"""Read-only product audit: all app data and engine actions are isolated/mocked."""
import copy
import io
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import subprocess
import threading
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine.paths

scratch = tempfile.TemporaryDirectory(prefix="sadness-audit-")
engine.paths.data_dir = lambda: scratch.name
from ui import server as s
from ui import profile_state
from ui import app_state
from engine import autostart
from engine.config import build_singbox_config, parse_link
from engine.wg_config import build_wg_tun_config, parse_wg_conf
from engine.diagnostics import redact
from engine.connection_state import ConnectionCoordinator

logging.getLogger("ui.server").disabled = True
client = s.app.test_client()
results = []

def record(case, **evidence):
    results.append({"case": case, **evidence})

def post(path, payload):
    return client.post(path, json=payload, base_url="http://127.0.0.1:45678")

def seed():
    app_state.reset_for_tests()
    profile_state.groups = [{"id":"g", "name":"Test", "url":None, "servers":[
        {"remark":n, "ui_id":n, "protocol":"vless", "host":"192.0.2.1", "port":443,
         "uuid":"00000000-0000-4000-8000-000000000001"} for n in ("A","B","C")]}]
    profile_state.wg_groups = [{"id":"w", "name":"Test WG", "servers":[{"remark":n,"ui_id":n} for n in ("A","B","C")]}]
    s._app_settings["selected_group"], s._app_settings["selected_index"] = "g", 1
    s._app_settings["selected_wg_group"], s._app_settings["selected_wg_index"] = "w", 1
    profile_state.apps_config = {"mode":"whitelist", "apps":[{"exe":"test.exe","name":"Test","enabled":True}]}
    s._connection = ConnectionCoordinator()

seed()
for family, url in [("proxy","/api/servers/delete"),("wg","/api/wg/servers/delete")]:
    seed()
    r=post(url,{"group_id":"g" if family=="proxy" else "w","index":0})
    selected=(s._get_selected_server() if family=="proxy" else s._get_selected_wg_server())
    record("delete_before_selected",family=family,response=r.get_json(),selected=selected.get("remark") if selected else None,expected="B")

seed()
for mode in ("whitelist","blacklist"):
    cfg=build_singbox_config(profile_state.groups[0]["servers"][0],routing_mode=mode,routed_apps=[])
    record("empty_routing",mode=mode,final=cfg["route"]["final"],process_rules=[r for r in cfg["route"]["rules"] if "process_name" in r])

seed()
attempt=s._connection.begin();s._connection.complete(attempt)
for url,body in [("/api/apps/toggle",{"exe":"test.exe","enabled":False}),
                 ("/api/apps/mode",{"mode":"blacklist"}),
                 ("/api/servers/select",{"group_id":"g","index":2}),
                 ("/api/settings",{"socks":12080,"http":12081}),
                 ("/api/socks5/regenerate",{}),
                 ("/api/tunnel-settings",{"block_udp":True})]:
    r=post(url,body)
    record("change_while_connected",endpoint=url,status=r.status_code,ok=r.get_json().get("ok"))

seed()
with patch.object(s,"_save_settings",return_value=False):
    r=post("/api/protocol",{"protocol":"wg"})
    record("protocol_save_failure",response=r.get_json(),in_memory=s._app_settings["active_protocol"])

seed()
with patch.object(autostart,"enabled",return_value=True),patch.object(autostart,"_run",return_value=(1,"Access denied")):
    s._app_settings["startup"]=True
    r=post("/api/app-settings",{"key":"startup","value":False})
    record("autostart_delete_failure",response=r.get_json(),stored=s._app_settings["startup"])

seed()
before=[x["ui_id"] for x in profile_state.groups[0]["servers"]]
new=[{k:v for k,v in x.items() if k!="ui_id"} for x in profile_state.groups[0]["servers"]]
profile_state.groups[0]["servers"]=new;profile_state.ensure_server_ids(profile_state.groups)
record("subscription_identity_refresh",old_ids=before,kept_ids=sum(x["ui_id"] in before for x in new))

