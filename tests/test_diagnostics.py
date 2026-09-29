import unittest
from unittest import mock
from engine.diagnostics import redact
from ui import server
from ui.routes import system as system_routes


class DiagnosticsTests(unittest.TestCase):
    def test_export_removes_config_secrets_and_subscription_urls(self):
        result = redact("PrivateKey = SECRET\nPresharedKey=OTHER\nhttps://example.test/sub/TOKEN")
        self.assertNotIn("SECRET", result)
        self.assertNotIn("OTHER", result)
        self.assertNotIn("TOKEN", result)

    def test_backend_has_no_window_commands(self):
        # Окном владеет Electron; прежние команды окна pywebview удалены.
        response = server.app.test_client().post("/api/window/minimize", base_url="http://127.0.0.1:45678")
        self.assertEqual(response.status_code, 404)

    def test_system_export_reads_backend_history(self):
        # Системный журнал (запуск, сбои) остаётся доступным отдельно от журнала сессии.
        with mock.patch.object(system_routes, "export_journal", return_value="startup error before UI"):
            response = server.app.test_client().get("/api/diagnostics/system", base_url="http://127.0.0.1:45678")
        self.assertEqual(response.get_json()["text"], "startup error before UI")
