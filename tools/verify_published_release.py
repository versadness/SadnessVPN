"""Read-only external verification of the signed manifest and every patch."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import urllib.request
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from engine.update_manifest import parse,verify,select_package,packages,MAX_MANIFEST
from engine.update_policy import MANIFEST_BASE,ALLOWED_HOSTS,PUBLIC_KEY_BASE64

parser=argparse.ArgumentParser();parser.add_argument('--version',required=True);args=parser.parse_args()
with urllib.request.urlopen(MANIFEST_BASE+'/beta.json',timeout=20) as response:
    data=verify(parse(response.read(MAX_MANIFEST+1)),PUBLIC_KEY_BASE64,ALLOWED_HOSTS,'beta')
assert data['version']==args.version
assert data.get('distribution')=='patch-only' and 'full' not in data
for base,package in data['patches'].items():
    selected=select_package(data,base)
    assert selected==package,selected
    checksum=hashlib.sha256();size=0
    with urllib.request.urlopen(package['url'],timeout=30) as response:
        while chunk:=response.read(1024*1024):
            size+=len(chunk)
            if size>package['size']:raise ValueError('Unexpected payload length')
            checksum.update(chunk)
    assert size==package['size'] and checksum.hexdigest()==package['sha256']
    print(f'PASS HTTPS signature/size/SHA256 and direct patch {base} -> {data["version"]}',flush=True)
assert select_package(data,args.version) is None
print(json.dumps(dict(version=data['version'],channel=data['channel'],bytes=sum(p['size'] for p in packages(data)),verified=True)))
