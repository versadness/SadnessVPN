import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine.singbox import SingBoxManager
from engine.zapret import ZapretManager


class ProcessSourceSafetyTests(unittest.TestCase):
    def test_managers_never_use_global_taskkill(self):
        engine_dir = Path(__file__).resolve().parents[1].joinpath("engine")

        for name in ("singbox.py", "xray.py", "zapret.py"):
            with self.subTest(name=name):
                source = engine_dir.joinpath(name).read_text(encoding="utf-8")
                self.assertNotIn("taskkill", source.lower())

    def test_singbox_never_deletes_network_adapters(self):
        path = Path(__file__).resolve().parents[1].joinpath("engine", "singbox.py")
        source = path.read_text(encoding="utf-8").lower()

        self.assertNotIn("remove-netadapter", source)
        self.assertNotIn('"interface", "delete"', source)


class SingBoxConflictSafetyTests(unittest.TestCase):
    def test_start_refuses_occupied_clash_port_without_spawning(self):
        messages = []
        manager = SingBoxManager(
            log_callback=lambda message, tag: messages.append((message, tag))
        )

        with tempfile.TemporaryDirectory() as root:
            executable = Path(root, "sing-box.exe")
            executable.touch()

            with (
                mock.patch.object(manager, "_singbox_path", return_value=str(executable)),
                mock.patch.object(manager, "_port_free", return_value=False),
                mock.patch("engine.singbox.platform.system", return_value="Windows"),
                mock.patch("engine.singbox.subprocess.Popen") as popen,
            ):
                result = manager.start({})

        self.assertFalse(result)
        popen.assert_not_called()
        self.assertTrue(any("9090" in message for message, _tag in messages))

    def test_stop_terminates_only_managed_process(self):
        manager = SingBoxManager()
        process = mock.Mock()
        process.poll.return_value = None
        manager.process = process
        manager.running = True

        with mock.patch.object(manager, "_wait_port_free", return_value=True):
            manager.stop()

        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=5)
        process.kill.assert_not_called()
        self.assertIsNone(manager.process)
        self.assertFalse(manager.running)


class ZapretConflictSafetyTests(unittest.TestCase):
    def test_start_refuses_foreign_winws_without_spawning(self):
        messages = []
        manager = ZapretManager(
            log_callback=lambda message, tag: messages.append((message, tag))
        )

        with (
            mock.patch.object(manager, "_foreign_winws_running", return_value=True),
            mock.patch("engine.zapret.subprocess.Popen") as popen,
        ):
            result = manager.start()

        self.assertFalse(result)
        popen.assert_not_called()
        self.assertTrue(any("winws.exe" in message for message, _tag in messages))


if __name__ == "__main__":
    unittest.main()