seed()
invalid_cases=[("/api/apps/add",{"exe":123}),("/api/servers/select",{"group_id":"g","index":"0"}),
               ("/api/servers/delete",{"group_id":"g","index":0.5}),
               ("/api/wg/servers/select",{"group_id":"w","index":"0"}),
               ("/api/servers/add",{"link":42}),("/api/apps/toggle",{"exe":"test.exe","enabled":"false"})]
for url,body in invalid_cases:
    r=post(url,body)
    record("malformed_input",endpoint=url,body=body,status=r.status_code,response=r.get_json())

seed()
r=client.post("/api/appearance/avatar",data={"file":(io.BytesIO(b"\x89PNG\r\n\x1a\nNOT_AN_IMAGE"),"bad.png")},base_url="http://127.0.0.1:45678")
record("corrupt_image",response=r.get_json())
for value in ['private_key=TEST_SECRET','{"password":"TEST_SECRET"}','Authorization: Bearer TEST_SECRET']:
    record("redaction",input=value,output=redact(value),leaks="TEST_SECRET" in redact(value))

seed()
for timeout in (1,50,100,200,3000):
    r=post("/api/ping-settings",{"ping_timeout":timeout})
    record("ping_timeout",entered_ms=timeout,accepted=r.get_json().get("ok"),effective_seconds=s._ping_timeout_seconds(timeout))

seed()
with patch.object(s,"_start_vpn_for_attempt",return_value=True),patch.object(s,"_wait_clash_ready",return_value=True),patch.object(s,"_start_traffic_monitor"),patch.object(s,"_start_ping_monitor"):
    a=s._connection.begin();s._finish_vpn_attempt(a,{},"Unreachable test endpoint")
    record("tunnel_ready_not_remote_ready",state=s._connection.state)

seed()
entered=threading.Event();release=threading.Event();cancelled=threading.Event()
def slow_awg(_server):
    entered.set();release.wait(2);return False
with patch.object(s.awg_engine,"start",side_effect=slow_awg),patch.object(s,"_stop_vpn_engine"),patch.object(s,"_reset_connection_state"):
    a=s._connection.begin()
    worker=threading.Thread(target=s._finish_awg_attempt,args=(a,{},"Test"));worker.start();entered.wait(1)
    canceller=threading.Thread(target=lambda:(s._cancel_vpn_connection(),cancelled.set()));canceller.start()
    record("awg_cancel_blocked_during_start",cancel_completes_within_200ms=cancelled.wait(.2))
    release.set();worker.join();canceller.join()

record("guards",external_origin=client.post('/api/disconnect',headers={'Origin':'https://example.test'},base_url='http://127.0.0.1:45678').status_code,
       external_host=client.get('/api/health',base_url='http://evil.test:45678').status_code)

from engine.stats import StatsTracker
tracker=StatsTracker();tracker.reset_all();tracker.start();tracker.update(100,200)
before=tracker.get_snapshot();tracker.stop();after=tracker.get_snapshot()
record('stats_after_stop',before_total=before['total']['down'],after_total=after['total']['down'],expected=200)
tracker.start();tracker.update(100,200);tracker.reset_all()
record('stats_reset_active',after_reset=tracker.get_snapshot()['total']['down'],expected=0)
tracker.stop()

key='AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE='
base=f'[Interface]\nPrivateKey={key}\nAddress=10.0.0.2/32\nDNS=2606:4700:4700::1111\n[Peer]\nPublicKey={key}\nEndpoint=192.0.2.1:51820\nAllowedIPs=10.1.0.0/16\n'
parsed=parse_wg_conf(base)[0]
record('wg_ipv6_dns',parsed_dns=parsed['dns'],expected=['2606:4700:4700::1111'])
record('wg_routes_replaced',source=parsed['source_allowed_ips'],actual=parsed['allowed_ips'])
peers=parse_wg_conf(base+f'[Peer]\nPublicKey={key}\nEndpoint=192.0.2.2:51821\nAllowedIPs=10.2.0.0/16\n')
record('wg_multiple_peers',configs=len(peers),retained_endpoint=peers[0]['endpoint'])
seed()
r=post('/api/wg/servers/add',{'conf':'[Interface]\nPrivateKey=invalid'})
record('wg_invalid_config_import',response=r.get_json())

