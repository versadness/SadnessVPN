"""Автозапуск Windows запускает лаунчер, а не отдельный бэкенд без окна."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine import autostart


class AutostartCommandTests(unittest.TestCase):
    def installed_layout(self, directory):
        root = Path(directory)
        (root / "runtime").mkdir()
        backend = root / "runtime" / "SadnessVPN.exe"
        launcher = root / "SadnessVPN.exe"
        backend.write_bytes(b"MZ")
        launcher.write_bytes(b"MZ")
        return backend, launcher

    def test_installed_task_starts_launcher_with_autostart_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            backend, launcher = self.installed_layout(directory)
            with mock.patch.object(autostart.sys, "frozen", True, create=True), \
                    mock.patch.object(autostart.sys, "executable", str(backend)):
                executable, arguments = autostart._command()
                command = autostart._task_command()
        self.assertEqual(os.path.normcase(executable), os.path.normcase(str(launcher.resolve())))
        self.assertEqual(arguments, ["--autostart"])
        self.assertTrue(command.endswith(" --autostart"))
        self.assertNotIn("runtime", command)

    def test_missing_launcher_is_an_explicit_error(self):
        with tempfile.TemporaryDirectory() as directory:
            backend, launcher = self.installed_layout(directory)
            launcher.unlink()
            with mock.patch.object(autostart.sys, "frozen", True, create=True), \
                    mock.patch.object(autostart.sys, "executable", str(backend)):
                with self.assertRaises(RuntimeError):
                    autostart._command()

    def test_legacy_task_pointing_at_backend_is_recreated(self):
        with mock.patch.object(autostart, "_command", return_value=(r"C:\App\SadnessVPN.exe", ["--autostart"])), \
                mock.patch.object(autostart, "_read_task",
                                  return_value=(True, r"C:\App\runtime\SadnessVPN.exe", "")), \
                mock.patch.object(autostart, "enable") as enable:
            self.assertTrue(autostart.ensure_current())
        enable.assert_called_once()

    def test_current_or_disabled_task_is_left_alone(self):
        with mock.patch.object(autostart, "_command", return_value=(r"C:\App\SadnessVPN.exe", ["--autostart"])), \
                mock.patch.object(autostart, "enable") as enable:
            with mock.patch.object(autostart, "_read_task",
                                   return_value=(True, '"C:\\App\\SadnessVPN.exe"', "--autostart")):
                self.assertFalse(autostart.ensure_current())
            with mock.patch.object(autostart, "_read_task", return_value=(False, "x", "")):
                self.assertFalse(autostart.ensure_current())
            with mock.patch.object(autostart, "_read_task", return_value=None):
                self.assertFalse(autostart.ensure_current())
        enable.assert_not_called()


if __name__ == "__main__":
    unittest.main()
