"""Owner-requested local servicing test: MSP forward, uninstall patch, MSI forward.

Requires no running SadnessVPN or its engines. Never deletes or prints profiles.
Reports exact package hashes and profile integrity; Windows Installer owns rollback.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import psutil
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from installer.updater_main import installed_version,protected_directory
from installer.recovery_cache import cache_full,recovery_package
from installer.msi_source import stage_minor_msi
from engine.update_policy import PRODUCT_CODE
from engine.json_store import atomic_write_json


def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    p=argparse.ArgumentParser();p.add_argument('--base',required=True);p.add_argument('--new',required=True);args=p.parse_args()
    installed=Path(os.environ['ProgramFiles'])/'Sadness VPN'
    for process in psutil.process_iter(['exe']):
        if process.info['exe'] and Path(process.info['exe']).is_relative_to(installed):raise RuntimeError('Close Sadness VPN first')
    if installed_version()!=args.base:raise RuntimeError('Unexpected installed version')
    folder=ROOT/'build'/('servicing-test-'+args.new);folder.mkdir(exist_ok=False)
    profile=Path(os.environ['LOCALAPPDATA'])/'SadnessVPN'/'data'
    names=['settings.json','servers.json','wg_servers.json','apps.json','stats.json']
    before={n:digest(profile/n) for n in names if (profile/n).is_file()}
    msi=ROOT/'dist'/f'SadnessVPN-{args.new}-Setup-x64.msi'
    base=ROOT/'dist'/f'SadnessVPN-{args.base}-Setup-x64.msi'
    patch=ROOT/'dist'/f'SadnessVPN-{args.base}-to-{args.new}-Beta-Update-x64.msp'
    for item in (msi,base,patch):
        if not item.is_file():raise FileNotFoundError(item.name)
    protected=protected_directory();cache_full(base,protected,args.base)
    report=dict(base=args.base,version=args.new,checks={},artifacts={p.name:digest(p) for p in (msi,patch)})
    report['profile_before']=before
    report_path=folder/'result.json'
    def run(name,command,expected):
        result=subprocess.run(['msiexec.exe',*command,'/qn','/norestart','/L*v',str(folder/(name+'.log'))],creationflags=0x08000000)
        actual=installed_version();ok=result.returncode in (0,3010) and actual==expected
        report['checks'][name]=dict(ok=ok,exit_code=result.returncode,installed_version=actual)
        atomic_write_json(str(report_path),report)
        if not ok:raise RuntimeError('Servicing failed: '+name)
        print('PASS '+name,flush=True)
    run('apply_patch',['/p',str(patch)],args.new)
    import msilib,re
    database=msilib.OpenDatabase(str(patch),32)
    revision=database.GetSummaryInformation(0).GetProperty(9)
    if isinstance(revision,bytes):revision=revision.decode('ascii')
    patch_id=revision.split(';')[0]
    if not re.fullmatch(r'\{[A-Fa-f0-9-]{36}\}',patch_id):raise ValueError('Invalid patch ID')
    del database
    run('rollback_patch',['/package',PRODUCT_CODE,'/uninstall',patch_id],args.base)
    def staged_msi():
        return stage_minor_msi(msi,protected,dict(sha256=digest(msi),size=msi.stat().st_size))
    run('install_full',['/i',str(staged_msi()),'REINSTALL=ALL','REINSTALLMODE=vomus'],args.new)
    previous_msi=recovery_package(protected,args.base)
    remove=subprocess.run(['msiexec.exe','/x',PRODUCT_CODE,'/qn','/norestart','/L*v',str(folder/'rollback-remove.log')],creationflags=0x08000000)
    if remove.returncode not in (0,3010):raise RuntimeError('Rollback removal failed')
    run('rollback_full',['/i',str(previous_msi)],args.base)
    run('reinstall_full',['/i',str(staged_msi()),'REINSTALL=ALL','REINSTALLMODE=vomus'],args.new)
    # Same minimal cache-only entry point used by fresh MSI setup.
    helper=installed/'SadnessUpdater.exe'
    result=subprocess.run([str(helper),'--cache-installed',str(msi)],creationflags=0x08000000)
    report['checks']['cache_full']=dict(ok=result.returncode==0 and recovery_package(protected,args.new).is_file())
    after={n:digest(profile/n) for n in names if (profile/n).is_file()}
    report['checks']['profile_preserved']=dict(ok=before==after)
    report['ready_for_owner_test']=all(r['ok'] for r in report['checks'].values())
    atomic_write_json(str(report_path),report)
    atomic_write_json(str(ROOT/'build'/('servicing-'+args.base+'-to-'+args.new+'.json')),report)
    print(json.dumps(report))


if __name__=='__main__':main()
