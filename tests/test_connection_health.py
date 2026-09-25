"""Регрессия «разрыва через 30–50 секунд».

Строки взяты из журнала пользователя за 20.09 и 22.09 (адреса заменены):
ядро живо, первые соединения проходят, затем каждое новое соединение с
сервером обрывается с «connect error: context canceled». Раньше приложение
продолжало показывать «подключено» без единого предупреждения.
"""
import unittest

from engine.connection_health import DialHealth, MIN_FAILURES, WINDOW_SECONDS, blocked_message

OK = ('time="2026-09-20T19:22:20+03:00" level=info msg="[TCP] 172.19.0.1:61068(steam.exe) '
      '--> client-update.akamai.steamstatic.com:443 match Match using proxy"')
FAIL = ('time="2026-09-20T19:22:40+03:00" level=warning msg="[TCP] dial proxy (match Match/) '
        '172.19.0.1:58263(svchost.exe) --> www.msftconnecttest.com:80 error: 203.0.113.20:30444 '
        'connect error: context canceled"')
REALITY_FAIL = ('time="2026-09-21T16:04:20+03:00" level=warning msg="[TCP] dial proxy (match Match/) '
                '172.19.0.1:50000(opera.exe) --> example.org:443 error: node.example.test:443 '
                'connect error: REALITY authentication failed"')
DIRECT_FAIL = ('time="2026-09-22T21:46:49+03:00" level=warning msg="[TCP] dial DIRECT (match Match/) '
               '172.19.0.1:59982(TgSocksLocal.exe) --> 149.154.174.100:443 error: dial tcp 149.154.174.100:443: i/o timeout"')
DIRECT_OK = ('time="2026-09-22T21:46:49+03:00" level=info msg="[TCP] 172.19.0.1:1(a.exe) '
             '--> lan.example:443 match IPCIDR(192.168.0.0/16) using DIRECT"')


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class DialHealthTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.health = DialHealth(clock=self.clock)

    def test_works_then_every_new_connection_fails(self):
        for _ in range(35):
            self.health.feed(OK)
            self.clock.now += 0.7
        self.assertIsNone(self.health.check())
        self.clock.now += WINDOW_SECONDS + 1  # успешные ушли из окна
        for _ in range(MIN_FAILURES):
            self.health.feed(FAIL)
            self.clock.now += 1
        info = self.health.check()
        self.assertTrue(info["blocked"])
        self.assertEqual(info["endpoint"], "203.0.113.20:30444")
        self.assertEqual(info["reason"], "context canceled")
        self.assertIsNone(self.health.check(), "один эпизод — одно сообщение")
        self.health.feed(OK)
        self.assertEqual(self.health.check(), {"recovered": True})

    def test_occasional_failures_among_successes_are_not_a_block(self):
        for _ in range(10):
            self.health.feed(FAIL)
            self.health.feed(OK)
        self.assertIsNone(self.health.check())

    def test_direct_traffic_does_not_count(self):
        for _ in range(20):
            self.health.feed(DIRECT_FAIL)
        self.assertIsNone(self.health.check())
        for _ in range(MIN_FAILURES):
            self.health.feed(FAIL)
        self.health.feed(DIRECT_OK)
        self.assertTrue(self.health.check()["blocked"])

    def test_reality_failure_reason_is_kept(self):
        for _ in range(MIN_FAILURES):
            self.health.feed(REALITY_FAIL)
        info = self.health.check()
        self.assertEqual(info["reason"], "REALITY authentication failed")
        self.assertIn("node.example.test:443", blocked_message("NL", info, "Germany HY2"))

    def test_reset_on_new_connection(self):
        for _ in range(MIN_FAILURES):
            self.health.feed(FAIL)
        self.health.reset()
        self.assertIsNone(self.health.check())


if __name__ == "__main__":
    unittest.main()
