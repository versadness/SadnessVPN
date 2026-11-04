"""Локальный API и Clash API ядра закрыты от чужих программ и сайтов."""
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine import core_config, ping
from engine.config import parse_link
from engine.core_config import build_proxy_config
from engine.wg_config import build_wg_tun_config
from ui import server

TOKEN = "T" * 43


class ApiTokenTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(server, "_API_TOKEN", TOKEN)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = server.app.test_client()

    def test_api_without_token_is_rejected(self):
        self.assertEqual(self.client.get("/api/hwid").status_code, 401)
        self.assertEqual(self.client.post("/api/disconnect", json={}).status_code, 401)

    def test_wrong_token_is_rejected(self):
        response = self.client.get("/api/hwid", headers={"X-Sadness-Token": "X" * 43})
        self.assertEqual(response.status_code, 401)

    def test_non_ascii_token_is_rejected_without_crash(self):
        response = self.client.get("/api/hwid", headers={"X-Sadness-Token": "тест"})
        self.assertEqual(response.status_code, 401)

    def test_header_token_is_accepted(self):
        response = self.client.get("/api/hwid", headers={"X-Sadness-Token": TOKEN})
        self.assertNotEqual(response.status_code, 401)

    def test_cookie_token_is_accepted(self):
        self.client.set_cookie("sadness_token", TOKEN)
        self.assertNotEqual(self.client.get("/api/hwid").status_code, 401)

    def test_launcher_and_updater_endpoints_stay_open(self):
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        self.assertNotEqual(self.client.get("/api/updates/state").status_code, 401)

    def test_foreign_origin_is_still_rejected_before_token(self):
        response = self.client.get("/api/hwid", headers={"X-Sadness-Token": TOKEN, "Origin": "https://evil.example"})
        self.assertEqual(response.status_code, 403)


class ApiTokenWithoutShellTests(unittest.TestCase):
    def test_backend_started_without_shell_keeps_working(self):
        with mock.patch.object(server, "_API_TOKEN", None):
            self.assertNotEqual(server.app.test_client().get("/api/hwid").status_code, 401)


class ApiTokenFileTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(server, "_API_TOKEN", None)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "api-token")

    def init(self):
        with mock.patch.dict(os.environ, {"SADNESS_API_TOKEN_FILE": self.path}):
            server._init_api_token()
        return server._API_TOKEN

    def test_token_file_is_created_private_and_matches(self):
        token = self.init()
        self.assertTrue(server._valid_token(token))
        self.assertEqual(Path(self.path).read_text(encoding="ascii"), token)
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)

    def test_reconnecting_shell_reuses_the_token(self):
        first = self.init()
        self.assertEqual(self.init(), first)

    def test_damaged_file_gets_a_fresh_token(self):
        Path(self.path).write_text("short", encoding="ascii")
        self.assertNotEqual(self.init(), "short")

    def test_no_shell_means_no_token(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            server._init_api_token()
        self.assertIsNone(server._API_TOKEN)


class ControllerSecretTests(unittest.TestCase):
    def assert_protected(self, config):
        self.assertEqual(config["secret"], core_config.CONTROLLER_SECRET)
        self.assertGreaterEqual(len(config["secret"]), 32)
        cors = config["external-controller-cors"]
        # Пустой список у mihomo означает «все источники».
        self.assertTrue(cors["allow-origins"])
        self.assertNotIn("*", cors["allow-origins"])
        self.assertFalse(cors["allow-private-network"])

    def test_proxy_config_requires_secret(self):
        node = parse_link("vless://11111111-2222-3333-4444-555555555555@198.51.100.7:443?security=tls&type=tcp&sni=example.com#t")
        self.assert_protected(build_proxy_config(node, clash_port=19090))

    def test_wireguard_config_requires_secret(self):
        self.assert_protected(build_wg_tun_config({
            "endpoint": "198.51.100.30", "port": 51820, "address": ["10.0.0.2/32"],
            "private_key": "A" * 43 + "=", "peer_public_key": "B" * 43 + "=",
        }, clash_port=19090))

    def test_tunnel_ping_sends_the_secret(self):
        connection = mock.MagicMock()
        connection.getresponse.return_value.status = 200
        connection.getresponse.return_value.read.return_value = b'{"delay": 42}'
        with mock.patch.object(ping.http.client, "HTTPConnection", return_value=connection):
            ping.tunnel_ping(clash_port=19090)
        headers = connection.request.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer " + core_config.CONTROLLER_SECRET)

    def test_backend_requests_to_core_send_the_secret(self):
        connection = mock.MagicMock()
        connection.getresponse.return_value.status = 204
        connection.getresponse.return_value.read.return_value = b""
        with mock.patch("http.client.HTTPConnection", return_value=connection):
            server._clash("PUT", "/proxies/proxy", {"name": "x"})
        headers = connection.request.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer " + core_config.CONTROLLER_SECRET)
        self.assertEqual(headers["Content-Type"], "application/json")


if __name__ == "__main__":
    unittest.main()
