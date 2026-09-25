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
        self.assertEqual(order, ["timestamps"])
        self.assertTrue(any("исключены из перехвата" in message for message in messages))

    def test_profiles_actually_pass_the_exclusion_file_to_winws(self):
        from engine.flowseal_profiles import FLOWSEAL_PROFILES

        for profile in FLOWSEAL_PROFILES:
            with self.subTest(profile=profile["id"]):
                self.assertTrue(any(
                    arg.startswith("--ipset-exclude=") and arg.endswith("ipset-exclude-user.txt")
                    for arg in profile["args"]
                ), profile["id"])


if __name__ == "__main__":
    unittest.main()
