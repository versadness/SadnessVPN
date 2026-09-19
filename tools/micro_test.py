"""Record real automated results against immutable candidate hashes.

--approve-manual is for the owner AFTER testing startup/tray/window/VPN; it
does not run these manual tests. Without it the candidate remains unpublished.
"""
import argparse
import json
from pathlib import Path
import subprocess
import shutil
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.release_candidate import digest
from engine.json_store import atomic_write_json


def main():
    p=argparse.ArgumentParser();p.add_argument('--candidate',required=True,type=Path);p.add_argument('--approve-manual',action='store_true')
    p.add_argument('--technical-only-authorized',action='store_true',help='Owner explicitly authorized publication without manual VPN testing')
    args=p.parse_args()
    report_path=args.candidate/'test-report.json';report=json.loads(report_path.read_text(encoding='utf-8'))
    for name,expected in report['artifacts'].items():
        if Path(name).name!=name or digest(args.candidate/name)!=expected:raise ValueError('Candidate changed; previous tests no longer apply')
    checks={
        'unit_tests':[sys.executable,'-m','unittest','discover','-s','tests','-q'],
        'singbox_dns_config':[sys.executable,'tools/test_dns_config_live.py'],
        'singbox_dns_interception':[sys.executable,'tools/test_dns_intercept_live.py'],
        'mihomo_six_rules':[sys.executable,'tools/test_rule_config_live.py'],
        'parallel_routes':[sys.executable,'tools/test_multi_route_live.py'],
        'subscription_api':[sys.executable,'tools/regression_212.py'],
    }
    node=shutil.which('node')
    if not node:
        bundled=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
        if bundled.is_file():node=str(bundled)
    if node:checks['ui_regression']=[node,'tools/regression_220_ui.cjs']
    else:report['automated']['ui_regression']=False
    for name,command in checks.items():
        log=args.candidate/(name+'.log')
        with log.open('w',encoding='utf-8') as stream:result=subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
        report['automated'][name]=result.returncode==0
    servicing=ROOT/'build'/('servicing-test-'+report['version'])/'result.json'
    if servicing.exists():
        tested=json.loads(servicing.read_text(encoding='utf-8'))
        bound=all(report['artifacts'].get(name)==checksum for name,checksum in tested.get('artifacts',{}).items()) and bool(tested.get('artifacts'))
        report['automated']['msi_msp_roundtrip']=bound and tested.get('ready_for_owner_test') is True
    else:report['automated']['msi_msp_roundtrip']=False
    manifest=json.loads((args.candidate/'update.json').read_text(encoding='utf-8'))
    for base,package in manifest.get('patches',{}).items():
        evidence=ROOT/'build'/('servicing-'+base+'-to-'+report['version']+'.json')
        passed=False
        if evidence.is_file():
            result=json.loads(evidence.read_text(encoding='utf-8'))
            filename=package['url'].rsplit('/',1)[-1]
            passed=(result.get('base')==base and result.get('version')==report['version']
                    and result.get('ready_for_owner_test') is True
                    and result.get('artifacts',{}).get(filename)==report['artifacts'].get(filename)==package['sha256'])
        if not passed and args.technical_only_authorized:
            # Isolated image verification is distinct from installed roundtrip.
            # Still require a real installed roundtrip for the release above.
            evidence=ROOT/'build'/f'admin-patch-test-{base}-to-{report["version"]}'/'result.json'
            if evidence.is_file():
                result=json.loads(evidence.read_text(encoding='utf-8'))
                passed=(result.get('base')==base and result.get('version')==report['version']
                        and result.get('actual_version')==report['version'] and result.get('ok') is True
                        and result.get('files',0)>0 and result.get('mismatches')==[]
                        and result.get('patch_sha256')==package['sha256'])
            report['automated']['patch_image_from_'+base]=passed
            report['automated'].pop('direct_patch_from_'+base,None)
        else:
            report['automated']['direct_patch_from_'+base]=passed
    if args.approve_manual:
        report['manual']={key:True for key in ['launch_and_relaunch','close_and_tray','resize_and_maximize','profile_preserved','vpn_connections','routing_and_settings']}
    if args.technical_only_authorized:
        report['publication_approval']='owner_authorized_technical_only'
    report['ready']=(bool(report['manual']) and all(report['manual'].values()) or args.technical_only_authorized) and all(report['automated'].values())
    atomic_write_json(str(report_path),report)
    print(json.dumps(dict(version=report['version'],automated=report['automated'],owner_microtest=bool(report['manual']),ready=report['ready'])))


if __name__=='__main__':main()
