import json
import os
import subprocess
import tempfile
import unittest

from engine.paths import bin_path
from engine.wg_config import build_wg_tun_config, parse_wg_conf

MIHOMO = bin_path("mihomo.exe")


class WireGuardParsingTests(unittest.TestCase):
    def test_parse_basic_wireguard_config(self):
        servers = parse_wg_conf(
            """
            [Interface]
            PrivateKey = AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
            Address = 10.0.0.2/32
            DNS = 1.1.1.1

            [Peer]
            PublicKey = BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=
            Endpoint = 198.51.100.30:51820
            AllowedIPs = 0.0.0.0/0
            """
        )

        self.assertEqual(len(servers), 1)
        server = servers[0]
        self.assertEqual(server["endpoint"], "198.51.100.30")
        self.assertEqual(server["port"], 51820)
        self.assertEqual(server["address"], ["10.0.0.2/32"])
        self.assertEqual(server["dns"], ["1.1.1.1"])
        self.assertFalse(server["is_awg"])

    def test_detect_amnezia_fields(self):
        servers = parse_wg_conf(
            """
            [Interface]
            PrivateKey = AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
            Address = 10.0.0.2/32
            Jc = 4
            S3 = 32
            I1 = <b 0x0c><r 16>

            [Peer]
            PublicKey = BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=
            Endpoint = 198.51.100.30:51820
            AllowedIPs = 0.0.0.0/0
            PersistentKeepalive = 19
            """
        )

        self.assertTrue(servers[0]["is_awg"])
        self.assertEqual(servers[0]["awg_fields"]["jc"], "4")
        self.assertEqual(servers[0]["awg_fields"]["s3"], "32")
        self.assertEqual(servers[0]["awg_fields"]["i1"], "<b 0x0c><r 16>")
        self.assertEqual(servers[0]["persistent_keepalive"], 19)
        self.assertEqual(servers[0]["source_allowed_ips"], ["0.0.0.0/0"])


class WireGuardRoutingConfigTests(unittest.TestCase):
    """Обычный WireGuard собирается в конфигурацию Mihomo, а не sing-box."""

    def setUp(self):
        self.server = {
            "endpoint": "198.51.100.30",
            "port": 51820,
            "address": ["10.0.0.2/32", "fd00::2/128"],
            "private_key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
            "peer_public_key": "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=",
            "mtu": 1280,
            "persistent_keepalive": 25,
        }

    def test_config_is_mihomo_with_tun_and_controller(self):
        config = build_wg_tun_config(self.server, clash_port=19090)
        for sing_box_key in ("inbounds", "outbounds", "route"):
            self.assertNotIn(sing_box_key, config)
        self.assertTrue(config["tun"]["enable"])
        self.assertEqual(config["external-controller"], "127.0.0.1:19090")

    def test_wireguard_outbound_fields(self):
        proxy = build_wg_tun_config(self.server)["proxies"][0]
        self.assertEqual(proxy["name"], "proxy")
        self.assertEqual(proxy["type"], "wireguard")
        self.assertEqual(proxy["server"], "198.51.100.30")
        self.assertEqual(proxy["port"], 51820)
        self.assertEqual(proxy["ip"], "10.0.0.2")
        self.assertEqual(proxy["ipv6"], "fd00::2")
        self.assertEqual(proxy["private-key"], self.server["private_key"])
        self.assertEqual(proxy["public-key"], self.server["peer_public_key"])
        self.assertEqual(proxy["persistent-keepalive"], 25)
        self.assertNotIn("smux", build_wg_tun_config(self.server, mux=True)["proxies"][0])

    def test_whitelist_routes_selected_process_to_proxy(self):
        rules = build_wg_tun_config(
            self.server, routing_mode="whitelist", routed_apps=["browser.exe"],
        )["rules"]
        self.assertIn("PROCESS-NAME,browser.exe,proxy", rules)
        self.assertEqual(rules[-1], "MATCH,DIRECT")

    def test_lan_mode_opens_only_proxy_listeners(self):
        config = build_wg_tun_config(self.server, allow_lan=True)
        self.assertEqual(config["bind-address"], "*")
        self.assertTrue(config["allow-lan"])

    def test_awg_server_is_refused(self):
        with self.assertRaises(ValueError):
            build_wg_tun_config({**self.server, "is_awg": True})

    @unittest.skipUnless(os.path.isfile(MIHOMO), "bin/mihomo.exe отсутствует")
    def test_bundled_mihomo_accepts_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "wg.yaml")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(build_wg_tun_config(self.server), handle)
            result = subprocess.run([MIHOMO, "-d", directory, "-f", path, "-t"],
                                    capture_output=True, text=True, encoding="utf-8",
                                    errors="replace", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout[-500:])


if __name__ == "__main__":
    unittest.main()
