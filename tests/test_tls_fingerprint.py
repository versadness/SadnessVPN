import unittest

from engine.core_config import apply_tls_fingerprint
from ui import app_state


def config():
    return {"proxies": [
        {"name": "a", "type": "vless", "tls": True, "client-fingerprint": "chrome"},
        {"name": "b", "type": "vless", "tls": True},
        {"name": "c", "type": "vless", "tls": False},
        {"name": "d", "type": "trojan"},
        {"name": "e", "type": "hysteria2"},
        {"name": "f", "type": "ss"},
        {"name": "g", "type": "vmess", "tls": True, "client-fingerprint": "random"},
    ]}


class TlsFingerprintTests(unittest.TestCase):
    def test_default_is_firefox(self):
        self.assertEqual(app_state.DEFAULT_SETTINGS["tls_fingerprint"], "firefox")

    def test_every_tls_server_including_backups_gets_the_choice(self):
        cfg = apply_tls_fingerprint(config(), "edge")
        fps = {p["name"]: p.get("client-fingerprint") for p in cfg["proxies"]}
        self.assertEqual(fps, {"a": "edge", "b": "edge", "c": None, "d": "edge", "e": None, "f": None, "g": "edge"})

    def test_provider_keeps_subscription_values(self):
        cfg = apply_tls_fingerprint(config(), "provider")
        self.assertEqual(cfg["proxies"][0]["client-fingerprint"], "chrome")
        self.assertNotIn("client-fingerprint", cfg["proxies"][1])

    def test_unknown_values_are_rejected(self):
        with self.assertRaises(ValueError):
            app_state.normalize_tunnel_setting("tls_fingerprint", "randomized")
        self.assertEqual(app_state.normalize_tunnel_setting("tls_fingerprint", "firefox"), "firefox")
