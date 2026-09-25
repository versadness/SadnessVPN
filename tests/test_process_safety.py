import threading
import tempfile
import unittest
import ipaddress
from pathlib import Path
from unittest import mock

from engine.mihomo import MihomoManager
from engine.zapret import ZapretManager


class ProcessSourceSafetyTests(unittest.TestCase):
    def test_managers_never_use_global_taskkill(self):
        engine_dir = Path(__file__).resolve().parents[1].joinpath("engine")

        for name in ("mihomo.py", "zapret.py", "amneziawg.py"):
            with self.subTest(name=name):
                source = engine_dir.joinpath(name).read_text(encoding="utf-8")
                self.assertNotIn("taskkill", source.lower())

    def test_core_never_deletes_network_adapters(self):
        path = Path(__file__).resolve().parents[1].joinpath("engine", "mihomo.py")
        source = path.read_text(encoding="utf-8").lower()

        self.assertNotIn("remove-netadapter", source)
        self.assertNotIn('"interface", "delete"', source)


class MihomoConflictSafetyTests(unittest.TestCase):
    def test_start_refuses_occupied_clash_port_without_spawning(self):
        messages = []
        manager = MihomoManager(
            log_callback=lambda message, tag: messages.append((message, tag))
        )

        with tempfile.TemporaryDirectory() as root:
            executable = Path(root, "mihomo.exe")
            executable.touch()

            with (
                mock.patch.object(manager, "_core_path", return_value=str(executable)),
                mock.patch.object(manager, "_port_free", return_value=False),
                mock.patch.object(manager, "_check_config", return_value=True),
                mock.patch("engine.mihomo.subprocess.Popen") as popen,
            ):
                result = manager.start({"external-controller": "127.0.0.1:9090"})

        self.assertFalse(result)
        popen.assert_not_called()
        self.assertTrue(any("9090" in message for message, _tag in messages))

    def test_start_refuses_occupied_auxiliary_port_before_tun_is_created(self):
        messages = []
        manager = MihomoManager(
            log_callback=lambda message, tag: messages.append((message, tag))
        )
        config = {
            "external-controller": "127.0.0.1:9090",
            "socks-port": 1080,
            "port": 8080,
            "tun": {"enable": True},
            "dns": {"enhanced-mode": "redir-host", "fake-ip-range": "172.19.0.1/30"},
        }
        with tempfile.TemporaryDirectory() as root:
            executable = Path(root, "mihomo.exe")
            executable.touch()
            Path(root, "wintun.dll").touch()
            with (
                mock.patch.object(manager, "_core_path", return_value=str(executable)),
                mock.patch("engine.mihomo.bin_path", side_effect=lambda name: str(Path(root, name))),
                mock.patch.object(manager, "_port_free", side_effect=lambda port: port != 1080),
                mock.patch.object(manager, "_port_owner", return_value="TgSocksLocal.exe"),
                mock.patch.object(manager, "_assigned_ipv4_networks", return_value=[]),
                mock.patch.object(manager, "_check_config", return_value=True),
                mock.patch("engine.mihomo.subprocess.Popen") as popen,
            ):
                result = manager.start(config)

        self.assertFalse(result)
        popen.assert_not_called()
        message = " ".join(text for text, _tag in messages)
        self.assertIn("1080", message)
        self.assertIn("TgSocksLocal.exe", message)
        self.assertIn("TUN не создавался", message)

    def test_listener_ports_are_derived_from_config(self):
        self.assertEqual(
            MihomoManager._listener_ports({
                "external-controller": "127.0.0.1:9191",
                "socks-port": 1081,
                "port": "8080",
            }),
            [("Clash API", 9191), ("socks-port", 1081)],
        )

    def test_occupied_tun_subnet_is_replaced_without_deleting_adapter(self):
        messages = []
        manager = MihomoManager(
            log_callback=lambda message, tag: messages.append((message, tag))
        )
        config = {
            "tun": {"enable": True},
            "dns": {"enhanced-mode": "redir-host", "fake-ip-range": "172.19.0.1/30"},
        }

        with mock.patch.object(
            manager,
            "_assigned_ipv4_networks",
            return_value=[ipaddress.ip_network("172.19.0.0/30")],
        ):
            self.assertTrue(manager._prepare_tun_addresses(config))

        replacement = config["dns"]["fake-ip-range"]
        self.assertNotEqual(replacement, "172.19.0.1/30")
        self.assertEqual(replacement, "172.19.1.1/30")
        self.assertTrue(any("Подсеть TUN" in message for message, _tag in messages))

    def test_stop_terminates_only_managed_process(self):
        manager = MihomoManager()
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


