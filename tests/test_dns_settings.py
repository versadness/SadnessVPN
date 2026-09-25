"""Свой DNS: адреса проверяются при сохранении, пустой пресет не подменяется молча."""
import unittest
from unittest import mock

from ui import app_state, server

BASE = "http://127.0.0.1:45678"


class CustomDnsValidationTests(unittest.TestCase):
    def test_addresses_and_encrypted_servers_are_accepted(self):
        self.assertEqual(
            app_state.normalize_custom_dns(" 9.9.9.9 ,tls://dns.quad9.net,https://dns.google/dns-query "),
            "9.9.9.9, tls://dns.quad9.net, https://dns.google/dns-query")

    def test_hostname_without_scheme_and_garbage_are_rejected(self):
        for value in ("dns.google", "tls://bad host", "1.2.3", "ftp://x"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                app_state.normalize_custom_dns(value)


class CustomDnsPresetRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = server.app.test_client()
        for patcher in (
            mock.patch.dict(server._app_settings, {"dns_preset": "cf_google", "custom_dns": ""}),
            mock.patch.object(app_state, "save_settings", return_value=True),
            mock.patch("ui.routes.settings.deps.broadcast"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def post(self, payload):
        return self.client.post("/api/tunnel-settings", json=payload, base_url=BASE).get_json()

    def test_custom_preset_requires_addresses(self):
        result = self.post({"dns_preset": "custom"})
        self.assertFalse(result["ok"])
        self.assertEqual(server._app_settings["dns_preset"], "cf_google")

    def test_custom_preset_with_addresses_is_saved(self):
        self.assertTrue(self.post({"custom_dns": "9.9.9.9"})["ok"])
        self.assertTrue(self.post({"dns_preset": "custom"})["ok"])
        self.assertEqual(server._app_settings["dns_preset"], "custom")


if __name__ == "__main__":
    unittest.main()
