"""Ручное добавление проверяется сразу, а не ошибкой при подключении."""
import unittest
from unittest import mock

from ui import profile_state, server

BASE = "http://127.0.0.1:45678"
UUID = "00000000-0000-0000-0000-000000000001"


class ManualServerTests(unittest.TestCase):
    def setUp(self):
        self.client = server.app.test_client()
        self.groups = []
        for patcher in (
            mock.patch.object(profile_state, "groups", self.groups),
            mock.patch.object(profile_state, "save_proxy_groups"),
            mock.patch.object(server, "_save_settings", return_value=True),
            mock.patch.object(server, "_broadcast_groups"),
            mock.patch.object(server, "_log"),
            mock.patch.dict(server._app_settings, {}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def add(self, link):
        return self.client.post("/api/servers/add", json={"link": link}, base_url=BASE).get_json()

    def test_unsupported_transport_is_refused_before_saving(self):
        result = self.add(f"vless://{UUID}@203.0.113.5:443?type=kcp#KCP")
        self.assertFalse(result["ok"])
        self.assertIn("kcp", result["error"])
        self.assertEqual(self.groups, [])

    def test_supported_server_is_added(self):
        result = self.add(f"vless://{UUID}@203.0.113.5:443?security=tls#OK")
        self.assertTrue(result["ok"])
        self.assertEqual(len(self.groups[0]["servers"]), 1)


class DeleteServerRepairTests(unittest.TestCase):
    def test_deleting_a_server_repairs_routes_immediately(self):
        client = server.app.test_client()
        groups = [{"id": "manual", "name": "Вручную", "servers": [{"remark": "A", "ui_id": "a"}]}]
        with mock.patch.object(profile_state, "groups", groups), \
                mock.patch.object(profile_state, "save_proxy_groups"), \
                mock.patch.object(server, "_save_settings", return_value=True), \
                mock.patch.object(server, "_broadcast_groups"), \
                mock.patch.object(server, "_log"), \
                mock.patch.dict(server._app_settings, {}), \
                mock.patch.object(server, "_repair_saved_routes") as repair:
            result = client.post("/api/servers/delete", json={"group_id": "manual", "index": 0},
                                 base_url=BASE).get_json()
        self.assertTrue(result["ok"])
        repair.assert_called_once()


class ManualAppTests(unittest.TestCase):
    def setUp(self):
        self.client = server.app.test_client()
        self.config = {"mode": "all", "apps": []}
        for patcher in (
            mock.patch.object(profile_state, "apps_config", self.config),
            mock.patch("ui.routes.apps.save_apps"),
            mock.patch.object(server, "_broadcast"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def add(self, exe):
        return self.client.post("/api/apps/add", json={"exe": exe, "name": "Test"},
                                base_url=BASE).get_json()

    def test_names_that_break_core_rules_are_refused(self):
        for exe in ("a,b.exe", "game (x64).exe", "mihomo.exe", "svchost.exe", "C:\\x\\app.exe"):
            with self.subTest(exe=exe):
                self.assertFalse(self.add(exe)["ok"])
        self.assertEqual(self.config["apps"], [])

    def test_regular_executable_is_added(self):
        self.assertTrue(self.add("Telegram.exe")["ok"])
        self.assertEqual(self.config["apps"][0]["exe"], "Telegram.exe")


if __name__ == "__main__":
    unittest.main()
