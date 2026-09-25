"""Регрессии неполного обновления подписок.

Образцы повторяют реальную выдачу панели Remnawave на немецком сервере
(base64 со ссылками VLESS XHTTP REALITY + Hysteria2 и Mihomo YAML), но все
секреты заменены: UUID, ключи REALITY, shortId и адреса — вымышленные.
"""
import base64
import gzip
import io
import json
import urllib.error
import unittest
from unittest.mock import MagicMock, patch

from engine.config import fetch_subscription, parse_share_links
from engine.subscriptions import SubscriptionNotModified, download_subscription
from engine.core_config import _mihomo_proxy

UUID = "11111111-2222-4333-8444-555555555555"
PBK = "TESTpublicKEYtestPUBLICkeyTESTpublicKEYte12"
SID = "0a1b2c3d"

XHTTP_DE = (f"vless://{UUID}@203.0.113.10:30444?encryption=none&type=xhttp"
            "&path=%2Freality-0000000000000000&mode=auto&security=reality"
            f"&sni=example.com&fp=edge&pbk={PBK}&sid={SID}"
            "#%F0%9F%87%A9%F0%9F%87%AA%20Germany%20VLESS-XHTTP")
XHTTP_FI_RELAY = XHTTP_DE.replace(":30444?", ":10446?").replace(
    "%F0%9F%87%A9%F0%9F%87%AA%20Germany", "%F0%9F%87%AB%F0%9F%87%AE%20Finland")
HY2_DE = f"hysteria2://{UUID}@203.0.113.10:443/?sni=vpn.example.test#%F0%9F%87%A9%F0%9F%87%AA%20Germany%20HY2"
HY2_FI = f"hysteria2://{UUID}@203.0.113.10:10445/?sni=vpn.example.test#%F0%9F%87%AB%F0%9F%87%AE%20Finland%20HY2"
REMNAWAVE_BASE64 = base64.b64encode("\n".join([XHTTP_FI_RELAY, XHTTP_DE, HY2_DE, HY2_FI]).encode())

MIHOMO_YAML = f"""mixed-port: 7890
proxies:
  - name: "🇩🇪 Germany VLESS-XHTTP"
    type: vless
    server: 203.0.113.10
    port: 30444
    network: xhttp
    udp: true
    uuid: {UUID}
    packet-encoding: xudp
    tls: true
    servername: example.com
    reality-opts: {{public-key: {PBK}, short-id: {SID}}}
    xhttp-opts: {{path: /reality-0000000000000000, mode: auto}}
    client-fingerprint: edge
  - name: "🇩🇪 Germany HY2"
    type: hysteria2
    server: 203.0.113.10
    port: 443
    udp: true
    password: {UUID}
    sni: vpn.example.test
  - name: "TUIC node"
    type: tuic
    server: 203.0.113.11
    port: 443
  - name: "Broken HY2"
    type: hysteria2
    server: 203.0.113.12
    port: 443
    password: test
    obfs: gecko
proxy-groups:
  - {{name: "→ Remnawave", type: select, proxies: ["🇩🇪 Germany VLESS-XHTTP", "🇩🇪 Germany HY2"]}}
rules: [MATCH,→ Remnawave]
"""


def fetch(body, metadata=None):
    with patch("engine.config.download_subscription", return_value=(body, metadata or {})):
        return fetch_subscription("https://example.test/sub/secret-token")


