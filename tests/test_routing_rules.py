import unittest
from engine.routing_rules import normalize_rule,validate_rules,resolve_rules
from engine.app_routes import build_multi_route_config


class RoutingRuleTests(unittest.TestCase):
    def rule(self,kind,value,**kw):return normalize_rule(dict(kind=kind,value=value,**kw))

    def test_domain_and_ip_normalization(self):
        self.assertEqual(self.rule('suffix','https://Sub.Example.com/path')['value'],'sub.example.com')
        self.assertEqual(self.rule('cidr','2001:db8::1/64')['value'],'2001:db8::/64')
        self.assertEqual(self.rule('cidr','192.0.2.1')['value'],'192.0.2.1/32')
        self.assertEqual(self.rule('suffix','рф')['value'],'xn--p1ai')

    def test_injection_and_system_process_rejected(self):
        for kind,value in [('process','a.exe,DIRECT'),('process','svchost.exe'),('suffix','a\n.example.com'),('cidr','1.2.3.4/99'),('keyword','foo,bar'),('geoip','cn,REJECT')]:
            with self.subTest(kind=kind,value=value),self.assertRaises(ValueError):self.rule(kind,value)

    def test_unknown_server_rejected_disabled_preserved(self):
        rule=self.rule('suffix','example.com',destination='server:missing')
        with self.assertRaises(ValueError):resolve_rules([rule],[])
        rule['enabled']=False;self.assertEqual(resolve_rules([rule],[]),[])

    def test_all_types_compile_and_order(self):
        inputs=[('process','Telegram.exe'),('geosite','youtube'),('suffix','example.com'),('keyword','example'),('geoip','us'),('cidr','2001:db8::/32')]
        rules=[self.rule(k,v,destination='direct') for k,v in inputs]
        routes=resolve_rules(rules,[])
        server=dict(protocol='ss',host='127.0.0.1',port=8388,method='aes-128-gcm',password='test')
        config=build_multi_route_config(server,routes)
        compiled=[r for r in config['rules'] if any(r.startswith(p) for p in ('PROCESS-NAME,','GEOSITE,','DOMAIN-','GEOIP,','IP-CIDR6,'))]
        self.assertEqual([r for r in compiled if not r.endswith(',no-resolve')],[r['match']+',DIRECT' for r in routes])

    def test_local_categories_exist(self):
        self.assertEqual(len(validate_rules([self.rule('geosite','youtube')],[])),1)
        with self.assertRaises(ValueError):validate_rules([self.rule('geoip','no_such_country')],[])


class GeoCategoryNameTests(unittest.TestCase):
    def test_categories_with_exclamation_mark_are_accepted(self):
        # В списке выбора есть category-ai-!cn: проверка не должна его отвергать.
        rule=normalize_rule(dict(kind='geosite',value='category-ai-!cn'))
        self.assertEqual(rule['value'],'category-ai-!cn')
        self.assertEqual(len(validate_rules([rule],[])),1)

    def test_rule_syntax_characters_are_still_rejected(self):
        for value in ('a,b','x(y)','a b'):
            with self.subTest(value=value),self.assertRaises(ValueError):
                normalize_rule(dict(kind='geosite',value=value))


if __name__=='__main__':unittest.main()
