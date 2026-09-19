"""Validate DNS transport regression with the bundled sing-box, without a VPN."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from engine.config import build_singbox_config,parse_link

with tempfile.TemporaryDirectory(prefix='sadness-dns-check-') as directory:
    for link in ('hy2://test@example.com:443/',
                 'vless://00000000-0000-0000-0000-000000000001@example.com:443?security=tls'):
        config=build_singbox_config(parse_link(link))
        target=Path(directory)/'config.json'
        target.write_text(json.dumps(config),encoding='utf-8')
        result=subprocess.run([str(ROOT/'bin/sing-box.exe'),'check','-c',str(target)],
                              capture_output=True,text=True,timeout=30,creationflags=0x08000000)
        if result.returncode:raise RuntimeError(result.stdout+result.stderr)
        print('PASS bundled sing-box DNS configuration: '+parse_link(link).get('protocol','vless'))
