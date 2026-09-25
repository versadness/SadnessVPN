"""Два процесса, два локальных SS-сервера, один клиент Mihomo.

Доказательство одновременной маршрутизации разных приложений в разные
серверы. Всё на loopback: ни подписки, ни TUN, ни внешней сети. Роль
SS-сервера тоже играет mihomo — sing-box из проекта удалён.
"""
import http.server
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from engine.app_routes import assignments,build_multi_route_config


def port():
    with socket.socket() as s:
        s.bind(('127.0.0.1',0));return s.getsockname()[1]


def handler(label):
    class Target(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200);self.end_headers();self.wfile.write(label.encode())
        def log_message(self,*args):pass
    return Target


def main():
    children=[];targets=[]
    with tempfile.TemporaryDirectory(prefix='sadness-multiroute-') as scratch:
        directory=Path(scratch)
        try:
            nodes=[]
            # Один и тот же URL обязан приводить в разные серверы, поэтому цели
            # слушают один порт на разных адресах loopback, а каждый SS-сервер
            # разрешает общее имя в свой адрес через hosts.
            target_port=port()
            for label,address in (('route-A','127.0.0.2'),('route-B','127.0.0.3')):
                target=http.server.ThreadingHTTPServer((address,target_port),handler(label));targets.append(target)
                threading.Thread(target=target.serve_forever,daemon=True).start()
                listen=port()
                config={'log-level':'error','hosts':{'probe.invalid':address},
                        'listeners':[{'name':'ss-in','type':'shadowsocks','listen':'127.0.0.1',
                                      'port':listen,'cipher':'aes-256-gcm','password':'local-test-only'}],
                        'proxies':[],'rules':['MATCH,DIRECT']}
                folder=directory/label;folder.mkdir()
                path=folder/'config.yaml';path.write_text(json.dumps(config))
                children.append(subprocess.Popen([str(ROOT/'bin/mihomo.exe'),'-d',str(folder),'-f',str(path)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=0x08000000))
                nodes.append({'ui_id':label,'protocol':'ss','method':'aes-256-gcm','password':'local-test-only','host':'127.0.0.1','port':listen})
            routes=assignments([{'exe':'curl.exe','destination':'server:route-A'},{'exe':'python.exe','destination':'server:route-B'}],[{'servers':nodes}])
            http_port=port()
            config=build_multi_route_config(nodes[0],routes,http_port=http_port,socks_port=port())
            config['tun']['enable']=False;config['dns']['enable']=False;config.pop('external-controller')
            path=directory/'client.yaml';path.write_text(json.dumps(config))
            log=open(directory/'mihomo.log','w',encoding='utf-8')
            children.append(subprocess.Popen([str(ROOT/'bin/mihomo.exe'),'-d',str(directory),'-f',str(path)],stdout=log,stderr=log,creationflags=0x08000000))
            try:
                for _ in range(70):
                    try:
                        with socket.create_connection(('127.0.0.1',http_port),timeout=.1):break
                    except OSError:time.sleep(.1)
                proxy=f'http://127.0.0.1:{http_port}'
                url=f'http://probe.invalid:{target_port}/'
                curl=['curl.exe','--silent','--show-error','--max-time','8','--noproxy','','--proxy',proxy,url]
                code="import urllib.request; o=urllib.request.build_opener(urllib.request.ProxyHandler({'http':"+repr(proxy)+"})); print(o.open("+repr(url)+",timeout=8).read().decode())"
                env=dict(os.environ);env['NO_PROXY']='';env['no_proxy']=''
                first=subprocess.Popen(curl,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,creationflags=0x08000000)
                second=subprocess.Popen([sys.executable,'-c',code],stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,creationflags=0x08000000)
                a,ae=first.communicate(timeout=12);b,be=second.communicate(timeout=12)
                assert a.strip()==b'route-A' and b.strip()==b'route-B',(a,ae,b,be)
                print('PASS: simultaneous curl.exe -> server A, python.exe -> server B; no TUN or user subscription')
            finally:log.close()
        finally:
            for child in children:
                if child.poll() is None:child.terminate()
            for child in children:child.wait(timeout=10)
            for target in targets:target.shutdown();target.server_close()


if __name__=='__main__':main()
