import base64
import json
import unittest

from engine.config import parse_link
from engine.core_config import build_mihomo_config


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

    def test_parse_vmess_link(self):
        payload = base64.b64encode(json.dumps({
            "ps": "Test VMess", "add": "vpn.example.com", "port": "443",
            "id": "00000000-0000-0000-0000-000000000000", "aid": "0",
            "net": "ws", "path": "/vm", "host": "edge.example.com", "tls": "tls",
        }).encode()).decode()
        server = parse_link("vmess://" + payload)

        self.assertEqual(server["protocol"], "vmess")
        self.assertEqual(server["remark"], "Test VMess")
        self.assertEqual(server["type"], "ws")
        self.assertEqual(server["security"], "tls")
        self.assertEqual(server["alter_id"], 0)

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
    """Маршрутизация собирается ядром Mihomo — второго ядра в проекте нет."""

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
        config = build_mihomo_config(
            self.server,
            routing_mode="whitelist",
            routed_apps=["chrome.exe"],
        )

        rules = config["rules"]
        self.assertIn("PROCESS-NAME,chrome.exe,proxy", rules)
        self.assertEqual(rules[-1], "MATCH,DIRECT")
        self.assertEqual(config["find-process-mode"], "always")

    def test_blacklist_routes_selected_process_directly(self):
        config = build_mihomo_config(
            self.server,
            routing_mode="blacklist",
            routed_apps=["game.exe"],
        )

        self.assertIn("PROCESS-NAME,game.exe,DIRECT", config["rules"])
        self.assertEqual(config["rules"][-1], "MATCH,proxy")

    def test_lan_mode_opens_only_the_proxy_listeners(self):
        config = build_mihomo_config(self.server, allow_lan=True)
        self.assertTrue(config["allow-lan"])
        self.assertEqual(config["bind-address"], "*")
        # TUN не становится доступным из локальной сети вместе с прокси.
        self.assertNotIn("listen", config["tun"])

    def test_local_bind_is_the_default(self):
        config = build_mihomo_config(self.server)
        self.assertFalse(config["allow-lan"])
        self.assertEqual(config["bind-address"], "127.0.0.1")

    def test_tun_subnet_comes_from_the_dns_block(self):
        config = build_mihomo_config(self.server)
        self.assertTrue(config["tun"]["enable"])
        self.assertEqual(config["dns"]["fake-ip-range"], "172.19.0.1/30")
        self.assertEqual(config["dns"]["enhanced-mode"], "redir-host")

    def test_adguard_ui_preset_builds_adguard_dns_servers(self):
        config = build_mihomo_config(self.server, dns_preset="adguard")
        self.assertEqual(config["dns"]["nameserver"],
                         ["tls://94.140.14.14", "tls://94.140.15.15"])

    def test_smart_dns_preset_bootstraps_through_its_own_raw_address(self):
        config = build_mihomo_config(self.server, dns_preset="xbox_dot")
        dns = config["dns"]
        self.assertEqual(dns["nameserver"], ["tls://xbox-dns.ru", "tls://xbox-dns.ru"])
        self.assertEqual(dns["default-nameserver"], ["111.88.96.50"])
        # Адрес самого VPN-сервера резолвится обычным публичным DNS.
        self.assertEqual(dns["proxy-server-nameserver"], ["1.1.1.1", "8.8.8.8"])
        self.assertFalse(dns["respect-rules"])
        self.assertFalse(config["ipv6"])

    def test_block_udp_precedes_process_rules(self):
        config = build_mihomo_config(self.server, block_udp=True,
                                     routing_mode="whitelist", routed_apps=["a.exe"])
        rules = config["rules"]
        self.assertLess(rules.index("NETWORK,UDP,REJECT"),
                        rules.index("PROCESS-NAME,a.exe,proxy"))


if __name__ == "__main__":
    unittest.main()
