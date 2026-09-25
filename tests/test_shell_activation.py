"""Повторный запуск активирует уже открытое окно вместо второго экземпляра."""
import time
import unittest
from unittest import mock

import backend_main
from ui import server

BASE = "http://127.0.0.1:45678"


class ShellReadyTests(unittest.TestCase):
    """Updater считает новую версию запущенной только по ui_ready."""

    def setUp(self):
        from ui import window_control
        self.window_control = window_control
        self.client = server.app.test_client()
        window_control.shell_ready.clear()
        self.addCleanup(window_control.shell_ready.clear)

    def test_update_state_reports_electron_window_readiness(self):
        state = self.client.get("/api/updates/state", base_url=BASE).get_json()
        self.assertFalse(state["ui_ready"])

        response = self.client.post("/api/shell/ready", base_url=BASE)
        self.assertEqual(response.get_json(), {"ok": True})
        state = self.client.get("/api/updates/state", base_url=BASE).get_json()
        self.assertTrue(state["ui_ready"])

    def test_updater_recovery_asks_the_shell_to_quit(self):
        # Раньше close-for-recovery в Electron-сборке ничего не закрывал, и
        # updater через 30 с сообщал «не удалось завершить новую версию».
        self.addCleanup(self.window_control.quit_request.clear)
        self.addCleanup(self.window_control.show_request.clear)
        with mock.patch.object(server._connection, "_state", "off"):
            response = self.client.post("/api/updates/close-for-recovery", base_url=BASE).get_json()
        self.assertTrue(response["ok"])
        with mock.patch.object(backend_main, "_SHELL_WAIT_SECONDS", 0.05):
            self.assertEqual(self.client.get("/api/shell/show-wait", base_url=BASE).get_json(),
                             {"show": False, "quit": True})
            # Команда выхода выдаётся один раз.
            self.assertEqual(self.client.get("/api/shell/show-wait", base_url=BASE).get_json(),
                             {"show": False})

    def test_startup_preferences_expose_only_silent_flag(self):
        with mock.patch.dict(server._app_settings, {"silent": True}):
            payload = self.client.get("/api/shell/startup", base_url=BASE).get_json()
        self.assertEqual(payload, {"ok": True, "silent": True})


class ShellActivationTests(unittest.TestCase):
    def setUp(self):
        self.client = server.app.test_client()
        backend_main._show_request.clear()
        self.addCleanup(backend_main._show_request.clear)

    def attach(self, seconds_ago=0.0):
        backend_main._shell_seen_at = time.monotonic() - seconds_ago

    def test_without_a_shell_the_launcher_is_told_to_start_one(self):
        # Окно могло упасть, а бэкенд остаться: тогда показывать нечего и
        # лаунчер обязан выполнить обычный запуск.
        self.attach(backend_main._SHELL_ATTACHED_SECONDS + 5)
        response = self.client.post("/api/shell/show", base_url=BASE)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ok": True, "attached": False})
        self.assertFalse(backend_main._show_request.is_set())

    def test_attached_shell_receives_the_request_exactly_once(self):
        self.attach()
        response = self.client.post("/api/shell/show", base_url=BASE)
        self.assertEqual(response.get_json(), {"ok": True, "attached": True})

        with mock.patch.object(backend_main, "_SHELL_WAIT_SECONDS", 0.05):
            self.assertEqual(self.client.get("/api/shell/show-wait", base_url=BASE).get_json(),
                             {"show": True})
            # Второй запрос не должен поднимать окно повторно.
            self.assertEqual(self.client.get("/api/shell/show-wait", base_url=BASE).get_json(),
                             {"show": False})

    def test_long_poll_itself_marks_the_shell_as_present(self):
        self.attach(backend_main._SHELL_ATTACHED_SECONDS + 5)
        with mock.patch.object(backend_main, "_SHELL_WAIT_SECONDS", 0.05):
            self.client.get("/api/shell/show-wait", base_url=BASE)
        self.assertEqual(self.client.post("/api/shell/show", base_url=BASE).get_json(),
                         {"ok": True, "attached": True})

    def test_request_is_rejected_from_outside_loopback(self):
        response = self.client.post("/api/shell/show", base_url="http://192.168.0.5:45678")
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
