import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import urlencode

from engine.config import parse_link, fetch_subscription
from engine.core_config import build_proxy_config, choose_core, build_mihomo_config
from engine.transports import parse_clash_nodes
from engine.route_info import observed_app_routes
from engine.mihomo import MihomoManager

UUID = "11111111-1111-4111-8111-111111111111"


class MultiCoreTests(unittest.TestCase):
    def node(self, extra=None):
        query = {"type": "xhttp", "security": "tls", "sni": "example.com", "path": "/hello",
                 "mode": "packet-up", "flow": "none", "extra": json.dumps(extra or {})}
        return parse_link(f"vless://{UUID}@example.com:443?" + urlencode(query))

    def test_xhttp_auto_uses_mihomo_and_maps_nested_extra(self):
        server = self.node({"xmux": {"maxConcurrency": "16-32", "maxConnections": 0}})
        self.assertEqual(choose_core(server), "mihomo")
        proxy = build_proxy_config(server)["proxies"][0]
        self.assertEqual(proxy["network"], "xhttp")
        self.assertEqual(proxy["xhttp-opts"]["path"], "/hello")
        self.assertEqual(proxy["xhttp-opts"]["mode"], "packet-up")
        self.assertEqual(proxy["xhttp-opts"]["reuse-settings"],
                         {"max-concurrency": "16-32", "max-connections": 0})
        self.assertNotIn("flow", proxy)

    def test_unsupported_xhttp_option_is_reported_before_the_tun_comes_up(self):
        with self.assertRaisesRegex(ValueError, "не поддерживается"):
            choose_core(self.node({"scMaxBufferedPosts": 30}))

    def test_mihomo_rejects_unsupported_extra_instead_of_silently_dropping_it(self):
        with self.assertRaisesRegex(ValueError, "не поддерживается"):
            build_mihomo_config(self.node({"scStreamUpServerSecs": "20-80"}))

    def test_clash_yaml_preserves_transport_and_reality(self):
        nodes = parse_clash_nodes('''proxies:
  - name: "Reality node"
    type: vless
    server: example.com
    port: 443
    uuid: 11111111-1111-4111-8111-111111111111
    tls: true
    network: xhttp
    servername: www.example.com
    reality-opts: {public-key: fake-key, short-id: "00ab"}
    xhttp-opts:
      path: /exact/path
      host: www.example.com
      mode: stream-up
      reuse-settings: {max-concurrency: "16-32"}
''')
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["security"], "reality")
        self.assertEqual(nodes[0]["sid"], "00ab")
        proxy = build_proxy_config(nodes[0])["proxies"][0]
        self.assertEqual(proxy["xhttp-opts"]["path"], "/exact/path")
        self.assertEqual(proxy["xhttp-opts"]["reuse-settings"]["max-concurrency"], "16-32")
        self.assertEqual(proxy["reality-opts"]["short-id"], "00ab")

    def test_mihomo_auth_and_rule_modes(self):
        node = self.node()
        config = build_mihomo_config(node, routing_mode="whitelist", routed_apps=[],
                                     socks5_auth={"user": "hello", "pass": "world"}, allow_lan=True)
        self.assertEqual(config["rules"][-1], "MATCH,DIRECT")
        self.assertEqual(config["authentication"], ["hello:world"])
        self.assertEqual(config["skip-auth-prefixes"], [])
        config = build_mihomo_config(node, routing_mode="blacklist", routed_apps=["test.exe"])
        self.assertIn("PROCESS-NAME,test.exe,DIRECT", config["rules"])
        self.assertEqual(config["rules"][-1], "MATCH,proxy")

    def test_observed_routes_keep_mixed_and_unknown_distinct(self):
        rows = observed_app_routes([
            {"metadata": {"processPath": r"C:\Apps\chrome.exe", "network": "tcp"}, "chains": ["proxy"]},
            {"metadata": {"process": "chrome.exe", "network": "udp"}, "chains": ["DIRECT"]},
            {"metadata": {"process": "test.exe"}, "chains": []},
            {"metadata": {}, "chains": ["proxy"]},
        ])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["routes"], ["direct", "proxy"])
        self.assertEqual(rows[1]["routes"], ["unknown"])

    def test_bad_json_extra_does_not_turn_into_plain_tcp(self):
        with self.assertRaisesRegex(ValueError, "XHTTP"):
            parse_link(f"vless://{UUID}@example.com:443?type=xhttp&extra=not-json")
        with self.assertRaisesRegex(ValueError, "не поддерживает XHTTP"):
            build_proxy_config(self.node(), preference="singbox")

    def test_mihomo_default_tun_ipv4_and_subnet_collision(self):
        import ipaddress
        config = build_mihomo_config(self.node())
        self.assertFalse(config["ipv6"])
        self.assertNotIn("inet4-address", config["tun"])
        manager = MihomoManager()
        with patch.object(manager, "_assigned_ipv4_networks", return_value=[ipaddress.ip_network("172.19.0.0/30")]):
            self.assertTrue(manager._prepare_tun_addresses(config))
        self.assertEqual(config["dns"]["fake-ip-range"], "172.19.1.1/30")

    def test_mihomo_fake_dns_avoids_existing_range(self):
        import ipaddress
        config = build_mihomo_config(self.node(), fakedns=True)
        manager = MihomoManager()
        with patch.object(manager, "_assigned_ipv4_networks", return_value=[ipaddress.ip_network("198.18.0.0/16")]):
            self.assertTrue(manager._prepare_tun_addresses(config))
        self.assertEqual(config["dns"]["fake-ip-range"], "198.19.0.1/16")

    def test_mihomo_dns_failure_prevents_process_and_tun_start(self):
        import socket
        manager = MihomoManager()
        with patch("engine.mihomo.socket.getaddrinfo", side_effect=socket.gaierror()), patch("engine.singbox.SingBoxManager.start") as start:
            self.assertFalse(manager.start(build_mihomo_config(self.node())))
        start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
