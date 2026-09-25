"""Совместная работа Mihomo TUN и winws: что именно защищено и от чего.

Главная опасность не в том, что компоненты «не подружатся», а в том, что
WinDivert увидит внешнее зашифрованное соединение с VPN-сервером — оно идёт по
тем же 80/443, что и обычный трафик, — и десинхронизация порвёт сам туннель.
"""
import unittest
from pathlib import Path
from unittest import mock
import tempfile

from engine import zapret_exclusions
from engine.zapret import ZapretManager


class ExclusionFileTests(unittest.TestCase):
    def test_managed_block_is_added_without_touching_user_lines(self):
        existing = "203.0.113.5\n# мой комментарий\n"
        result = zapret_exclusions.render(existing, ["198.51.100.7", "198.51.100.8"])

        self.assertIn("203.0.113.5", result)
        self.assertIn("# мой комментарий", result)
        self.assertIn("198.51.100.7", result)
        self.assertIn(zapret_exclusions.BEGIN, result)
        self.assertIn(zapret_exclusions.END, result)

    def test_rewriting_replaces_only_the_managed_block(self):
        first = zapret_exclusions.render("203.0.113.5\n", ["198.51.100.7"])
        second = zapret_exclusions.render(first, ["198.51.100.9"])

        self.assertIn("203.0.113.5", second)
        self.assertIn("198.51.100.9", second)
        self.assertNotIn("198.51.100.7", second)
        self.assertEqual(second.count(zapret_exclusions.BEGIN), 1)

    def test_empty_address_list_removes_the_block_and_keeps_user_lines(self):
        first = zapret_exclusions.render("203.0.113.5\n", ["198.51.100.7"])
        cleared = zapret_exclusions.render(first, [])

        self.assertEqual(cleared.strip(), "203.0.113.5")
        self.assertNotIn(zapret_exclusions.BEGIN, cleared)

    def test_literal_addresses_are_used_without_a_dns_lookup(self):
        with mock.patch("engine.zapret_exclusions.socket.getaddrinfo") as lookup:
            addresses = zapret_exclusions.collect([
                {"host": "198.51.100.7", "port": 443},
                {"host": "2001:db8::1", "port": 443},
            ])
        lookup.assert_not_called()
        self.assertEqual(addresses, ["198.51.100.7", "2001:db8::1"])

    def test_names_are_resolved_and_deduplicated(self):
        answer = [(0, 0, 0, "", ("198.51.100.7", 443)),
                  (0, 0, 0, "", ("198.51.100.7", 443)),
                  (0, 0, 0, "", ("198.51.100.8", 443))]
        with mock.patch("engine.zapret_exclusions.socket.getaddrinfo", return_value=answer):
            addresses = zapret_exclusions.collect([{"host": "vpn.example", "port": 443}])
        self.assertEqual(addresses, ["198.51.100.7", "198.51.100.8"])

    def test_a_failed_lookup_never_blocks_the_bypass(self):
        with mock.patch("engine.zapret_exclusions.socket.getaddrinfo", side_effect=OSError):
            self.assertEqual(zapret_exclusions.collect([{"host": "vpn.example"}]), [])

    def test_secrets_never_reach_the_exclusion_file(self):
        server = {"host": "198.51.100.7", "port": 443, "uuid": "SECRET-UUID",
                  "password": "SECRET-PASSWORD", "remark": "Мой сервер"}
        rendered = zapret_exclusions.render("", zapret_exclusions.collect([server]))
        for secret in ("SECRET-UUID", "SECRET-PASSWORD", "Мой сервер"):
            self.assertNotIn(secret, rendered)


class ManagerIntegrationTests(unittest.TestCase):
    def test_start_writes_the_exclusions_before_launching_winws(self):
        order = []
        messages = []
        manager = ZapretManager(log_callback=lambda message, tag: messages.append(message))

        with tempfile.TemporaryDirectory() as root:
            lists = Path(root, "lists")
            lists.mkdir()
            with mock.patch.object(manager, "_lists",
                                   side_effect=lambda name: str(lists / name)), \
                 mock.patch.object(manager, "_winws_path", return_value=str(Path(root, "winws.exe"))), \
                 mock.patch.object(manager, "_foreign_winws_running", return_value=False), \
                 mock.patch.object(zapret_exclusions, "collect", return_value=["198.51.100.7"]), \
                 mock.patch.object(manager, "_enable_tcp_timestamps",
                                   side_effect=lambda: order.append("timestamps")), \
                 mock.patch("engine.zapret.subprocess.Popen") as popen:
                started = manager.start("flowseal_general", {"scope": "standard"},
                                        [{"host": "198.51.100.7", "port": 443}])

            written = (lists / "ipset-exclude-user.txt").read_text(encoding="utf-8")

        # winws не запустился (файла нет) — но исключения уже на диске.
        self.assertFalse(started)
        popen.assert_not_called()
        self.assertIn("198.51.100.7", written)
        # Глобальная настройка Windows не меняется, если winws так и не запущен.
        self.assertEqual(order, [])
        self.assertTrue(any("исключены из перехвата" in message for message in messages))

    def test_profiles_actually_pass_the_exclusion_file_to_winws(self):
        from engine.flowseal_profiles import FLOWSEAL_PROFILES

        for profile in FLOWSEAL_PROFILES:
            with self.subTest(profile=profile["id"]):
                self.assertTrue(any(
                    arg.startswith("--ipset-exclude=") and arg.endswith("ipset-exclude-user.txt")
                    for arg in profile["args"]
                ), profile["id"])


