"""Пинг серверов: ICMP не зависит от языка Windows, HTTP меряется через сам сервер."""
import subprocess
import unittest
from unittest import mock

from engine import ping


def completed(stdout: bytes, code=0):
    return subprocess.CompletedProcess(args=[], returncode=code, stdout=stdout, stderr=b"")


class IcmpPingTests(unittest.TestCase):
    def run_icmp(self, text, encoding, code=0):
        with mock.patch.object(ping.platform, "system", return_value="Windows"), \
                mock.patch.object(ping, "_decode_console", side_effect=lambda raw: raw.decode(encoding)), \
                mock.patch.object(ping.subprocess, "run", return_value=completed(text.encode(encoding), code)):
            return ping.icmp_ping("198.51.100.1", 1)

    def test_russian_windows_reply_in_oem_codepage(self):
        reply = "Ответ от 198.51.100.1: число байт=32 время=37мс TTL=54\r\n"
        self.assertEqual(self.run_icmp(reply, "cp866"), 37)

    def test_sub_millisecond_reply(self):
        reply = "Ответ от 127.0.0.1: число байт=32 время<1мс TTL=128\r\n"
        self.assertEqual(self.run_icmp(reply, "cp866"), 1)

    def test_english_windows_reply(self):
        reply = "Reply from 198.51.100.1: bytes=32 time=12ms TTL=54\r\n"
        self.assertEqual(self.run_icmp(reply, "ascii"), 12)

    def test_unreachable_with_zero_exit_code_is_not_a_reply(self):
        reply = "Ответ от 192.168.1.1: Заданный узел недоступен.\r\n"
        self.assertIsNone(self.run_icmp(reply, "cp866"))


class HttpPingTests(unittest.TestCase):
    def test_http_mode_measures_through_each_server(self):
        groups = [{"id": "g", "servers": [{"host": "a"}, {"host": "b"}]}]
        results = []

        def fake_delays(servers, url, timeout, stop_event, on_result):
            self.assertEqual(url, "https://example.test/204")
            on_result(0, 80)
            on_result(1, None)

        with mock.patch("engine.url_test.delays", side_effect=fake_delays), \
                mock.patch.object(ping, "http_ping") as direct:
            ping.ping_groups(groups, lambda *row: results.append(row), ping_type="http_get",
                             test_url="https://example.test/204")
        direct.assert_not_called()
        self.assertEqual(results, [("g", 0, 80, "green"), ("g", 1, None, "err")])


if __name__ == "__main__":
    unittest.main()