class MihomoExitNotificationTests(unittest.TestCase):
    def test_unexpected_current_process_exit_notifies_and_cleans_up(self):
        exit_codes = []
        manager = MihomoManager(exit_callback=exit_codes.append)
        process = mock.Mock()
        process.stdout = ["fatal: test failure\n"]
        process.poll.return_value = 17
        stop_requested = threading.Event()
        manager.process = process
        manager.running = True

        with tempfile.NamedTemporaryFile(delete=False) as config_file:
            manager._config_file = config_file.name
            config_path = Path(config_file.name)

        manager._read_output(process, stop_requested)

        self.assertEqual(exit_codes, [17])
        self.assertFalse(manager.running)
        self.assertIsNone(manager.process)
        self.assertIsNone(manager._config_file)
        self.assertFalse(config_path.exists())

    def test_expected_process_exit_does_not_notify(self):
        exit_codes = []
        manager = MihomoManager(exit_callback=exit_codes.append)
        process = mock.Mock()
        process.stdout = []
        process.poll.return_value = 0
        stop_requested = threading.Event()
        stop_requested.set()
        manager.process = process
        manager.running = True

        manager._read_output(process, stop_requested)

        self.assertEqual(exit_codes, [])
        self.assertFalse(manager.running)
        self.assertIsNone(manager.process)

    def test_old_reader_cannot_clear_or_report_new_process(self):
        exit_codes = []
        manager = MihomoManager(exit_callback=exit_codes.append)
        old_process = mock.Mock()
        old_process.stdout = []
        old_process.poll.return_value = 9
        new_process = mock.Mock()
        manager.process = new_process
        manager.running = True

        manager._read_output(old_process, threading.Event())

        self.assertEqual(exit_codes, [])
        self.assertIs(manager.process, new_process)
        self.assertTrue(manager.running)


class ZapretExitNotificationTests(unittest.TestCase):
    def test_unexpected_current_process_exit_notifies_and_cleans_up(self):
        exit_codes = []
        manager = ZapretManager(exit_callback=exit_codes.append)
        process = mock.Mock()
        process.stdout = ["fatal: test failure\n"]
        process.poll.return_value = 23
        stop_requested = threading.Event()
        manager.process = process
        manager.running = True

        manager._read_output(process, stop_requested)

        self.assertEqual(exit_codes, [23])
        self.assertFalse(manager.running)
        self.assertIsNone(manager.process)

    def test_expected_process_exit_does_not_notify(self):
        exit_codes = []
        manager = ZapretManager(exit_callback=exit_codes.append)
        process = mock.Mock()
        process.stdout = []
        process.poll.return_value = 0
        stop_requested = threading.Event()
        stop_requested.set()
        manager.process = process
        manager.running = True

        manager._read_output(process, stop_requested)

        self.assertEqual(exit_codes, [])
        self.assertFalse(manager.running)

    def test_old_reader_cannot_clear_or_report_new_process(self):
        exit_codes = []
        manager = ZapretManager(exit_callback=exit_codes.append)
        old_process = mock.Mock()
        old_process.stdout = []
        old_process.poll.return_value = 9
        new_process = mock.Mock()
        manager.process = new_process
        manager.running = True

        manager._read_output(old_process, threading.Event())

        self.assertEqual(exit_codes, [])
        self.assertIs(manager.process, new_process)
        self.assertTrue(manager.running)


if __name__ == "__main__":
    unittest.main()
