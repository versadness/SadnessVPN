import unittest

from engine.wg_config import build_wg_tun_config, parse_wg_conf


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

            [Peer]
            PublicKey = BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=
            Endpoint = 198.51.100.30:51820
            AllowedIPs = 0.0.0.0/0
            """
        )

        self.assertTrue(servers[0]["is_awg"])
        self.assertEqual(servers[0]["awg_fields"]["jc"], "4")


class WireGuardRoutingConfigTests(unittest.TestCase):
    def setUp(self):
        self.server = {
            "endpoint": "198.51.100.30",
            "port": 51820,
            "address": ["10.0.0.2/32"],
            "private_key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
            "peer_public_key": "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=",
            "mtu": 1280,
        }

    def test_whitelist_routes_selected_process_to_proxy(self):
        config = build_wg_tun_config(
            self.server,
            routing_mode="whitelist",
            routed_apps=["browser.exe"],
        )

        rules = config["route"]["rules"]
        self.assertIn(
            {"process_name": ["browser.exe"], "outbound": "proxy"},
            rules,
        )
        self.assertEqual(rules[-1], {"outbound": "direct"})

    def test_default_config_contains_wireguard_outbound(self):
        config = build_wg_tun_config(self.server)

        outbound = config["outbounds"][0]
        self.assertEqual(outbound["type"], "wireguard")
        self.assertEqual(outbound["server"], "198.51.100.30")
        self.assertEqual(outbound["server_port"], 51820)


if __name__ == "__main__":
    unittest.main()
