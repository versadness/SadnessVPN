"""Проверка сервера: состояния разделены, а проверка действительно изолирована."""
import unittest
from unittest import mock

from engine import server_probe
from engine.config import parse_link

UUID = "11111111-1111-4111-8111-111111111111"


class ProbeConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.server = parse_link(
            f"vless://{UUID}@example.com:443?security=tls&type=ws&path=%2Fws&sni=example.com")

    def test_nothing_can_leave_the_probe_except_through_the_tested_server(self):
        config = server_probe._config(self.server, 18080)

        self.assertEqual(config["rules"], ["MATCH,proxy"])
        self.assertEqual(len(config["proxies"]), 1)
        # Ни одного правила обхода: проверка не может незаметно уйти в DIRECT.
        self.assertFalse([rule for rule in config["rules"] if "DIRECT" in rule])

    def test_probe_never_creates_a_tun_or_takes_the_shared_api_port(self):
        config = server_probe._config(self.server, 18080)

        self.assertNotIn("tun", config)
        self.assertNotIn("external-controller", config)
        self.assertEqual(config["bind-address"], "127.0.0.1")
        self.assertFalse(config["allow-lan"])

    def test_an_unsupported_transport_is_reported_without_starting_the_core(self):
        with mock.patch("engine.server_probe.subprocess.run") as run:
            result = server_probe.probe({**self.server, "type": "kcp"})

        run.assert_not_called()
        self.assertEqual(result["state"], server_probe.UNSUPPORTED)
        self.assertIn("kcp", result["detail"])


class ClassificationTests(unittest.TestCase):
    def test_states_are_distinguished_by_what_the_core_reported(self):
        cases = {
            'level=error msg="x509: certificate signed by unknown authority"':
                server_probe.TLS_ERROR,
            'level=error msg="reality verify failed"': server_probe.TLS_ERROR,
            'level=warning msg="authentication failed"': server_probe.AUTH_ERROR,
            'level=warning msg="dial tcp 198.51.100.1:443: i/o timeout"':
                server_probe.UNREACHABLE,
            'level=warning msg="something else entirely"': server_probe.TRANSPORT_ERROR,
        }
        for log, expected in cases.items():
            with self.subTest(log=log):
                self.assertEqual(server_probe.classify(log), expected)

    def test_every_state_has_a_plain_language_label(self):
        for state in (server_probe.UNSUPPORTED, server_probe.CONFIG_REJECTED,
                      server_probe.UNREACHABLE, server_probe.TLS_ERROR,
                      server_probe.TRANSPORT_ERROR, server_probe.AUTH_ERROR,
                      server_probe.CONNECTED):
            self.assertTrue(server_probe.LABELS[state])

    def test_port_reachable_is_not_reported_as_the_server_being_down(self):
        # «Порт доступен» и «соединение работает» — разные факты, и молча
        # сливать их в «сервер недоступен» нельзя.
        self.assertNotEqual(server_probe.CONNECTED, server_probe.UNREACHABLE)


class SecretSafetyTests(unittest.TestCase):
    def test_probe_result_never_carries_credentials(self):
        server = {"protocol": "vless", "host": "example.com", "port": 443,
                  "uuid": "SECRET-UUID", "security": "tls", "type": "kcp",
                  "password": "SECRET-PASSWORD"}

        result = server_probe.probe(server)

        blob = repr(result)
        self.assertNotIn("SECRET-UUID", blob)
        self.assertNotIn("SECRET-PASSWORD", blob)


if __name__ == "__main__":
    unittest.main()
