import unittest
from unittest.mock import patch
from engine.rule_conflicts import analyze


def rule(identity,kind,value,destination='proxy',enabled=True):
    return dict(id=identity,kind=kind,value=value,destination=destination,enabled=enabled)


class RuleConflictTests(unittest.TestCase):
    def test_suffix_shadow_and_direction(self):
        self.assertEqual(analyze([rule('a','suffix','example.com'),rule('b','suffix','a.example.com')])['b'][0]['relation'],'covered')
        self.assertEqual(analyze([rule('a','suffix','a.example.com'),rule('b','suffix','example.com')])['b'][0]['relation'],'partial')

    def test_domain_boundaries(self):
        self.assertEqual(analyze([rule('a','suffix','example.com'),rule('b','suffix','notexample.com')]),{})

    def test_disabled_and_case(self):
        self.assertEqual(analyze([rule('a','process','APP.exe',enabled=False),rule('b','process','app.exe')]),{})
        self.assertTrue(analyze([rule('a','process','APP.exe','direct'),rule('b','process','app.exe')])['b'][0]['different_destination'])

    def test_cidr_ipv4_ipv6_and_family(self):
        for broad,narrow in [('10.0.0.0/8','10.2.0.0/16'),('2001:db8::/32','2001:db8:1::/48')]:
            self.assertEqual(analyze([rule('a','cidr',broad),rule('b','cidr',narrow)])['b'][0]['relation'],'covered')
        self.assertEqual(analyze([rule('a','cidr','0.0.0.0/0'),rule('b','cidr','::/0')]),{})

    def test_keyword_and_no_geo_guess(self):
        self.assertEqual(analyze([rule('a','keyword','example'),rule('b','suffix','example.com')])['b'][0]['relation'],'covered')
        self.assertEqual(analyze([rule('a','geosite','google'),rule('b','suffix','google.com')]),{})

    def test_limit(self):
        with self.assertRaises(ValueError):analyze([{}]*1001)

    def test_readable_categories_keep_technical_values(self):
        from engine.geo_catalog import category_items
        with patch('engine.geo_catalog.categories',return_value=['ru','unknown-category']):
            self.assertEqual(category_items('geoip'),[{'value':'ru','name':'Россия'}, {'value':'unknown-category','name':'unknown-category'}])
