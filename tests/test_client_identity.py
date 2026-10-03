import unittest
from unittest import mock

from engine import app_meta
from engine import config, wg_config
from engine.subscriptions import SubscriptionError


class ClientIdentityTests(unittest.TestCase):
    @mock.patch.object(app_meta.sys, "platform", "win32")
    @mock.patch.object(app_meta.platform, "machine", return_value="AMD64")
    @mock.patch.object(app_meta.platform, "version", return_value="10.0.26200")
    def test_subscription_user_agent_identifies_the_real_client(self, _version, _machine):
        user_agent = app_meta.subscription_user_agent()

        self.assertEqual(
            user_agent,
            f"SadnessVPN/v{app_meta.APP_VERSION} platform/windows "
            "platform-version/10.0.26200 arch/amd64",
        )
        self.assertNotIn("Clash", user_agent)

    @mock.patch.object(app_meta.sys, "platform", "linux")
    @mock.patch.object(app_meta.platform, "machine", return_value="x86_64")
    @mock.patch.object(app_meta.platform, "release", return_value="6.11.4-301.fc41.x86_64")
    def test_linux_client_reports_linux_not_windows(self, _release, _machine):
        headers = app_meta.subscription_headers()

        self.assertEqual(
            headers["User-Agent"],
            f"SadnessVPN/v{app_meta.APP_VERSION} platform/linux "
            "platform-version/6.11.4-301.fc41.x86_64 arch/amd64",
        )
        self.assertEqual(headers["X-Platform"], "linux")
        self.assertEqual(headers["X-Device-OS"], "Linux")
        self.assertEqual(headers["X-Ver-OS"], "6.11.4-301.fc41.x86_64")

    @mock.patch.object(app_meta.sys, "platform", "win32")
    def test_subscription_headers_include_hwid_and_client_metadata(self):
        headers = app_meta.subscription_headers("device-id")

        self.assertEqual(headers["X-Client-Name"], "Sadness VPN")
        self.assertEqual(headers["X-Client-Version"], app_meta.APP_VERSION)
        self.assertEqual(headers["HWID"], "device-id")
        self.assertEqual(headers["X-HWID"], "device-id")
        self.assertEqual(headers["Device-Id"], "device-id")
        self.assertEqual(headers["X-Device-OS"], "Windows")
        self.assertEqual(headers["X-Ver-OS"], app_meta.windows_version())
        self.assertEqual(headers["X-Device-Model"], "PC")

    def test_empty_hwid_is_not_sent(self):
        headers = app_meta.subscription_headers()

        self.assertNotIn("HWID", headers)
        self.assertNotIn("X-HWID", headers)
        self.assertNotIn("Device-Id", headers)

    def test_proxy_subscription_uses_shared_client_identity(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b""
        with mock.patch.object(config.urllib.request, "urlopen", return_value=response) as call:
            with self.assertRaises(SubscriptionError):
                config.fetch_subscription("https://example.test/sub", hwid="device-id-123")

        request = call.call_args.args[0]
        self.assertIn(f"SadnessVPN/v{app_meta.APP_VERSION}", request.get_header("User-agent"))
        self.assertEqual(request.get_header("Hwid"), "device-id-123")

    def test_wireguard_subscription_uses_shared_client_identity(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b""
        with mock.patch.object(wg_config.urllib.request, "urlopen", return_value=response) as call:
            with self.assertRaises(SubscriptionError):
                wg_config.fetch_wg_subscription("https://example.test/wg", hwid="device-id-123")

        request = call.call_args.args[0]
        self.assertIn(f"SadnessVPN/v{app_meta.APP_VERSION}", request.get_header("User-agent"))
        self.assertEqual(request.get_header("Hwid"), "device-id-123")


if __name__ == "__main__":
    unittest.main()
