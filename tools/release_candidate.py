"""Assemble an immutable local candidate; this command never contacts the VPS."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from engine.update_manifest import version,canonical
from engine.json_store import atomic_write_json
from engine import update_policy


def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--version',required=True);parser.add_argument('--base',action='append',default=[])
    parser.add_argument('--notes',required=True,type=Path)
    parser.add_argument('--base-url',default=update_policy.MANIFEST_BASE or 'https://updates.example.invalid/updates')
    args=parser.parse_args();version(args.version)
    bases=sorted(set(args.base),key=version)
    if any(version(args.version)<=version(base) for base in bases):raise ValueError('Version must advance')
    candidate=ROOT/'dist'/'candidate'/args.version
    if candidate.exists():raise FileExistsError('Candidate already exists; use a new version or review it explicitly')
    sources=[ROOT/'dist'/f'SadnessVPN-{args.version}-Setup-x64.msi']+[ROOT/'dist'/f'SadnessVPN-{base}-to-{args.version}-Beta-Update-x64.msp' for base in bases]
    missing=[p.name for p in sources if not p.is_file()]
    if missing:raise FileNotFoundError('Build these first: '+', '.join(missing))
    notes=json.loads(args.notes.read_text(encoding='utf-8'))
    if not isinstance(notes,list):raise ValueError('Notes must be a JSON array')
    candidate.mkdir(parents=True)
    packages=[];hashes={}
    for source in sources:
        target=candidate/source.name;shutil.copy2(source,target);checksum=digest(target)
        hashes[target.name]=checksum
        packages.append(dict(url=args.base_url.rstrip('/')+'/releases/'+args.version+'/'+target.name,size=target.stat().st_size,sha256=checksum))
    manifest=dict(schema=1,product='Sadness VPN',version=args.version,channel='beta',published_at=datetime.now(timezone.utc).isoformat(),
                  notes=notes,full=packages[0],patches=dict(zip(bases,packages[1:])))
    trust=candidate/'trust-policy.json'
    atomic_write_json(str(trust),dict(manifest_base=update_policy.MANIFEST_BASE,
        allowed_hosts=list(update_policy.ALLOWED_HOSTS),public_key_base64=update_policy.PUBLIC_KEY_BASE64))
    hashes[trust.name]=digest(trust)
    atomic_write_json(str(candidate/'update.json'),manifest)
    atomic_write_json(str(candidate/'files.sha256.json'),hashes)
    atomic_write_json(str(candidate/'test-report.json'),dict(version=args.version,artifacts=hashes,automated={},manual={},ready=False))
    print(json.dumps(dict(candidate=str(candidate),published=False,requires_micro_test=True)))


if __name__=='__main__':main()
