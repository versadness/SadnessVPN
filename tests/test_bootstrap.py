import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import bootstrap
from engine import startup_diagnostics as diag


class BootstrapTests(unittest.TestCase):
    def test_diagnostics_precede_main_import(self):
        # С 2.0.26 точка входа поднимает бэкенд движков, а не окно на WebView2.
        # Имя модуля здесь обязано совпадать с тем, что импортирует bootstrap:
        # иначе подмена не сработает и тест поднимет настоящий Flask-сервер,
        # который не даст процессу завершиться.
        import builtins
        original = builtins.__import__
        order = []
        def fail_import(name, *args, **kwargs):
            if name == "backend_main":
                order.append("import")
                raise ImportError("missing test dependency")
            return original(name, *args, **kwargs)
        with patch.object(bootstrap, "initialize", side_effect=lambda: order.append("logs")), patch.object(bootstrap, "report_failure") as report, patch("builtins.__import__", side_effect=fail_import):
            self.assertEqual(bootstrap.run(), 1)
        self.assertEqual(order, ["logs", "import"])
        self.assertIsInstance(report.call_args.args[0], ImportError)

    def test_error_dialog_has_cause_and_actual_path(self):
        stream = io.StringIO()
        with patch.object(diag, "initialize", return_value=r"C:\logs\startup-python.log"), patch.object(diag, "_stream", stream), patch.object(diag.ctypes.windll.user32, "MessageBoxW", return_value=7) as box:
            diag.report_failure(RuntimeError("renderer failed"))
        self.assertIn("RuntimeError: renderer failed", stream.getvalue())
        self.assertIn(r"C:\logs\startup-python.log", box.call_args.args[1])
        self.assertIn("renderer failed", box.call_args.args[1])

    def test_foreign_event_names_are_not_opened(self):
        with patch.object(diag.sys, "argv", ["app", "--startup-event=Global\\OtherApp"]), patch.object(diag.ctypes, "WinDLL") as dll:
            diag.notify_ready()
        dll.assert_not_called()

    def test_packaging_preserves_security_and_user_data(self):
        root = Path(__file__).resolve().parents[1]
        spec = (root / "SadnessVPN.spec").read_text(encoding="utf8")
        self.assertIn("['bootstrap.py']", spec)
        self.assertNotIn("upx=True", spec)
        installer = (root / "installer/build_msi.py").read_text(encoding="utf8")
        self.assertIn('"MsiLogging"', installer)
        self.assertIn('"LaunchCondition"', installer)
        self.assertNotIn("Add-MpPreference", installer)
        self.assertNotIn("Set-MpPreference", installer)
        self.assertNotIn('"CustomAction"', installer)


if __name__ == "__main__":
    unittest.main()
