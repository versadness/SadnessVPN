import base64
import socket
import unittest
import urllib.error
from unittest.mock import MagicMock, patch
from engine.subscriptions import (parse_metadata, download_subscription, decode_subscription,
                                  SubscriptionError, check_device_headers)
from engine.config import fetch_subscription


class SubscriptionTests(unittest.TestCase):
    def test_metadata_case_base64_and_counters(self):
        title = base64.b64encode('Мой VPN'.encode()).decode()
        m = parse_metadata({'Profile-Title':'base64:' + title, 'Subscription-Userinfo':'upload=1; download=2; total=100; expire=1800000000'})
        self.assertEqual(m['provider_name'], 'Мой VPN')
        self.assertEqual(m['expire'], 1800000000)
        self.assertEqual(m['total'], 100)
        self.assertGreater(m['updated_at'], 0)

    def test_untrusted_metadata_does_not_invent_expiry(self):
        for value in ('expire=NaN', 'expire=-1', 'expire=999999999999999999999', 'expire=253402300800'):
            self.assertNotIn('expire', parse_metadata({'subscription-userinfo':value}))
        self.assertEqual(parse_metadata({'subscription-userinfo':'expire=0'})['expire'], 0)
        self.assertNotIn('provider_name', parse_metadata({'profile-title':'base64:!!!!'}))

    def test_device_limit_has_actionable_error(self):
        for key in ('X-Hwid-Max-Devices-Reached', 'x-hwid-limit', 'x-hwid-not-supported'):
            with self.assertRaises(SubscriptionError):
                check_device_headers({key:'true'})
        check_device_headers({'x-hwid-active':'true', 'x-hwid-limit':'false'})

    def test_timeout_not_empty_server_list(self):
        with patch('urllib.request.urlopen', side_effect=socket.timeout()):
            with self.assertRaisesRegex(SubscriptionError, '25'):
                download_subscription('https://example.test/private-token')

    def test_http_error_does_not_leak_url_or_body(self):
        error = urllib.error.HTTPError('https://example.test/secret', 403, 'secret', {}, None)
        with patch('urllib.request.urlopen', side_effect=error):
            with self.assertRaises(SubscriptionError) as caught:
                download_subscription('https://example.test/secret')
            self.assertIn('403', str(caught.exception))
            self.assertNotIn('secret', str(caught.exception))

    def test_existing_uuid_is_sent_unchanged(self):
        hwid = 'D75E5BD8-72D3-1178-C3A5-1C689F839E09'
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'test'
        with patch('urllib.request.urlopen', return_value=response) as call:
            download_subscription('https://example.test/sub', hwid)
        self.assertEqual(call.call_args.args[0].get_header('X-hwid'), hwid)

    def test_legacy_underscore_not_silently_replaced(self):
        with patch('urllib.request.urlopen') as call:
            with self.assertRaises(SubscriptionError):
                download_subscription('https://example.test/sub', 'svpn_' + 'a'*32)
            call.assert_not_called()

    def test_plain_and_base64_protocols(self):
        for text in ('ss://YWVzLTEyOC1nY206cGFzcw@example.test:443#Server', 'trojan://pass@example.test:443#Server', 'vless://id@example.test:443#Server'):
            for body in (text.encode(), base64.b64encode(text.encode())):
                self.assertEqual(decode_subscription(body), text)

    def test_html_is_not_subscription(self):
        with self.assertRaises(SubscriptionError):
            decode_subscription(b'<!doctype html><html>login</html>')

    def test_empty_clash_retains_metadata_on_error(self):
        with patch('engine.config.download_subscription', return_value=(b'proxies: []\nrules: []', {'expire':123})):
            with self.assertRaisesRegex(SubscriptionError, 'proxies') as caught:
                fetch_subscription('https://example.test/sub')
            self.assertEqual(caught.exception.metadata['expire'], 123)

    def test_zero_listen_address_does_not_discard_good_servers(self):
        body = b'listen: 0.0.0.0\nproxies:\n  - name: Test\n    type: trojan\n    server: example.test\n    port: 443\n    password: test\n'
        with patch('engine.config.download_subscription', return_value=(body, {'expire':123})):
            result = fetch_subscription('https://example.test/sub')
            self.assertEqual(len(result), 1)
            self.assertEqual(result.metadata['expire'], 123)

    def test_response_size_bounded(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'x' * (8*1024*1024+1)
        with patch('urllib.request.urlopen', return_value=response):
            with self.assertRaisesRegex(SubscriptionError, '8'):
                download_subscription('https://example.test/sub')


if __name__ == '__main__':
    unittest.main()