seed()
for host in ('192.0.2.1','vpn.example.test','2001:db8::1'):
    candidate={**parsed,'endpoint':host}
    cfg=build_wg_tun_config(candidate)
    target=Path(scratch.name,'check.json');target.write_text(json.dumps(cfg),encoding='utf-8')
    proc=subprocess.run([str(Path(__file__).resolve().parents[1]/'bin/sing-box.exe'),'check','-c',str(target)],capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
    record('wg_endpoint_config_check',endpoint=host,exit=proc.returncode,error=(proc.stderr or proc.stdout).strip()[-450:])
for preset,custom in [('cf_google',None),('xbox_dot',None),('custom',['https://dns.example.test/dns-query']),('custom',['tls://1.1.1.1'])]:
    cfg=build_wg_tun_config(parsed,dns_preset=preset,custom_dns=custom)
    record('wg_dns_generation',preset=preset,input=custom,generated=cfg['dns']['servers'][0]['address'])

seed()
messages=[]
class InlineThread:
    def __init__(self,target,**kwargs): self.target=target
    def start(self): self.target()
with patch.object(s.threading,'Thread',InlineThread),patch.object(s,'fetch_subscription',side_effect=ValueError('Synthetic import failure')),patch.object(s,'_broadcast',side_effect=messages.append):
    r=post('/api/servers/import',{'url':'https://example.test/sub'})
    record('async_import_failure',response=r.get_json(),event_types=[m['type'] for m in messages])

from engine.amneziawg import AmneziaWGManager
manager=AmneziaWGManager();manager.running=True
with patch.object(manager,'_uninstall_owned_service',return_value=False),patch.object(manager,'_remove_config'):
    manager.stop()
    record('awg_stop_service_failure',running_after=manager.running,uninstall_success=False)

seed()
fake_awg=base+'\n[Interface]\nPrivateKey=invalid\nJc=4\n'
messages=[]
with patch.object(s,'_broadcast',side_effect=messages.append):
    post('/api/wg/servers/add',{'conf':fake_awg})
record('awg_import_warning',warnings=[m['msg'] for m in messages if m['type']=='log' and 'sing-box' in m['msg']])

seed()
matrix=[]
for protocol in ('vless','ss','trojan','hysteria2','wg'):
    for setting in ({},{'fakedns':True},{'block_udp':True},{'mux':True},{'dns_preset':'xbox_dot'},{'routing_mode':'whitelist','routed_apps':['test.exe']}):
        if protocol=='wg':cfg=build_wg_tun_config(parsed,**setting)
        else:
            server={**profile_state.groups[0]['servers'][0],'protocol':protocol,'password':'test-password','method':'aes-128-gcm'}
            cfg=build_singbox_config(server,**setting)
        target=Path(scratch.name,'matrix.json');target.write_text(json.dumps(cfg),encoding='utf-8')
        proc=subprocess.run([str(Path(__file__).resolve().parents[1]/'bin/sing-box.exe'),'check','-c',str(target)],capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
        matrix.append({'protocol':protocol,'setting':setting,'exit':proc.returncode,'error':proc.stderr.strip()[-250:] if proc.returncode else ''})
record('config_matrix',tested=len(matrix),failures=[x for x in matrix if x['exit']])

output=Path(__file__).resolve().parents[1]/'build/audit-209-backend-results.json'
output.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'cases':len(results),'results_file':str(output),'last_cases':results[-3:]},ensure_ascii=False,indent=2))
logging.shutdown()
scratch.cleanup()
