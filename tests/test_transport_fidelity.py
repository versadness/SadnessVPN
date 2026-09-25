"""Транспорт сервера переносится без тихой подмены: либо точно, либо явный отказ."""
import json
import os
import subprocess
import tempfile
import unittest
import urllib.parse

from engine.config import parse_link
from engine.core_config import build_mihomo_config, ensure_supported, _mihomo_proxy
from engine.paths import bin_path
from engine.transports import parse_clash_nodes

MIHOMO = bin_path("mihomo.exe")
UUID = "00000000-0000-0000-0000-000000000001"


def ss_link(plugin):
    userinfo = "YWVzLTEyOC1nY206c2VjcmV0"  # aes-128-gcm:secret
    return f"ss://{userinfo}@203.0.113.5:8388/?plugin={urllib.parse.quote(plugin)}#SS"


class ShadowsocksPluginTests(unittest.TestCase):
    def test_simple_obfs_is_kept(self):
        server = parse_link(ss_link("obfs-local;obfs=http;obfs-host=cdn.example.com"))
        proxy = _mihomo_proxy(server)
        self.assertEqual(server["port"], 8388)
        self.assertEqual(proxy["plugin"], "obfs")
        self.assertEqual(proxy["plugin-opts"], {"mode": "http", "host": "cdn.example.com"})

    def test_v2ray_plugin_websocket_with_tls(self):
        server = parse_link(ss_link("v2ray-plugin;tls;host=cdn.example.com;path=/ws"))
        self.assertEqual(_mihomo_proxy(server)["plugin-opts"],
                         {"mode": "websocket", "tls": True, "host": "cdn.example.com", "path": "/ws"})

    def test_unknown_plugin_is_refused_not_dropped(self):
        with self.assertRaises(ValueError):
            parse_link(ss_link("kcptun;mode=fast"))

    def test_plain_ss_link_without_plugin_is_unchanged(self):
        server = parse_link("ss://YWVzLTEyOC1nY206c2VjcmV0@203.0.113.5:8388#SS")
        self.assertNotIn("plugin", _mihomo_proxy(server))

    def test_clash_node_plugin_is_kept_or_refused(self):
        base = """proxies:
  - name: SS
    type: ss
    server: 203.0.113.5
    port: 8388
    cipher: aes-128-gcm
    password: secret
    plugin: {plugin}
    plugin-opts:
      mode: tls
"""
        servers = parse_clash_nodes(base.format(plugin="obfs"))
        self.assertEqual(_mihomo_proxy(servers[0])["plugin-opts"], {"mode": "tls"})
        rejected = []
        self.assertEqual(parse_clash_nodes(base.format(plugin="restls"), rejected=rejected), [])
        self.assertIn("restls", rejected[0]["reason"])


class HttpHeaderObfsTests(unittest.TestCase):
    def test_vless_tcp_http_header_becomes_mihomo_http_network(self):
        server = parse_link(f"vless://{UUID}@203.0.113.5:80?type=tcp&headerType=http"
                            "&path=%2Fvideo&host=example.com#H")
        proxy = _mihomo_proxy(server)
        self.assertEqual(proxy["network"], "http")
        self.assertEqual(proxy["http-opts"], {"method": "GET", "path": ["/video"],
                                              "headers": {"Host": ["example.com"]}})

    def test_unsupported_header_is_refused(self):
        server = parse_link(f"vless://{UUID}@203.0.113.5:80?type=tcp&headerType=srtp#H")
        with self.assertRaises(ValueError):
            ensure_supported(server)

    def test_xray_type_http_still_means_h2(self):
        server = parse_link(f"vless://{UUID}@203.0.113.5:443?type=http&security=tls&path=%2Fh2#H")
        self.assertEqual(_mihomo_proxy(server)["network"], "h2")

    def test_clash_network_http_is_http11_obfs_not_h2(self):
        raw = f"""proxies:
  - name: VMess HTTP
    type: vmess
    server: 203.0.113.5
    port: 80
    uuid: {UUID}
    cipher: auto
    network: http
    http-opts:
      path: [/v]
      headers:
        Host: [example.com]
"""
        proxy = _mihomo_proxy(parse_clash_nodes(raw)[0])
        self.assertEqual(proxy["network"], "http")
        self.assertEqual(proxy["http-opts"]["path"], ["/v"])
        self.assertEqual(proxy["http-opts"]["headers"], {"Host": ["example.com"]})


class StoredServerIdentityTests(unittest.TestCase):
    def test_new_empty_parser_field_keeps_the_same_server_identity(self):
        # Иначе после обновления подписки терялись выбор и маршруты у серверов
        # с одинаковыми именами.
        from ui.profile_state import server_fingerprint
        stored = {"protocol": "vless", "host": "203.0.113.5", "port": 443, "type": "tcp", "ui_id": "a"}
        fresh = {**stored, "header_type": ""}
        self.assertEqual(server_fingerprint(stored), server_fingerprint(fresh))
        self.assertNotEqual(server_fingerprint(stored),
                            server_fingerprint({**stored, "header_type": "http"}))


@unittest.skipUnless(os.path.isfile(MIHOMO), "bin/mihomo.exe отсутствует")
class BundledCoreAcceptsTests(unittest.TestCase):
    def check(self, server):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "c.yaml")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(build_mihomo_config(server), handle)
            result = subprocess.run([MIHOMO, "-d", directory, "-f", path, "-t"],
                                    capture_output=True, text=True, encoding="utf-8",
                                    errors="replace", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout[-500:])

    def test_obfs_v2ray_plugin_and_http_header(self):
        self.check(parse_link(ss_link("obfs-local;obfs=tls;obfs-host=cdn.example.com")))
        self.check(parse_link(ss_link("v2ray-plugin;tls;host=cdn.example.com;path=/ws")))
        self.check(parse_link(f"vless://{UUID}@203.0.113.5:80?type=tcp&headerType=http"
                              "&path=%2Fvideo&host=example.com#H"))


if __name__ == "__main__":
    unittest.main()