class TcpTimestampsTests(unittest.TestCase):
    """Глобальная настройка Windows возвращается, если её менял обход."""

    def manager(self, state):
        manager = ZapretManager()
        calls = []

        def netsh(*arguments):
            calls.append(arguments)
            import subprocess
            output = f"RFC 1323 Timestamps                 : {state}\r\n".encode()
            return subprocess.CompletedProcess(arguments, 0, output, b"")

        manager._netsh = netsh
        return manager, calls

    def test_disabled_setting_is_enabled_and_then_restored(self):
        manager, calls = self.manager("disabled")
        with mock.patch("engine.zapret.platform.system", return_value="Windows"):
            manager._enable_tcp_timestamps()
            manager._restore_tcp_timestamps()
        self.assertIn(("set", "global", "timestamps=enabled"), calls)
        self.assertEqual(calls[-1], ("set", "global", "timestamps=disabled"))

    def test_already_enabled_setting_is_left_untouched(self):
        manager, calls = self.manager("enabled")
        with mock.patch("engine.zapret.platform.system", return_value="Windows"):
            manager._enable_tcp_timestamps()
            manager._restore_tcp_timestamps()
        self.assertEqual(calls, [("show", "global")])


class WinwsLogTagTests(unittest.TestCase):
    def test_error_words_in_output_do_not_raise_popups(self):
        import threading
        logged = []
        manager = ZapretManager(log_callback=lambda message, tag: logged.append((message, tag)))
        process = mock.Mock()
        process.stdout = ["windivert: could not resolve hostname\n", "filter loaded\n"]
        process.poll.return_value = 0
        manager.process = process
        stop = threading.Event()
        stop.set()
        manager._read_output(process, stop)
        tags = {message: tag for message, tag in logged}
        # «err» превращается во всплывающее уведомление: для строк вывода — только warn.
        self.assertEqual(tags["[zapret] windivert: could not resolve hostname"], "warn")
        self.assertEqual(tags["[zapret] filter loaded"], "log")
        self.assertNotIn("err", [tag for _message, tag in logged])


class WireGuardEndpointTests(unittest.TestCase):
    def test_wireguard_endpoint_is_excluded(self):
        # WG/AWG хранят адрес в endpoint, а не в host.
        servers = [{"endpoint": "198.51.100.40", "port": 51820, "private_key": "секрет"}]
        self.assertEqual(zapret_exclusions.collect(servers), ["198.51.100.40"])


class ProtectRunningBypassTests(unittest.TestCase):
    """VPN, выбранный после запуска Zapret, всё равно исключается из обработки."""

    def service(self, excluded):
        from ui.zapret_service import ZapretService
        broadcast = mock.Mock()
        service = ZapretService(log_callback=lambda *_: None, broadcast=broadcast)
        service.state, service.running = "on", True
        engine = service.engine
        engine.running = True
        engine._strategy = "flowseal_general"
        engine._game_filter_config = {"scope": "standard"}
        engine.excluded_addresses = list(excluded)
        engine.stop = mock.Mock()
        engine.start = mock.Mock(return_value=True)
        return service, broadcast

    def test_new_server_restarts_own_winws_with_same_profile(self):
        service, broadcast = self.service(excluded=["198.51.100.7"])
        servers = [{"host": "198.51.100.8"}]
        self.assertTrue(service.protect_vpn(servers))
        service.engine.stop.assert_called_once()
        service.engine.start.assert_called_once_with("flowseal_general", {"scope": "standard"}, servers)
        self.assertEqual(service.state, "on")
        broadcast.assert_called_once()

    def test_already_excluded_server_changes_nothing(self):
        service, broadcast = self.service(excluded=["198.51.100.8"])
        self.assertFalse(service.protect_vpn([{"host": "198.51.100.8"}]))
        service.engine.stop.assert_not_called()
        broadcast.assert_not_called()

    def test_stopped_bypass_is_left_alone(self):
        service, _broadcast = self.service(excluded=[])
        service.state = "off"
        self.assertFalse(service.protect_vpn([{"host": "198.51.100.8"}]))
        service.engine.start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
