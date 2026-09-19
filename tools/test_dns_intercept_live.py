"""Offline end-to-end TCP DNS interception through the bundled SOCKS listener.

No TUN, system proxy, real subscription, or external resolver is used.
"""
import json
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from engine.config import build_singbox_config,parse_link

def read_exact(sock,size):
    result=b''
    while len(result)<size:
        chunk=sock.recv(size-len(result))
        if not chunk:raise RuntimeError('Premature EOF')
        result+=chunk
    return result

with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as dns:
    dns.bind(('127.0.0.1',0));dns.settimeout(.2)
    stopping=threading.Event();requests=[]
    def resolve():
        while not stopping.is_set():
            try:query,address=dns.recvfrom(4096)
            except socket.timeout:continue
            requests.append(query)
            answer=query[:2]+bytes.fromhex('81800001000100000000')+query[12:]+bytes.fromhex('c00c000100010000003c0004c000027b')
            dns.sendto(answer,address)
    worker=threading.Thread(target=resolve);worker.start()
    try:
        for scheme,link in [('hy2','hy2://test@example.com:443/'),
                            ('vless','vless://00000000-0000-0000-0000-000000000001@example.com:443?security=tls')]:
            with socket.socket() as reserve:
                reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
            config=build_singbox_config(parse_link(link),socks_port=port)
            config['inbounds']=[i for i in config['inbounds'] if i['type']=='socks']
            config.pop('experimental',None)
            config['dns']={'servers':[{'tag':'test-dns','address':f'udp://127.0.0.1:{dns.getsockname()[1]}','detour':'direct'}],'final':'test-dns'}
            with tempfile.TemporaryDirectory(prefix='sadness-dns-probe-') as folder:
                target=Path(folder)/'config.json';target.write_text(json.dumps(config),encoding='utf-8')
                with (Path(folder)/'core.log').open('w') as log:
                    process=subprocess.Popen([str(ROOT/'bin/sing-box.exe'),'run','-c',str(target)],stdout=log,stderr=log,creationflags=0x08000000)
                    try:
                        for attempt in range(50):
                            try:client=socket.create_connection(('127.0.0.1',port),timeout=1);break
                            except OSError:time.sleep(.1)
                        else:raise RuntimeError('Core did not start')
                        with client:
                            client.settimeout(5);client.sendall(b'\x05\x01\x00')
                            assert read_exact(client,2)==b'\x05\x00'
                            client.sendall(b'\x05\x01\x00\x01'+socket.inet_aton('127.0.0.1')+struct.pack('!H',53))
                            reply=read_exact(client,4);assert reply[:2]==b'\x05\x00',reply
                            if reply[3]==1:read_exact(client,6)
                            elif reply[3]==4:read_exact(client,18)
                            elif reply[3]==3:read_exact(client,read_exact(client,1)[0]+2)
                            else:raise RuntimeError('Invalid SOCKS address type')
                            query=bytes.fromhex('123401000001000000000000')+b'\x05probe\x07example\x00\x00\x01\x00\x01'
                            client.sendall(struct.pack('!H',len(query))+query)
                            answer=read_exact(client,struct.unpack('!H',read_exact(client,2))[0])
                            assert answer[:2]==query[:2] and answer[-4:]==socket.inet_aton('192.0.2.123'),answer
                        print('PASS '+scheme+': TCP DNS to loopback:53 intercepted and answered by isolated resolver')
                    finally:
                        process.terminate()
                        try:process.wait(timeout=5)
                        except subprocess.TimeoutExpired:process.kill();process.wait()
        assert len(requests)>=2
    finally:stopping.set();worker.join(timeout=2)
