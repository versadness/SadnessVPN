"""Isolated regressions: no user profiles, network tunnels or startup tasks mutated."""
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
scratch = tempfile.TemporaryDirectory(prefix="sadness-regression-")
import engine.paths
engine.paths.data_dir = lambda: scratch.name
from ui import server as s
from ui import profile_state
from ui import app_state
from engine.connection_state import ConnectionCoordinator
from engine.stats import StatsTracker
from engine.wg_config import parse_wg_conf, build_wg_tun_config
from engine.config import build_singbox_config
from engine.diagnostics import redact
from engine.amneziawg import AmneziaWGManager
from engine import autostart, ping

KEY = 'AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE='
CONF = f'[Interface]\nPrivateKey={KEY}\nAddress=10.0.0.2/32\nDNS=2606:4700:4700::1111\n[Peer]\nPublicKey={KEY}\nEndpoint=192.0.2.1:51820\n'


class Regression(unittest.TestCase):
    def setUp(self):
        app_state.reset_for_tests()
        s._connection = ConnectionCoordinator()
        s._stopping = False
        s._vpn_error = False
        s._app_settings["active_protocol"] = 'vless'
        profile_state.groups = [{'id':'g','name':'Proxy','servers':[{'ui_id':n,'remark':n,'protocol':'vless','host':'192.0.2.1','port':443,'uuid':'00000000-0000-4000-8000-000000000001'} for n in ('A','B','C')]}]
        # Different endpoints distinguish real subscription identities.
        for i, server in enumerate(profile_state.groups[0]['servers']): server['port'] += i
        profile_state.wg_groups = [{'id':'w','name':'WG','servers':[dict(parse_wg_conf(CONF)[0],ui_id=n,remark=n,port=51820+i) for i,n in enumerate(('A','B','C'))]}]
        s._app_settings["selected_group"], s._app_settings["selected_index"] = 'g',1
        s._app_settings["selected_wg_group"], s._app_settings["selected_wg_index"] = 'w',1
        profile_state.apps_config={'mode':'whitelist','apps':[{'exe':'test.exe','enabled':True}]}
        self.client=s.app.test_client()

    def post(self,path,body):
        return self.client.post(path,json=body,base_url='http://127.0.0.1:45678')

    def test_delete_before_selection(self):
        for family,gid,get in [('', 'g',s._get_selected_server),('/wg','w',s._get_selected_wg_server)]:
            self.assertTrue(self.post('/api'+family+'/servers/delete',{'group_id':gid,'index':0}).json['ok'])
            self.assertEqual(get()['ui_id'],'B')

    def test_refresh_reorders_preserving_identity_and_selection(self):
        for groups,wg in [(profile_state.groups,False),(profile_state.wg_groups,True)]:
            old=groups[0]['servers']
            new=[{k:v for k,v in server.items() if k!='ui_id'} for server in reversed(old)]
            new[1]['remark']='Renamed'
            s._replace_group_servers(groups[0],new,wireguard=wg)
            self.assertEqual([x['ui_id'] for x in new],['C','B','A'])
            self.assertEqual((s._get_selected_wg_server if wg else s._get_selected_server)()['ui_id'],'B')

    def test_selection_save_failure_rolls_back(self):
        for family,gid in [('', 'g'),('/wg','w')]:
            with patch.object(s,'_save_settings',return_value=False):
                result=self.post('/api'+family+'/servers/select',{'group_id':gid,'index':2})
            self.assertEqual(result.status_code,500)
            self.assertEqual(s._app_settings["selected_wg_index"] if family else s._app_settings["selected_index"],1)
            self.assertEqual(s._app_settings["active_protocol"],'vless')

    def test_protocol_save_failure(self):
        with patch.object(s,'_save_settings',return_value=False):
            self.assertFalse(self.post('/api/protocol',{'protocol':'wg'}).json['ok'])
        self.assertEqual(s._app_settings["active_protocol"],'vless')

    def test_active_network_changes_rejected_sort_allowed(self):
        attempt=s._connection.begin();s._connection.complete(attempt)
        for endpoint,body in [('/apps/toggle',{'exe':'test.exe','enabled':False}),('/apps/add',{'exe':'new.exe'}),('/apps/remove',{'exe':'test.exe'}),('/servers/select',{'group_id':'g','index':2}),('/settings',{'socks':12080,'http':12081}),('/socks5/regenerate',{})]:
            self.assertEqual(self.post('/api'+endpoint,body).status_code,409,endpoint)
        self.assertTrue(self.post('/api/tunnel-settings',{'server_sort':'name'}).json['ok'])

    def test_malformed_values_are_400(self):
        for endpoint,body in [('/apps/add',{'exe':123}),('/servers/select',{'group_id':'g','index':'1'}),('/servers/delete',{'group_id':'g','index':.5}),('/servers/add',{'link':42}),('/apps/toggle',{'exe':'test.exe','enabled':'false'}),('/settings',[])]:
            self.assertEqual(self.post('/api'+endpoint,body).status_code,400,endpoint)

    def test_corrupt_image_rejected(self):
        result=self.client.post('/api/appearance/avatar',data={'file':(io.BytesIO(b'\x89PNG\r\n\x1a\nBAD'),'bad.png')},base_url='http://127.0.0.1:45678')
        self.assertFalse(result.json['ok'])

    def test_redacts_secret_forms(self):
        for value in ['private_key=TEST_SECRET','{"password":"TEST_SECRET"}','Authorization: Bearer TEST_SECRET','PresharedKey = TEST_SECRET','socks5_pass: TEST_SECRET']:
            self.assertNotIn('TEST_SECRET',redact(value))

    def test_stats_stop_and_active_resets(self):
        tracker=StatsTracker();tracker.reset_all();tracker.start();tracker.update(100,200)
        tracker.stop();self.assertEqual(tracker.get_snapshot()['total']['down'],200)
        tracker.start();tracker.update(100,200);tracker.reset_today()
        self.assertEqual(tracker.get_snapshot()['today']['down'],0)
        self.assertEqual(tracker.get_snapshot()['total']['down'],400)
        tracker.reset_all();self.assertEqual(tracker.get_snapshot()['total']['down'],0)
        tracker.update(150,250);tracker.stop()
        self.assertEqual(tracker.get_snapshot()['total']['down'],50)

    def test_invalid_wg_and_multipeer_rejected(self):
        for conf in ['[Interface]\nPrivateKey=bad',CONF.replace(KEY,'bad',1),CONF.replace(':51820',':wrong'),CONF+'[Peer]\nPublicKey='+KEY]:
            with self.assertRaises(ValueError):parse_wg_conf(conf)

    def test_ipv6_dns_preserved(self):
        self.assertEqual(parse_wg_conf(CONF)[0]['dns'],['2606:4700:4700::1111'])

    def test_empty_whitelist_never_falls_through_proxy(self):
        for build,server in [(build_singbox_config,profile_state.groups[0]['servers'][0]),(build_wg_tun_config,parse_wg_conf(CONF)[0])]:
            rules=build(server,routing_mode='whitelist',routed_apps=[])['route']['rules']
            self.assertEqual(rules[-1]['outbound'],'direct')

    def test_config_matrix_real_singbox_check(self):
        for endpoint in ['192.0.2.1','vpn.example.test','2001:db8::1']:
            for dns in [None,'https://dns.example.test/dns-query','tls://1.1.1.1']:
                server=dict(parse_wg_conf(CONF)[0],endpoint=endpoint)
                cfg=build_wg_tun_config(server,**({'dns_preset':'custom','custom_dns':[dns]} if dns else {}))
                with self.subTest(endpoint=endpoint,dns=dns):
                    path=Path(scratch.name,'config.json');path.write_text(json.dumps(cfg),encoding='utf-8')
                    result=subprocess.run([str(ROOT/'bin/sing-box.exe'),'check','-c',str(path)],capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
                    self.assertEqual(result.returncode,0,result.stderr[-300:])

    def test_occupied_local_proxy_port_is_reassigned_and_persisted(self):
        s._app_settings["socks"], s._app_settings["http"] = 1080, 8080
        s._app_settings["socks"], s._app_settings["http"] = 1080, 8080
        events = []
        with patch.object(s.vpn_engine, "_port_free", side_effect=lambda port: port != 1080), patch.object(s.vpn_engine, "_port_owner", return_value="TgSocksLocal.exe"), patch.object(s, "_save_settings", return_value=True), patch.object(s, "_broadcast", events.append):
            self.assertTrue(s._ensure_local_proxy_ports())
        self.assertEqual((s._app_settings["socks"], s._app_settings["http"]), (1081, 8080))
        self.assertEqual((s._app_settings["socks"], s._app_settings["http"]), (1081, 8080))
        self.assertTrue(any(event.get("type") == "app_settings_updated" for event in events))

    def test_ping_units_and_type(self):
        self.assertEqual(s._ping_timeout_seconds(200),.2)
        for ms in [1,50,100]:self.assertFalse(self.post('/api/ping-settings',{'ping_timeout':ms}).json['ok'])
        with patch.object(ping,'icmp_ping',return_value=12) as probe:
            self.assertEqual(ping.wg_ping('example.test',51820,timeout=.2,ping_type='icmp'),12)
            probe.assert_called_once_with('example.test',.2)

    def test_awg_stop_failure_keeps_ownership(self):
        manager=AmneziaWGManager();manager.running=True
        with patch.object(manager,'_uninstall_owned_service',return_value=False),patch.object(manager,'_remove_config') as remove:
            with self.assertRaises(RuntimeError):manager.stop()
            self.assertTrue(manager.running);remove.assert_not_called()

    def test_awg_cancellation_does_not_hold_coordinator(self):
        entered=threading.Event();release=threading.Event()
        def start(server,**kwargs):entered.set();release.wait(3);return False
        with patch.object(s.awg_engine,'start',side_effect=start),patch.object(s,'_stop_vpn_engine'):
            attempt=s._connection.begin()
            worker=threading.Thread(target=s._finish_awg_attempt,args=(attempt,{},'Test'));worker.start()
            self.assertTrue(entered.wait(1))
            begin=time.perf_counter();response=self.post('/api/disconnect',{})
            self.assertTrue(response.json['ok']);self.assertLess(time.perf_counter()-begin,.2)
            self.assertFalse(s._connection.is_current(attempt));release.set();worker.join(2)
            self.assertFalse(worker.is_alive())
            self.assertTrue(s._disconnect_lock.acquire(timeout=2));s._disconnect_lock.release()

    def test_autostart_delete_failure_not_silent(self):
        s._app_settings['startup']=True
        with patch.object(autostart,'enabled',return_value=True),patch.object(autostart,'_run',return_value=(1,'Access denied')):
            self.assertFalse(self.post('/api/app-settings',{'key':'startup','value':False}).json['ok'])
        self.assertTrue(s._app_settings['startup'])

    def test_autostart_already_absent_is_idempotent(self):
        with patch.object(autostart,'enabled',return_value=False),patch.object(autostart,'_run') as run:
            self.assertTrue(self.post('/api/app-settings',{'key':'startup','value':False}).json['ok'])
            run.assert_not_called()

    def test_async_import_error_visible_event(self):
        messages=[]
        class InlineThread:
            def __init__(self,target,**kwargs):self.target=target
            def start(self):self.target()
        with patch.object(s.threading,'Thread',InlineThread),patch.object(s,'fetch_subscription',side_effect=ValueError('Synthetic failure')),patch.object(s,'_broadcast',side_effect=messages.append):
            self.assertTrue(self.post('/api/servers/import',{'url':'https://example.test/sub'}).json['ok'])
        self.assertIn('operation_error',[m['type'] for m in messages])

    def test_wg_import_broadcasts_protocol(self):
        messages=[]
        with patch.object(s,'_broadcast',side_effect=messages.append):
            self.assertTrue(self.post('/api/wg/servers/add',{'conf':CONF}).json['ok'])
        event=next(m for m in messages if m['type']=='wg_groups_updated')
        self.assertEqual(event['activeProtocol'],'wg')

    def test_unknown_awg_service_query_not_reported_absent(self):
        manager=AmneziaWGManager()
        with patch.object(manager,'_run',return_value=subprocess.CompletedProcess([],5,'','Access denied')):
            self.assertEqual(manager._service_state(),-1)

    def test_failed_shutdown_keeps_window_open(self):
        from ui.window_control import WindowController
        from unittest.mock import Mock
        shown=threading.Event()
        controller=WindowController(Mock(),Mock(side_effect=RuntimeError('Synthetic stop failure')),'')
        controller.show_error=lambda text:shown.set()
        controller.close();self.assertTrue(shown.wait(1))
        self.assertFalse(controller._allow_close)
        self.assertFalse(controller._closing)


if __name__=='__main__':
    try:unittest.main(verbosity=2)
    finally:
        import logging
        logging.shutdown();scratch.cleanup()
