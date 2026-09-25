import unittest
import base64
from unittest.mock import patch

from engine.config import parse_link, fetch_subscription
from engine.core_config import build_mihomo_config, ensure_supported
from engine.transports import parse_clash_nodes


class Hysteria2Tests(unittest.TestCase):
    def test_subscription_plain_and_base64(self):
        raw = b"hy2://password@example.com:443/?sni=example.com#Test\nhysteria2://second@example.net/"
        for payload in (raw, base64.b64encode(raw)):
            with patch("engine.config.download_subscription", return_value=(payload, {})):
                nodes = fetch_subscription("https://example.invalid/test")
                self.assertEqual(len(nodes), 2)
                self.assertTrue(all(n["protocol"] == "hysteria2" for n in nodes))

    def test_official_slash_form_and_alias(self):
        for scheme in ("hy2", "hysteria2"):
            node = parse_link(f"{scheme}://user:p%40ss@vpn.example:443/?sni=tls.example#My%20HY2")
            self.assertEqual((node["host"], node["port"], node["password"]), ("vpn.example", 443, "user:p@ss"))
            self.assertEqual(node["remark"], "My HY2")
            self.assertEqual((node["type"], node["security"]), ("quic", "tls"))

    def test_ipv6_and_default_port(self):
        for address in ("[2001:db8::1]", "[2001:db8::1]:443"):
            node = parse_link(f"hy2://secret@{address}/")
            self.assertEqual((node["host"], node["port"]), ("2001:db8::1", 443))
        self.assertEqual(parse_link("hy2://example.com/")["host"], "example.com")

    def test_plain_hy2_defaults_secure_and_native_mux(self):
        node = parse_link("hy2://p@example.com/?alpn=h3")
        proxy = build_mihomo_config(node, mux=True)["proxies"][0]
        self.assertFalse(proxy["skip-cert-verify"])
        self.assertEqual(proxy["alpn"], ["h3"])
        # У Hysteria 2 собственное мультиплексирование: smux добавлять нельзя.
        self.assertNotIn("smux", proxy)

    def test_hopping_keeps_every_port_in_the_single_core(self):
        node = parse_link("hy2://p@example.com:443,5000-5010/")
        self.assertEqual(build_mihomo_config(node)["proxies"][0]["ports"], "443,5000-5010")

    def test_pin_is_preserved(self):
        node = parse_link("hy2://p@example.com/?pinSHA256=" + ":".join(["AB"] * 32))
        self.assertEqual(build_mihomo_config(node)["proxies"][0]["fingerprint"], "ab" * 32)

    def test_salamander(self):
        node = parse_link("hy2://p@example.com/?insecure=1&obfs=salamander&obfs-password=a%2Bb")
        proxy = build_mihomo_config(node)["proxies"][0]
        self.assertEqual((proxy["obfs"], proxy["obfs-password"]), ("salamander", "a+b"))
        self.assertTrue(proxy["skip-cert-verify"])

    def test_clash_hy2_retains_fields(self):
        node = parse_clash_nodes('''proxies:
  - name: HY2
    type: hy2
    server: example.com
    port: 443
    ports: 443,5000-5010
    hop-interval: 20
    password: password
    up: 20 Mbps
    down: 100 Mbps
    alpn: [h3]
    obfs: salamander
    obfs-password: other
''')[0]
        self.assertEqual(node["type"], "quic")
        proxy = build_mihomo_config(node)["proxies"][0]
        self.assertEqual((proxy["hop-interval"], proxy["up"], proxy["down"]), (20, "20 Mbps", "100 Mbps"))

    def test_unsupported_options_do_not_silently_weaken_connection(self):
        for suffix in ("?obfs=unknown", "?obfs=salamander", "?ech=not!base64", "?pinSHA256=bad", "?insecure=garbage"):
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                parse_link("hy2://p@example.com/" + suffix)
        with self.assertRaisesRegex(ValueError, "не поддерживается ядром Mihomo"):
            ensure_supported({"protocol": "wireguard", "host": "example.com", "port": 443})

    def test_ech_link_reaches_the_core_without_being_dropped(self):
        server = parse_link("hy2://p@example.com:443?sni=example.com&ech=AEX%2BDQBB")
        proxy = build_mihomo_config(server)["proxies"][0]
        self.assertEqual(proxy["ech-opts"], {"enable": True, "config": "AEX+DQBB"})

    def test_clash_ech_block_is_honoured_including_the_off_switch(self):
        node = """proxies:
  - name: "hy2 ech"
    type: hysteria2
    server: example.com
    port: 443
    password: p
    ech-opts:
      enable: true
      config: AEX+DQBB
"""
        server = parse_clash_nodes(node)[0]
        self.assertEqual(build_mihomo_config(server)["proxies"][0]["ech-opts"],
                         {"enable": True, "config": "AEX+DQBB"})
        server["ech"] = {"enable": False, "config": "AEX+DQBB"}
        self.assertNotIn("ech-opts", build_mihomo_config(server)["proxies"][0])

    def test_realm_stays_blocked_because_mihomo_needs_a_control_server(self):
        node = """proxies:
  - name: "hy2 realm"
    type: hysteria2
    server: example.com
    port: 443
    password: p
    realm-opts:
      enable: true
"""
        # Узел по-прежнему не импортируется, но теперь отказ записывается
        # с причиной, а не обрывает импорт всей подписки.
        rejected = []
        self.assertEqual(parse_clash_nodes(node, rejected=rejected), [])
        self.assertEqual(rejected[0]["name"], "hy2 realm")
        self.assertIn("control-сервера", rejected[0]["reason"])

    def test_invalid_endpoints(self):
        for address in ("", ":443", "example.com:0", "example.com:65536", "example.com:10-1", "example.com:443,,444", "example.com:abc"):
            with self.subTest(address=address), self.assertRaises(ValueError):
                parse_link("hy2://p@" + address)


if __name__ == "__main__":
    unittest.main()
