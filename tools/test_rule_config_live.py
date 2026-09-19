"""Ask the bundled Mihomo binary to validate all six rule types, offline."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from engine.routing_rules import normalize_rule,resolve_rules
from engine.app_routes import build_multi_route_config

with tempfile.TemporaryDirectory(prefix='sadness-rules-') as folder:
    directory=Path(folder)
    for filename in ('geoip.dat','geosite.dat'):shutil.copy2(ROOT/'bin'/filename,directory/filename)
    rules=[normalize_rule(dict(kind=k,value=v,destination='direct')) for k,v in
           [('process','Telegram.exe'),('geosite','youtube'),('suffix','example.com'),('keyword','example'),('geoip','us'),('cidr','2001:db8::/32')]]
    config=build_multi_route_config(dict(protocol='ss',host='127.0.0.1',port=8388,method='aes-128-gcm',password='local-test'),resolve_rules(rules,[]))
    config['tun']['enable']=False
    target=directory/'config.json';target.write_text(json.dumps(config),encoding='utf-8')
    result=subprocess.run([str(ROOT/'bin/mihomo.exe'),'-d',folder,'-f',str(target),'-t'],capture_output=True,text=True,timeout=30,creationflags=0x08000000)
    if result.returncode:raise RuntimeError(result.stdout+result.stderr)
    print('PASS: bundled Mihomo accepted all six rule types using bundled Geo databases, without a tunnel')
