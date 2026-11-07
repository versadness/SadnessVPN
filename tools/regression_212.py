"""Isolated subscription integration tests; never opens real user profiles or URLs."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
scratch = tempfile.TemporaryDirectory(prefix='sadness-subscriptions-')
import engine.paths
engine.paths.data_dir = lambda: scratch.name
from ui import server as s
from ui import profile_state
from ui import app_state
from engine.connection_state import ConnectionCoordinator
from engine.subscriptions import SubscriptionServers, SubscriptionError


class InlineThread:
    def __init__(self, target, **kwargs): self.target = target
    def start(self): self.target()


class SubscriptionIntegration(unittest.TestCase):
    def setUp(self):
        profile_state.groups = [{'id':'g', 'name':'Custom name', 'url':'https://example.test/private', 'servers':[{
            'ui_id':'old', 'remark':'Old', 'protocol':'ss', 'host':'198.51.100.7',
            'port':8388, 'method':'aes-128-gcm', 'password':'local-test-only',
        }]}]
        profile_state.wg_groups = []
        s._connection = ConnectionCoordinator()
        s._stopping = False
        app_state.reset_for_tests()
        s._app_settings["selected_group"] = 'g'
        s._app_settings["selected_index"] = 0
        s._app_settings["selected_wg_index"] = None
        s._app_settings['hwid'] = 'existing-identifier'
        self.client = s.app.test_client()
        self.events = []
        # Replace only the server's threading reference. Mutating the shared
        # threading module also breaks subprocess' reader threads on Windows.
        self.patches = [patch.object(s,'threading',Mock(wraps=s.threading, Thread=InlineThread)), patch.object(s,'_broadcast',self.events.append)]
        for p in self.patches: p.start()

    def tearDown(self):
        for p in reversed(self.patches): p.stop()

    def post(self, path, data):
        return self.client.post(path, json=data)

    def test_rule_validation_reports_value_without_saving(self):
        with patch.object(s,'save_apps') as save:
            result=self.post('/api/routing/validate',dict(kind='cidr',value='1.2.3.4/99',destination='direct'))
        self.assertEqual(result.status_code,400)
        self.assertEqual(result.json['field'],'value')
        save.assert_not_called()

    def test_rule_validation_reports_missing_server(self):
        result=self.post('/api/routing/validate',dict(kind='suffix',value='example.com',destination='server:missing'))
        self.assertEqual(result.status_code,400)
        self.assertEqual(result.json['field'],'server')

    def test_direct_rule_validation_normalizes_domain(self):
        result=self.post('/api/routing/validate',dict(kind='suffix',value='https://Sub.Example.com/path',destination='direct'))
        self.assertTrue(result.json['ok'])
        self.assertEqual(result.json['rule']['value'],'sub.example.com')

    def test_reconnect_default_is_safe_and_setting_persists(self):
        self.assertFalse(s._app_settings['reconnect'])
        with patch.object(s,'_save_settings',return_value=True):
            result=self.post('/api/app-settings',dict(key='reconnect',value=True))
        self.assertTrue(result.json['ok'])
        self.assertTrue(s._app_settings['reconnect'])

    def test_individual_destination_is_saved_and_broadcast(self):
        profile_state.apps_config={'mode':'all','apps':[{'exe':'test.exe','name':'Test','enabled':True}]}
        with patch.object(s,'save_apps') as save:
            result=self.post('/api/apps/destination',{'exe':'test.exe','destination':'server:old'})
        self.assertTrue(result.json['ok'])
        self.assertEqual(profile_state.apps_config['apps'][0]['destination'],'server:old')
        save.assert_called_once()
        self.assertTrue(any(e['type']=='apps_config' for e in self.events))

    def test_missing_destination_never_saves_a_fallback(self):
        profile_state.apps_config={'mode':'all','apps':[{'exe':'test.exe','name':'Test','enabled':True}]}
        with patch.object(s,'save_apps') as save:
            result=self.post('/api/apps/destination',{'exe':'test.exe','destination':'server:missing'})
        self.assertFalse(result.json['ok'])
        self.assertNotIn('destination',profile_state.apps_config['apps'][0])
        save.assert_not_called()

    def test_destination_cannot_change_during_connection(self):
        profile_state.apps_config={'mode':'all','apps':[{'exe':'test.exe','enabled':True}]}
        s._connection.begin()
        self.assertEqual(self.post('/api/apps/destination',{'exe':'test.exe','destination':'direct'}).status_code,409)

    def test_metadata_and_custom_name_survive_refresh_reload(self):
        result = SubscriptionServers([{'remark':'New'}], {'provider_name':'Provider','expire':1800000000})
        with patch.object(s,'fetch_subscription',return_value=result):
            self.assertTrue(self.post('/api/groups/refresh',{'id':'g'}).json['ok'])
        self.assertEqual(profile_state.groups[0]['name'], 'Custom name')
        self.assertEqual(s.load_groups()[0]['subscription']['expire'],1800000000)
        self.assertEqual(s._groups_for_ui()[0]['subscription']['provider_name'],'Provider')

    def test_failed_refresh_preserves_servers_selection_and_hwid(self):
        before = copy.deepcopy(profile_state.groups[0]['servers'])
        with patch.object(s,'fetch_subscription',side_effect=SubscriptionError('HTTP 403')):
            self.post('/api/groups/refresh',{'id':'g'})
        self.assertEqual(profile_state.groups[0]['servers'],before)
        self.assertEqual(s._app_settings["selected_index"],0)
        self.assertEqual(s._app_settings['hwid'],'existing-identifier')
        self.assertEqual(s.load_groups()[0]['subscription']['error'],'HTTP 403')
        self.assertFalse(s._subscription_lock.locked())

    def test_failed_new_subscription_is_visible_and_retryable(self):
        with patch.object(s,'fetch_subscription',side_effect=SubscriptionError('Timeout')):
            self.post('/api/servers/import',{'url':'https://example.test/new'})
        self.assertEqual(len(profile_state.groups),2)
        self.assertEqual(profile_state.groups[-1]['servers'],[])
        self.assertEqual(profile_state.groups[-1]['subscription']['error'],'Timeout')

    def test_successful_new_subscription_uses_provider_title(self):
        result = SubscriptionServers([{'remark':'New'}], {'provider_name':'Provider'})
        with patch.object(s,'fetch_subscription',return_value=result):
            self.post('/api/servers/import',{'url':'https://example.test/new'})
        self.assertEqual(profile_state.groups[-1]['name'],'Provider')

    def test_conflict_analysis_does_not_mutate_profile(self):
        before=copy.deepcopy(profile_state.apps_config)
        rules=[dict(id='first',kind='suffix',value='example.com',destination='direct'),dict(id='second',kind='suffix',value='a.example.com',destination='proxy')]
        response=self.post('/api/routing/conflicts',{'rules':rules})
        self.assertTrue(response.json['ok'])
        self.assertEqual(response.json['conflicts']['second'][0]['relation'],'covered')
        self.assertEqual(profile_state.apps_config,before)

    def test_wg_metadata_uses_same_flow(self):
        result = SubscriptionServers([{'remark':'WG','is_awg':True}], {'expire':1800000000})
        with patch.object(s,'fetch_wg_subscription',return_value=result):
            self.post('/api/wg/servers/import',{'url':'https://example.test/wg','name':'WG Plan'})
        self.assertEqual(s._wg_groups_for_ui()[0]['subscription']['expire'],1800000000)

    def test_rename_validation_and_delete(self):
        for name in (' ', 'x'*161):
            self.assertEqual(self.post('/api/groups/rename',{'id':'g','name':name}).status_code,400)
        self.assertTrue(self.post('/api/groups/rename',{'id':'g','name':'Renamed'}).json['ok'])
        self.assertEqual(s.load_groups()[0]['name'],'Renamed')
        self.assertTrue(self.post('/api/groups/delete',{'id':'g'}).json['ok'])
        self.assertEqual(s.load_groups(),[])
        self.assertIsNone(s._app_settings["selected_index"])

    def test_concurrent_mutations_rejected(self):
        with s._subscription_lock:
            for path in ('/api/groups/refresh','/api/groups/delete','/api/groups/rename','/api/hwid/regenerate'):
                self.assertEqual(self.post(path,{'id':'g','name':'Other'}).status_code,409)

    def test_download_finishing_after_connect_never_replaces_servers(self):
        before = copy.deepcopy(profile_state.groups)
        def fetch(*args, **kwargs):
            s._connection.begin()
            return SubscriptionServers([{'remark':'New'}])
        with patch.object(s,'fetch_subscription',side_effect=fetch):
            self.post('/api/groups/refresh',{'id':'g'})
        self.assertEqual(profile_state.groups,before)

    def test_save_failure_rolls_back_in_memory(self):
        before = copy.deepcopy(profile_state.groups)
        with patch.object(s,'fetch_subscription',return_value=SubscriptionServers([{'remark':'New'}])), patch.object(profile_state,'save_proxy_groups',side_effect=OSError()):
            self.post('/api/groups/refresh',{'id':'g'})
        self.assertEqual(profile_state.groups,before)
        self.assertEqual(s._app_settings["selected_index"],0)


if __name__ == '__main__':
    import logging
    try:
        unittest.main(verbosity=1)
    finally:
        logging.shutdown()
        scratch.cleanup()
