import unittest
import base64
from unittest.mock import patch

from engine.config import parse_link, _build_singbox_outbound, fetch_subscription
from engine.core_config import choose_core, build_mihomo_config
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
        out = _build_singbox_outbound(node, mux=True)
        self.assertFalse(out["tls"]["insecure"])
        self.assertEqual(out["tls"]["alpn"], ["h3"])
        self.assertNotIn("multiplex", out)
        self.assertNotIn("smux", build_mihomo_config(node, mux=True)["proxies"][0])
        self.assertEqual(choose_core(node), "singbox")

    def test_hopping_selects_mihomo_without_dropping_ports(self):
        node = parse_link("hy2://p@example.com:443,5000-5010/")
        self.assertEqual(choose_core(node), "mihomo")
        self.assertEqual(build_mihomo_config(node)["proxies"][0]["ports"], "443,5000-5010")
        for action in (lambda: choose_core(node, "singbox"), lambda: _build_singbox_outbound(node)):
            with self.assertRaisesRegex(ValueError, "Mihomo"):
                action()

    def test_pin_is_preserved_and_routes_to_capable_core(self):
        node = parse_link("hy2://p@example.com/?pinSHA256=" + ":".join(["AB"] * 32))
        self.assertEqual(choose_core(node), "mihomo")
        self.assertEqual(build_mihomo_config(node)["proxies"][0]["fingerprint"], "ab" * 32)

    def test_salamander(self):
        node = parse_link("hy2://p@example.com/?insecure=1&obfs=salamander&obfs-password=a%2Bb")
        out = _build_singbox_outbound(node)
        self.assertEqual(out["obfs"], {"type": "salamander", "password": "a+b"})
        self.assertTrue(out["tls"]["insecure"])

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
        for suffix in ("?obfs=unknown", "?obfs=salamander", "?ech=secret", "?pinSHA256=bad", "?insecure=garbage"):
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                parse_link("hy2://p@example.com/" + suffix)
        with self.assertRaisesRegex(ValueError, "Неизвестное ядро"):
            choose_core(parse_link("hy2://p@example.com/"), "xray")

    def test_invalid_endpoints(self):
        for address in ("", ":443", "example.com:0", "example.com:65536", "example.com:10-1", "example.com:443,,444", "example.com:abc"):
            with self.subTest(address=address), self.assertRaises(ValueError):
                parse_link("hy2://p@" + address)


if __name__ == "__main__":
    unittest.main()
