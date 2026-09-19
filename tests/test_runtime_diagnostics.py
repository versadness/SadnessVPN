import json
import unittest
from unittest.mock import Mock, patch

from engine.core_logs import core_log_tag
from engine.ping import tunnel_ping
from engine import autostart


class CoreSeverityTests(unittest.TestCase):
    def test_process_lookup_info_is_not_an_error(self):
        self.assertEqual(core_log_tag("+0300 2026-09-06 12:09:10 INFO [2200839720 14ms] router: failed to search process: process not found"), "log")

    def test_actual_errors_are_kept(self):
        for line in ("+0300 2026-09-06 12:09:10 ERROR connection: timeout",
                     "2026/09/06 12:09:06.976469 [Error] transport: failed",
                     'time="2026-09-06T12:09:10+03:00" level=error msg="dial timeout"',
                     "fatal: test failure", "panic: invalid memory", "fatal error: unexpected signal"):
            with self.subTest(line=line):
                self.assertEqual(core_log_tag(line), "err")

    def test_warn_and_ansi_levels(self):
        self.assertEqual(core_log_tag("2026/09/06 12:09:06.976469 [Warning] core: Xray started"), "warn")
        self.assertEqual(core_log_tag('\x1b[31mERROR\x1b[0m failed'), "err")
        self.assertEqual(core_log_tag('time="now" level=warning msg="failed"'), "warn")

    def test_message_words_never_override_explicit_info(self):
        self.assertEqual(core_log_tag("INFO dns: error.example failed"), "log")
        self.assertEqual(core_log_tag('time="now" level=info msg="failed to detect process"'), "log")


class TunnelPingTests(unittest.TestCase):
    def run_ping(self, status=200, body=b'{"delay": 72}'):
        connection = Mock()
        response = connection.getresponse.return_value
        response.status = status
        response.read.return_value = body
        with patch("engine.ping.http.client.HTTPConnection", return_value=connection) as constructor:
            result = tunnel_ping(test_url="https://example.com/check?a=1&b=2", timeout=2)
        constructor.assert_called_once_with("127.0.0.1", 9090, timeout=3)
        connection.close.assert_called_once()
        return result, connection

    def test_uses_outbound_delay_and_encodes_url(self):
        result, connection = self.run_ping()
        self.assertEqual(result, 72)
        from urllib.parse import urlsplit, parse_qs
        method, target = connection.request.call_args.args
        self.assertEqual(method, "GET")
        self.assertEqual(urlsplit(target).path, "/proxies/proxy/delay")
        self.assertEqual(parse_qs(urlsplit(target).query), {"url": ["https://example.com/check?a=1&b=2"], "timeout": ["2000"]})

    def test_failed_probe_never_falls_back_to_tcp(self):
        with patch("engine.ping.socket.create_connection") as tcp:
            for status, body in ((504, b'{}'), (200, b'{"delay":-1}'), (200, b'{"delay":true}'),
                                 (200, b'{}'), (200, b'bad json'), (200, b'[]')):
                self.assertIsNone(self.run_ping(status, body)[0])
            tcp.assert_not_called()

    def test_timeout_closes_connection(self):
        connection = Mock()
        connection.request.side_effect = TimeoutError()
        with patch("engine.ping.http.client.HTTPConnection", return_value=connection):
            self.assertIsNone(tunnel_ping())
        connection.close.assert_called_once()

    def test_native_awg_uses_http_response(self):
        with patch("engine.ping.http_ping", return_value=96) as http, patch("engine.ping.http.client.HTTPConnection") as api:
            self.assertEqual(tunnel_ping(native_awg=True), 96)
        http.assert_called_once()
        api.assert_not_called()


@unittest.skipUnless(autostart.sys.platform == "win32", "Windows COM")
class AutostartStatusTests(unittest.TestCase):
    def query(self, error=None, enabled=True):
        import pythoncom
        scheduler = Mock()
        task = scheduler.GetFolder.return_value.GetTask
        if error:
            task.side_effect = error
        else:
            task.return_value.Enabled = enabled
        with patch("win32com.client.Dispatch", return_value=scheduler), patch.object(pythoncom, "CoInitialize"), patch.object(pythoncom, "CoUninitialize") as uninitialize:
            try:
                return autostart.enabled()
            finally:
                uninitialize.assert_called_once()

    def test_missing_task_direct_and_wrapped(self):
        import pythoncom
        self.assertFalse(self.query(pythoncom.com_error(-2147024894, "missing", None, None)))
        self.assertFalse(self.query(pythoncom.com_error(-2147352567, "exception", (0, None, None, None, 0, -2147024894), None)))

    def test_access_denied_is_not_misreported_as_disabled(self):
        import pythoncom
        for error in (pythoncom.com_error(-2147024891, "denied", None, None),
                      pythoncom.com_error(-2147352567, "exception", (0, None, None, None, 0, -2147024891), None)):
            with self.assertRaises(pythoncom.com_error):
                self.query(error)

    def test_existing_task_state(self):
        self.assertTrue(self.query(enabled=True))
        self.assertFalse(self.query(enabled=False))


if __name__ == "__main__":
    unittest.main()
