import unittest
from engine.app_routes import assignments, build_multi_route_config
from engine.config import parse_link
from engine.route_info import observed_app_routes


class AppRouteTests(unittest.TestCase):
    def setUp(self):
        self.first={**parse_link('hy2://first@example.com/'), 'ui_id':'first'}
        self.second={**parse_link('trojan://second@example.net:443'), 'ui_id':'second'}
        self.groups=[{'servers':[self.first,self.second]}]

    def test_two_apps_get_distinct_proxies(self):
        routes=assignments([{'exe':'chrome.exe','destination':'server:first'},
                            {'exe':'Discord.exe','destination':'server:second'}], self.groups)
        config=build_multi_route_config(self.first,routes,routing_mode='blacklist',routed_apps=['chrome.exe'])
        self.assertEqual(len(config['proxies']),3)
        self.assertNotEqual(routes[0]['tag'],routes[1]['tag'])
        explicit=f"PROCESS-NAME,chrome.exe,{routes[0]['tag']}"
        self.assertLess(config['rules'].index(explicit),config['rules'].index('PROCESS-NAME,chrome.exe,DIRECT'))

    def test_removed_server_is_error_not_fallback(self):
        with self.assertRaisesRegex(ValueError,'больше не найден'):
            assignments([{'exe':'test.exe','destination':'server:gone'}],self.groups)

    def test_disabled_missing_server_does_not_block(self):
        self.assertEqual(assignments([{'exe':'test.exe','destination':'server:gone','enabled':False}],self.groups),[])

    def test_direct_and_deduplicated_servers(self):
        routes=assignments([{'exe':'a.exe','destination':'direct'},
                            {'exe':'b.exe','destination':'server:first'},
                            {'exe':'c.exe','destination':'server:first'}],self.groups)
        config=build_multi_route_config(self.first,routes,block_udp=True)
        self.assertEqual(len(config['proxies']),2)
        self.assertLess(config['rules'].index('NETWORK,UDP,REJECT'),config['rules'].index('PROCESS-NAME,a.exe,DIRECT'))

    def test_unsupported_protocol_rejected_with_a_clear_reason(self):
        with self.assertRaisesRegex(ValueError,'не поддерживается ядром Mihomo'):
            build_multi_route_config({**self.first,'protocol':'wireguard'},[])

    def test_observed_custom_tag_is_proxy(self):
        rows=observed_app_routes([{'metadata':{'process':'chrome.exe','network':'tcp'},'chains':['app-aabb']}])
        self.assertEqual(rows[0]['routes'],['proxy'])

    def test_rule_injection_rejected(self):
        with self.assertRaises(ValueError):
            assignments([{'exe':'a.exe,DIRECT','destination':'direct'}],self.groups)
