import base64
import unittest

from engine.config import build_xray_tun_config, parse_link


class ProxyLinkParsingTests(unittest.TestCase):
    def test_parse_vless_link(self):
        server = parse_link(
            "vless://00000000-0000-0000-0000-000000000000@vpn.example.com:443"
            "?security=tls&type=ws&sni=edge.example.com&path=%2Fvpn#Test%20VLESS"
        )

        self.assertEqual(server["remark"], "Test VLESS")
        self.assertEqual(server["host"], "vpn.example.com")
        self.assertEqual(server["port"], 443)
        self.assertEqual(server["security"], "tls")
        self.assertEqual(server["type"], "ws")
        self.assertEqual(server["path"], "/vpn")

    def test_parse_shadowsocks_link(self):
        credentials = base64.b64encode(b"aes-256-gcm:test-password").decode("ascii")
        server = parse_link(f"ss://{credentials}@198.51.100.10:8388#Test%20SS")

        self.assertEqual(server["protocol"], "ss")
        self.assertEqual(server["method"], "aes-256-gcm")
        self.assertEqual(server["password"], "test-password")
        self.assertEqual(server["port"], 8388)

    def test_parse_trojan_link(self):
        server = parse_link(
            "trojan://test-password@vpn.example.com:443"
            "?sni=edge.example.com&type=grpc&serviceName=vpn#Test%20Trojan"
        )

        self.assertEqual(server["protocol"], "trojan")
        self.assertEqual(server["password"], "test-password")
        self.assertEqual(server["type"], "grpc")
        self.assertEqual(server["serviceName"], "vpn")

    def test_parse_hysteria2_link(self):
        server = parse_link(
            "hysteria2://test-password@vpn.example.com:443"
            "?sni=edge.example.com&obfs=salamander&obfs-password=obfs#Test%20HY2"
        )

        self.assertEqual(server["protocol"], "hysteria2")
        self.assertEqual(server["password"], "test-password")
        self.assertEqual(server["obfs"], "salamander")
        self.assertEqual(server["obfs_password"], "obfs")


class ProxyRoutingConfigTests(unittest.TestCase):
    def setUp(self):
        self.server = {
            "host": "198.51.100.20",
            "port": 443,
            "uuid": "00000000-0000-0000-0000-000000000000",
            "security": "tls",
            "sni": "vpn.example.com",
            "type": "tcp",
        }

    def test_whitelist_routes_selected_process_to_proxy(self):
        config = build_xray_tun_config(
            self.server,
            routing_mode="whitelist",
            routed_apps=["chrome.exe"],
        )

        rules = config["route"]["rules"]
        self.assertIn(
            {"process_name": ["chrome.exe"], "outbound": "proxy"},
            rules,
        )
        self.assertEqual(rules[-1], {"outbound": "direct"})
        self.assertTrue(config["route"]["find_process"])

    def test_blacklist_routes_selected_process_directly(self):
        config = build_xray_tun_config(
            self.server,
            routing_mode="blacklist",
            routed_apps=["game.exe"],
        )

        self.assertIn(
            {"process_name": ["game.exe"], "outbound": "direct"},
            config["route"]["rules"],
        )
        self.assertEqual(config["route"]["final"], "proxy")

    def test_lan_mode_exposes_only_proxy_inbounds(self):
        config = build_xray_tun_config(self.server, allow_lan=True)
        listens = {
            inbound["tag"]: inbound.get("listen")
            for inbound in config["inbounds"]
        }

        self.assertEqual(listens["socks-in"], "0.0.0.0")
        self.assertEqual(listens["http-in"], "0.0.0.0")
        self.assertNotEqual(listens["tun-in"], "0.0.0.0")

    def test_adguard_ui_preset_builds_adguard_dns_servers(self):
        config = build_xray_tun_config(self.server, dns_preset="adguard")
        addresses = [item["address"] for item in config["dns"]["servers"]]

        self.assertIn("tls://94.140.14.14", addresses)
        self.assertIn("tls://94.140.15.15", addresses)


if __name__ == "__main__":
    unittest.main()
