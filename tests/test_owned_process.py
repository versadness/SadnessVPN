"""Процессы, пережившие сбой бэкенда, останавливаются, а чужие — никогда."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from engine import owned_process
from engine.amneziawg import AmneziaWGManager


class OwnedProcessTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        patcher = mock.patch.object(owned_process, "_record_path",
                                    side_effect=lambda name: os.path.join(self.folder.name, name + ".json"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def spawn(self):
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])

        def cleanup():
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)

        self.addCleanup(cleanup)
        return process

    def test_orphan_started_by_the_app_is_stopped(self):
        process = self.spawn()
        owned_process.remember("core", process.pid)
        self.assertTrue(owned_process.reap("core", sys.executable))
        self.assertIsNotNone(process.wait(timeout=10))
        self.assertFalse(os.path.exists(owned_process._record_path("core")))

    def test_process_with_other_executable_is_never_touched(self):
        process = self.spawn()
        owned_process.remember("core", process.pid)
        self.assertFalse(owned_process.reap("core", os.path.join(self.folder.name, "mihomo.exe")))
        self.assertIsNone(process.poll())

    def test_reused_pid_is_not_mistaken_for_ours(self):
        process = self.spawn()
        owned_process.remember("core", process.pid)
        path = owned_process._record_path("core")
        # Тот же PID, но другое время создания: номер процесса переиспользован.
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        data["created"] -= 3600
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        self.assertFalse(owned_process.reap("core", sys.executable))
        self.assertIsNone(process.poll())

    def test_forgotten_process_is_not_reaped(self):
        process = self.spawn()
        owned_process.remember("core", process.pid)
        owned_process.forget("core")
        self.assertFalse(owned_process.reap("core", sys.executable))
        self.assertIsNone(process.poll())


class LeftoverAwgServiceTests(unittest.TestCase):
    def test_disconnect_removes_service_left_by_a_crashed_session(self):
        manager = AmneziaWGManager()
        self.assertFalse(manager.running)
        with mock.patch.object(manager, "_service_state", return_value=4), \
                mock.patch.object(manager, "_uninstall_owned_service", return_value=True) as uninstall:
            self.assertTrue(manager.stop())
        uninstall.assert_called_once()

    def test_disconnect_without_service_does_nothing(self):
        manager = AmneziaWGManager()
        with mock.patch.object(manager, "_service_state", return_value=0), \
                mock.patch.object(manager, "_uninstall_owned_service") as uninstall:
            self.assertTrue(manager.stop())
        uninstall.assert_not_called()


if __name__ == "__main__":
    unittest.main()
