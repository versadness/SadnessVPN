"""Apply MSP to an isolated administrative image, without changing installed app."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from installer.build_patch import administrative_image,query
from engine.json_store import atomic_write_json
import msilib


def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--base',required=True);parser.add_argument('--new',required=True)
    args=parser.parse_args()
    from engine.update_manifest import version
    version(args.base);version(args.new)
    folder=ROOT/'build'/f'admin-patch-test-{args.base}-to-{args.new}'
    folder.mkdir(exist_ok=False)
    base=ROOT/'dist'/f'SadnessVPN-{args.base}-Setup-x64.msi'
    patch=ROOT/'dist'/f'SadnessVPN-{args.base}-to-{args.new}-Beta-Update-x64.msp'
    expected=ROOT/'build'/f'patch-{args.base}-to-{args.new}'/'updated'/'Sadness VPN'
    image=administrative_image(base,folder/'image')
    result=subprocess.run(['msiexec.exe','/a',str(image),'/p',str(patch),'/qn','/norestart','/L*v',str(folder/'apply.log')],creationflags=0x08000000)
    if result.returncode not in (0,3010):raise RuntimeError('Administrative patch failed: '+str(result.returncode))
    db=msilib.OpenDatabase(str(image),0)
    actual=dict(query(db,'SELECT `Property`,`Value` FROM `Property`'))['ProductVersion']
    mismatches=[];count=0
    for source in expected.rglob('*'):
        if not source.is_file():continue
        relative=source.relative_to(expected);target=folder/'image'/'Sadness VPN'/relative
        count+=1
        if not target.is_file() or digest(source)!=digest(target):mismatches.append(str(relative))
    report=dict(base=args.base,version=args.new,actual_version=actual,files=count,mismatches=mismatches,
                patch_sha256=digest(patch),ok=actual==args.new and not mismatches and count>0)
    atomic_write_json(str(folder/'result.json'),report)
    print(json.dumps(report))
    if not report['ok']:raise RuntimeError('Patched image differs from full release')


if __name__=='__main__':main()
