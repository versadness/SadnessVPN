"""Install the existing local Electron candidate, preserving profile evidence."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import psutil
import msilib
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from installer.updater_main import installed_version,protected_directory
from installer.msi_source import stage_minor_msi
from installer.recovery_cache import cache_full
from engine.json_store import atomic_write_json

def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

installed=Path(os.environ['ProgramFiles'])/'Sadness VPN'
for process in psutil.process_iter(['exe']):
    if process.info['exe'] and Path(process.info['exe']).is_relative_to(installed):
        raise RuntimeError('Close the running application before installation')
assert installed_version()=='2.0.24','Unexpected installed version'
msi=ROOT/'dist/SadnessVPN-2.0.25-Setup-x64.msi'
database=msilib.OpenDatabase(str(msi),0)
view=database.OpenView("SELECT `Value` FROM `Property` WHERE `Property`='ProductVersion'")
view.Execute(None);assert view.Fetch().GetString(1)=='2.0.25'
view.Close();del view,database
profile=Path(os.environ['LOCALAPPDATA'])/'SadnessVPN/data'
names=['settings.json','servers.json','wg_servers.json','apps.json','stats.json']
before={name:digest(profile/name) for name in names if (profile/name).is_file()}
protected=protected_directory()
cache_full(ROOT/'dist/SadnessVPN-2.0.24-Setup-x64.msi',protected,'2.0.24')
package=dict(sha256=digest(msi),size=msi.stat().st_size)
staged=stage_minor_msi(msi,protected,package)
log=ROOT/'build/install-electron-2.0.25.log'
result=subprocess.run(['msiexec.exe','/i',str(staged),'REINSTALL=ALL','REINSTALLMODE=vomus','/qn','/norestart','/L*v',str(log)],creationflags=0x08000000)
after={name:digest(profile/name) for name in names if (profile/name).is_file()}
report=dict(exit_code=result.returncode,version=installed_version(),profile_preserved=before==after,msi_sha256=package['sha256'])
atomic_write_json(str(ROOT/'build/install-electron-2.0.25-result.json'),report)
print(json.dumps(report))
if result.returncode not in (0,3010) or report['version']!='2.0.25' or before!=after:raise RuntimeError('Installation verification failed')
