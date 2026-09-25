import logging
import socket
import unittest

from engine import tg_proxy


class TgProxyConfigTests(unittest.TestCase):
    def test_defaults_create_a_hex_secret(self):
        config = tg_proxy.normalize(None)
        self.assertEqual(config["port"], 1443)
        self.assertFalse(config["enabled"])
        self.assertRegex(config["secret"], r"^[0-9a-f]{32}$")

    def test_user_port_is_validated(self):
        self.assertEqual(tg_proxy.normalize({"port": "2443"})["port"], 2443)
        for bad in ("abc", 80, 70000, True, None):
            with self.subTest(port=bad), self.assertRaises(tg_proxy.TgProxyError):
                tg_proxy.normalize({"port": bad})

    def test_ports_of_the_app_are_refused(self):
        with self.assertRaisesRegex(tg_proxy.TgProxyError, "интерфейс"):
            tg_proxy.normalize({"port": 45678})
        with self.assertRaisesRegex(tg_proxy.TgProxyError, "SOCKS5"):
            tg_proxy.normalize({"port": 1080}, reserved={1080: "SOCKS5-прокси"})

    def test_stored_secret_is_kept_and_broken_one_replaced(self):
        secret = "0123456789abcdef0123456789abcdef"
        self.assertEqual(tg_proxy.normalize({"secret": secret})["secret"], secret)
        self.assertNotEqual(tg_proxy.normalize({"secret": "zz"})["secret"], "zz")
        self.assertEqual(tg_proxy.normalize_stored({"port": "bad"})["port"], 1443)

    def test_link_uses_loopback_and_dd_secret(self):
        link = tg_proxy.link({"port": 2443, "secret": "ab" * 16})
        self.assertEqual(link, "tg://proxy?server=127.0.0.1&port=2443&secret=dd" + "ab" * 16)


class TgProxyLogTests(unittest.TestCase):
    def test_secret_never_reaches_the_app_log(self):
        logs = []
        manager = tg_proxy.TgProxyManager(lambda msg, tag: logs.append(msg))
        manager.secret = "cd" * 16
        logger = logging.getLogger("tg-mtproto-proxy")
        logger.info("  Secret:        %s", manager.secret)
        logger.info("    tg://proxy?server=127.0.0.1&port=1443&secret=dd%s", manager.secret)
        logger.info("stats: total=1")
        logger.warning("DC2 failed")
        self.assertEqual(logs, ["[tg-proxy] DC2 failed"])


class TgProxyLifecycleTests(unittest.TestCase):
    def test_start_listens_and_stop_releases_the_port(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        manager = tg_proxy.TgProxyManager()
        ok, error = manager.start(tg_proxy.normalize({"port": port}))
        try:
            self.assertTrue(ok, error)
            socket.create_connection(("127.0.0.1", port), 2).close()
        finally:
            manager.stop(quiet=True)
        self.assertFalse(manager.running)
        self.assertTrue(tg_proxy.port_free(port))

    def test_busy_port_is_reported_without_starting(self):
        with socket.socket() as busy:
            busy.bind(("127.0.0.1", 0))
            busy.listen()
            port = busy.getsockname()[1]
            ok, error = tg_proxy.TgProxyManager().start(tg_proxy.normalize({"port": port}))
        self.assertFalse(ok)
        self.assertIn("занят", error)


if __name__ == "__main__":
    unittest.main()