class RemnawaveFormatTests(unittest.TestCase):
    def test_base64_keeps_every_node_and_all_xhttp_reality_fields(self):
        servers = fetch(REMNAWAVE_BASE64)
        self.assertEqual(len(servers), 4)
        self.assertEqual(servers.metadata["received"], 4)
        self.assertEqual(servers.metadata["accepted"], 4)
        self.assertEqual(servers.metadata["rejected"], [])
        fi = servers[0]
        self.assertEqual((fi["host"], fi["port"]), ("203.0.113.10", 10446))
        proxy = _mihomo_proxy(servers[1])
        self.assertEqual(proxy["network"], "xhttp")
        self.assertEqual(proxy["xhttp-opts"], {"path": "/reality-0000000000000000", "host": "", "mode": "auto"})
        self.assertEqual(proxy["reality-opts"], {"public-key": PBK, "short-id": SID})
        self.assertEqual(proxy["servername"], "example.com")
        self.assertEqual(proxy["client-fingerprint"], "edge")
        hy2 = _mihomo_proxy(servers[2])
        self.assertEqual((hy2["type"], hy2["port"], hy2["sni"]), ("hysteria2", 443, "vpn.example.test"))

    def test_mihomo_yaml_bad_node_does_not_block_the_rest(self):
        servers = fetch(MIHOMO_YAML.encode())
        self.assertEqual([s["remark"] for s in servers], ["🇩🇪 Germany VLESS-XHTTP", "🇩🇪 Germany HY2"])
        rejected = {item["name"]: item["reason"] for item in servers.metadata["rejected"]}
        self.assertIn("TUIC node", rejected)
        self.assertIn("tuic", rejected["TUIC node"])
        self.assertIn("Broken HY2", rejected)
        self.assertEqual(servers.metadata["received"], 4)
        self.assertEqual(_mihomo_proxy(servers[0])["xhttp-opts"]["mode"], "auto")

    def test_unsupported_and_broken_links_are_reported_not_silently_dropped(self):
        body = "\n".join([XHTTP_DE, "tuic://secret@203.0.113.5:443#TUIC%20node",
                          "vless://broken@203.0.113.6:notaport#Broken%20VLESS", HY2_DE]).encode()
        servers = fetch(body)
        self.assertEqual(len(servers), 2)
        self.assertEqual(servers.metadata["received"], 4)
        names = [item["name"] for item in servers.metadata["rejected"]]
        self.assertEqual(names, ["TUIC node", "Broken VLESS"])
        # Причина отказа не содержит секретов ссылки.
        self.assertNotIn("secret", json.dumps(servers.metadata, ensure_ascii=False))

    def test_xhttp_download_settings_rejected_with_reason(self):
        extra = '{"downloadSettings":{"address":"203.0.113.7"}}'
        link = XHTTP_DE.replace("&mode=auto", "&mode=auto&extra=" + __import__("urllib.parse").parse.quote(extra))
        servers, rejected, received = parse_share_links(link + "\n" + HY2_DE)
        self.assertEqual((len(servers), received), (1, 2))
        self.assertIn("downloadSettings", rejected[0]["reason"])

    def test_all_rejected_is_an_error_that_keeps_current_servers(self):
        from engine.subscriptions import SubscriptionError
        with self.assertRaises(SubscriptionError) as caught:
            fetch(b"tuic://x@203.0.113.5:443#Only%20TUIC")
        self.assertIn("Only TUIC", str(caught.exception))
        self.assertIn("сохранены", str(caught.exception))
        self.assertEqual(caught.exception.metadata["accepted"], 0)

    def test_crlf_and_blank_lines(self):
        body = ("\r\n" + XHTTP_DE + "\r\n\r\n" + HY2_DE + "\r\n").encode()
        self.assertEqual(len(fetch(base64.b64encode(body))), 2)


class TransportTests(unittest.TestCase):
    def _response(self, body, encoding=""):
        response = MagicMock()
        inner = response.__enter__.return_value
        inner.read.return_value = body
        inner.headers = {"Content-Encoding": encoding} if encoding else {}
        return response

    def test_gzip_body_is_decompressed(self):
        packed = gzip.compress(REMNAWAVE_BASE64)
        with patch("urllib.request.urlopen", return_value=self._response(packed, "gzip")):
            body, _ = download_subscription("https://example.test/sub")
        self.assertEqual(body, REMNAWAVE_BASE64)

    def test_304_is_not_an_empty_subscription(self):
        error = urllib.error.HTTPError("https://example.test/secret", 304, "Not Modified", {}, io.BytesIO(b""))
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(SubscriptionNotModified) as caught:
                download_subscription("https://example.test/secret")
        self.assertNotIn("secret", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
