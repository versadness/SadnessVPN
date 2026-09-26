import unittest
from unittest import mock
import json
import tempfile
from pathlib import Path

from ui import server
from ui import profile_state


class LocalApiBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.client = server.app.test_client()

    def test_health_identifies_this_exact_server_instance(self):
        response = self.client.get(
            "/api/health",
            base_url="http://127.0.0.1:45678",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["instance"], server.SERVER_INSTANCE_ID)
        self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])
        self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")

    def test_dns_rebinding_host_is_rejected(self):
        response = self.client.get("/api/health", base_url="http://attacker.invalid")

        self.assertEqual(response.status_code, 403)

    def test_cross_origin_browser_request_is_rejected(self):
        response = self.client.get(
            "/api/health",
            base_url="http://127.0.0.1:45678",
            headers={"Origin": "https://attacker.invalid"},
        )

        self.assertEqual(response.status_code, 403)

    def test_non_loopback_client_is_rejected(self):
        response = self.client.get(
            "/api/health",
            base_url="http://127.0.0.1:45678",
            environ_base={"REMOTE_ADDR": "192.0.2.10"},
        )

        self.assertEqual(response.status_code, 403)

    def test_invalid_or_reserved_proxy_ports_are_rejected_without_mutation(self):
        ports = lambda: (server._app_settings["socks"], server._app_settings["http"])
        original = ports()
        cases = (
            {"socks": 0, "http": 8080},
            {"socks": 8080, "http": 8080},
            {"socks": 45678, "http": 8080},
            {"socks": 1080, "http": 9090},
        )

        for payload in cases:
            with self.subTest(payload=payload):
                response = self.client.post(
                    "/api/settings",
                    json=payload,
                    base_url="http://127.0.0.1:45678",
                )
                self.assertFalse(response.get_json()["ok"])
                self.assertEqual(ports(), original)

    def test_wireguard_file_name_becomes_the_server_name(self):
        conf = ("[Interface]\nPrivateKey = AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=\n"
                "Address = 10.0.0.2/32\n[Peer]\n"
                "PublicKey = BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=\n"
                "Endpoint = 198.51.100.30:51820\nAllowedIPs = 0.0.0.0/0\n")
        groups = json.loads(json.dumps(profile_state.wg_groups))
        settings = dict(server._app_settings)
        try:
            with mock.patch.object(profile_state, "save_wireguard_groups"), \
                    mock.patch.object(server, "_save_settings", return_value=True):
                response = self.client.post("/api/wg/servers/add", json={"conf": conf, "name": "Мой Нидерланды"},
                                            base_url="http://127.0.0.1:45678")
            self.assertTrue(response.get_json()["ok"])
            manual = next(g for g in profile_state.wg_groups if g["id"] == "manual-wg")
            self.assertEqual(manual["servers"][-1]["remark"], "Мой Нидерланды")
        finally:
            profile_state.wg_groups[:] = groups
            server._app_settings.clear()
            server._app_settings.update(settings)

    def test_invalid_tunnel_setting_is_rejected_without_mutation(self):
        original = server._app_settings["preferred_ip"]

        response = self.client.post(
            "/api/tunnel-settings",
            json={"preferred_ip": "sideways"},
            base_url="http://127.0.0.1:45678",
        )

        self.assertFalse(response.get_json()["ok"])
        self.assertEqual(server._app_settings["preferred_ip"], original)

    def test_rule_rename_preserves_the_existing_rule(self):
        original = profile_state.apps_config
        profile_state.apps_config = {
            "mode": "blacklist",
            "apps": [{
                "exe": "Bob's Browser.exe",
                "name": "Old name",
                "path": r"C:\Apps\browser.exe",
                "enabled": False,
            }],
        }
        try:
            with mock.patch.object(server, "save_apps"), mock.patch.object(server, "_broadcast"):
                response = self.client.post(
                    "/api/apps/rename",
                    json={"exe": "Bob's Browser.exe", "name": "Bob's private browser"},
                    base_url="http://127.0.0.1:45678",
                )

            self.assertTrue(response.get_json()["ok"])
            self.assertEqual(profile_state.apps_config["apps"], [{
                "exe": "Bob's Browser.exe",
                "name": "Bob's private browser",
                "path": r"C:\Apps\browser.exe",
                "enabled": False,
            }])
        finally:
            profile_state.apps_config = original

    def test_invalid_rule_rename_does_not_remove_the_rule(self):
        original = profile_state.apps_config
        app = {"exe": "chat.exe", "name": "Chat", "path": "", "enabled": True}
        profile_state.apps_config = {"mode": "all", "apps": [dict(app)]}
        try:
            response = self.client.post(
                "/api/apps/rename",
                json={"exe": "chat.exe", "name": "   "},
                base_url="http://127.0.0.1:45678",
            )

            self.assertFalse(response.get_json()["ok"])
            self.assertEqual(profile_state.apps_config["apps"], [app])
        finally:
            profile_state.apps_config = original

    def test_server_ui_identity_does_not_depend_on_list_index(self):
        original = profile_state.groups
        first = {"remark": "First", "protocol": "vless", "ui_id": "server-a"}
        second = {"remark": "Second", "protocol": "trojan", "ui_id": "server-b"}
        profile_state.groups = [{"id": "g", "name": "Group", "servers": [first, second]}]
        try:
            before = server._groups_for_ui()[0]["servers"]
            profile_state.groups[0]["servers"].reverse()
            after = server._groups_for_ui()[0]["servers"]

            self.assertEqual([item["ui_id"] for item in before], ["server-a", "server-b"])
            self.assertEqual([item["ui_id"] for item in after], ["server-b", "server-a"])
        finally:
            profile_state.groups = original

    def test_public_ip_response_is_validated(self):
        response_body = json.dumps({"ip": "203.0.113.9"}).encode("utf-8")
        upstream = mock.MagicMock()
        upstream.__enter__.return_value.read.return_value = response_body
        with mock.patch.object(server.urllib.request, "urlopen", return_value=upstream):
            response = self.client.post(
                "/api/network/ip",
                json={},
                base_url="http://127.0.0.1:45678",
            )

        self.assertEqual(response.get_json(), {
            "ok": True,
            "ip": "203.0.113.9",
            "version": 4,
            "source": "ipify",
        })

    def test_public_ip_uses_fallback_source(self):
        invalid = mock.MagicMock()
        invalid.__enter__.return_value.read.return_value = b"not-json"
        fallback = mock.MagicMock()
        fallback.__enter__.return_value.read.return_value = (
            b"fl=123\nip=2001:db8::9\nts=123\n"
        )
        with mock.patch.object(
            server.urllib.request,
            "urlopen",
            side_effect=[invalid, fallback],
        ):
            response = self.client.post(
                "/api/network/ip",
                json={},
                base_url="http://127.0.0.1:45678",
            )

        self.assertEqual(response.get_json(), {
            "ok": True,
            "ip": "2001:db8::9",
            "version": 6,
            "source": "Cloudflare",
        })

    def test_public_ip_reports_failure_after_all_sources_fail(self):
        with mock.patch.object(
            server.urllib.request,
            "urlopen",
            side_effect=OSError("offline"),
        ) as urlopen:
            response = self.client.post(
                "/api/network/ip",
                json={},
                base_url="http://127.0.0.1:45678",
            )

        self.assertFalse(response.get_json()["ok"])
        self.assertEqual(urlopen.call_count, len(server._PUBLIC_IP_SOURCES))

    def test_process_picker_returns_running_executables(self):
        from ui.routes import apps as apps_routes
        with mock.patch.object(
            apps_routes,
            "get_running_processes",
            return_value=["ChatGPT.exe", "Telegram.exe"],
        ):
            response = self.client.get(
                "/api/apps/processes",
                base_url="http://127.0.0.1:45678",
            )

        self.assertEqual(
            response.get_json(),
            {"processes": ["ChatGPT.exe", "Telegram.exe"]},
        )

    def test_local_country_flag_is_served(self):
        response = self.client.get(
            "/static/flags/4x3/de.svg",
            base_url="http://127.0.0.1:45678",
        )
        try:
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"<svg", response.data)
        finally:
            response.close()

    def test_invalid_favorite_setting_is_rejected(self):
        original = list(server._app_settings.get("favorite_servers", []))
        try:
            response = self.client.post(
                "/api/app-settings",
                json={"key": "favorite_servers", "value": "not-a-list"},
                base_url="http://127.0.0.1:45678",
            )
            self.assertFalse(response.get_json()["ok"])
            self.assertEqual(server._app_settings.get("favorite_servers", []), original)
        finally:
            server._app_settings["favorite_servers"] = original

    def test_lan_proxy_cannot_be_enabled_without_authentication(self):
        keys = ("lan", "socks5_auth", "socks5_user", "socks5_pass")
        original = {key: server._app_settings.get(key) for key in keys}
        server._app_settings.update({
            "lan": False,
            "socks5_auth": False,
            "socks5_user": "",
            "socks5_pass": "",
        })
        try:
            response = self.client.post(
                "/api/app-settings",
                json={"key": "lan", "value": True},
                base_url="http://127.0.0.1:45678",
            )

            self.assertFalse(response.get_json()["ok"])
            self.assertFalse(server._app_settings["lan"])
        finally:
            server._app_settings.update(original)

    def test_rule_export_writes_a_separate_json_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.object(server.Path, "home", return_value=Path(temporary)):
                response = self.client.post(
                    "/api/apps/export",
                    json={},
                    base_url="http://127.0.0.1:45678",
                )

            payload = response.get_json()
            self.assertTrue(payload["ok"])
            exported = Path(payload["path"])
            self.assertEqual(exported.parent, Path(temporary) / "Downloads")
            self.assertEqual(json.loads(exported.read_text(encoding="utf-8")), profile_state.apps_config)


if __name__ == "__main__":
    unittest.main()
