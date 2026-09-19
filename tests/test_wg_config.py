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

    def test_lan_mode_exposes_only_proxy_inbounds(self):
        config = build_wg_tun_config(self.server, allow_lan=True)
        listens = {
            inbound["tag"]: inbound.get("listen")
            for inbound in config["inbounds"]
        }

        self.assertEqual(listens["socks-in"], "0.0.0.0")
        self.assertEqual(listens["http-in"], "0.0.0.0")
        self.assertNotEqual(listens["tun-in"], "0.0.0.0")

    def test_tun_uses_current_address_field(self):
        inbound = build_wg_tun_config(self.server)["inbounds"][0]
        self.assertEqual(inbound["address"], ["172.19.0.1/30"])
        self.assertNotIn("inet4_address", inbound)


if __name__ == "__main__":
    unittest.main()
