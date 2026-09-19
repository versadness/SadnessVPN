import unittest

from engine.config import build_singbox_config, parse_link
from engine.core_logs import ErrorNotifications, core_log_tag


class DnsTransportTests(unittest.TestCase):
    def test_plain_dns_both_transports_before_private_bypass(self):
        for link in ('hy2://test@example.com:443/',
                     'vless://00000000-0000-0000-0000-000000000001@example.com:443?security=tls'):
            for mode in ('all', 'whitelist', 'blacklist'):
                with self.subTest(link=link, mode=mode):
                    config = build_singbox_config(parse_link(link), routing_mode=mode,
                                                   routed_apps=['test.exe'], block_udp=True)
                    rules = config['route']['rules']
                    self.assertEqual(rules[0], {'network': ['udp', 'tcp'], 'port': 53, 'outbound': 'dns-out'})
                    self.assertTrue(rules[1]['ip_is_private'])
                    self.assertFalse(any(r.get('port') == 853 and r.get('outbound') == 'dns-out' for r in rules))


class NotificationTests(unittest.TestCase):
    def test_network_burst_is_bounded_but_unrelated_errors_still_notify(self):
        now = [0.0]
        gate = ErrorNotifications(clock=lambda: now[0])
        self.assertTrue(gate.should_notify('ERROR router: missing default interface'))
        for _ in range(36):
            self.assertFalse(gate.should_notify('ERROR dns: exchange failed: no route to internet'))
        self.assertTrue(gate.should_notify('FATAL could not start core'))
        now[0] = 30
        self.assertTrue(gate.should_notify('ERROR inbound/tun: reject while device paused'))

    def test_peer_reset_keeps_error_severity_without_whole_vpn_popup(self):
        gate = ErrorNotifications()
        text = 'ERROR upload: raw-read: An existing connection was forcibly closed by the remote host.'
        self.assertEqual(core_log_tag(text), 'err')
        self.assertFalse(gate.should_notify(text))
        self.assertTrue(gate.should_notify('ERROR connect: connection refused'))


if __name__ == '__main__':
    unittest.main()
