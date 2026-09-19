"""Scoped HWID transport diagnostic using an isolated, loopback-only HTTP proxy.

Reads existing subscription/credentials without logging them. Never installs a TUN,
changes system proxy/DNS, generates HWIDs, or mutates the user's saved profiles.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine.app_meta import subscription_headers
from engine.config import _build_singbox_outbound
from engine.subscriptions import decode_subscription


def main():
    if len(sys.argv) != 2 or not sys.argv[1].startswith('https://'):
        raise SystemExit('Pass the exact HTTPS subscription to test; it will not be printed.')
    target_url = sys.argv[1]
    data = Path(os.environ['LOCALAPPDATA']) / 'SadnessVPN' / 'data'
    settings = json.loads((data / 'settings.json').read_text(encoding='utf-8'))
    groups = json.loads((data / 'servers.json').read_text(encoding='utf-8'))
    group = next(g for g in groups if g.get('url') and g.get('servers'))
    for index, server in enumerate(group['servers'][:2]):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        config = {'log': {'disabled': True},
                  'inbounds': [{'type': 'http', 'tag':'probe', 'listen':'127.0.0.1', 'listen_port':port}],
                  'outbounds': [_build_singbox_outbound(server)], 'route': {'final':'proxy'}}
        with tempfile.TemporaryDirectory(prefix='sadness-hwid-probe-') as folder:
            path = Path(folder) / 'config.json'
            path.write_text(json.dumps(config), encoding='utf-8')
            process = subprocess.Popen([str(ROOT/'bin'/'sing-box.exe'), 'run', '-c', str(path)],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                ready = False
                for _ in range(30):
                    if process.poll() is not None:
                        break
                    try:
                        with socket.create_connection(('127.0.0.1',port),timeout=.1):
                            ready = True
                            break
                    except OSError:
                        time.sleep(.1)
                if not ready:
                    print('proxy', index, 'startup failed', flush=True)
                    continue
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({'https':f'http://127.0.0.1:{port}'}))
                request = urllib.request.Request(target_url, headers=subscription_headers(settings['hwid']))
                try:
                    with opener.open(request, timeout=12) as response:
                        body = response.read(8388609)
                        print(json.dumps({'proxy':index,'http':response.status,'bytes':len(body),
                                          'content_type':response.headers.get('Content-Type'),
                                          'server':response.headers.get('Server'),
                                          'hwid_flags':{k:response.headers.get(k) for k in ('x-hwid-active','x-hwid-not-supported','x-hwid-max-devices-reached','x-hwid-limit')}},ensure_ascii=True),flush=True)
                        text = decode_subscription(body)
                        print('link_lines',sum(line.strip().startswith(('vless://','ss://','trojan://','hysteria2://')) for line in text.splitlines()),flush=True)
                        return
                except Exception as exc:
                    print('proxy',index,'request failed',type(exc).__name__,flush=True)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)


if __name__ == '__main__':
    main()
