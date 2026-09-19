import unittest
from engine.route_info import observed_rule_routes


class RuleObservationTests(unittest.TestCase):
    def test_core_payload_only_and_private_path_not_exposed(self):
        rules=[dict(id='a',kind='suffix',value='example.com',enabled=True)]
        connection=dict(rule='DomainSuffix',rulePayload='example.com',metadata=dict(processPath=r'C:\Users\Private\Telegram.exe',host='private.example.com'),chains=['DIRECT'])
        result=observed_rule_routes([connection],rules)
        self.assertEqual(result[0]['id'],'a')
        self.assertEqual(result[0]['process'],'Telegram.exe')
        self.assertEqual(result[0]['exit'],'DIRECT')
        self.assertNotIn('Private',str(result));self.assertNotIn('private.example.com',str(result))

    def test_no_guess_from_destination_and_disabled_rule(self):
        rules=[dict(id='a',kind='suffix',value='example.com',enabled=True)]
        self.assertEqual(observed_rule_routes([dict(metadata=dict(host='example.com'),chains=['proxy'])],rules),[])
        rules[0]['enabled']=False
        self.assertEqual(observed_rule_routes([dict(rule='DomainSuffix',rulePayload='example.com')],rules),[])

    def test_first_enabled_rule_wins(self):
        rules=[dict(id=i,kind='process',value='Telegram.exe') for i in ['first','second']]
        result=observed_rule_routes([dict(rule='ProcessName',rulePayload='telegram.exe',chains=['app-a'])],rules)
        self.assertEqual([r['id'] for r in result],['first'])
