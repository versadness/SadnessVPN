"""Upload the supplied 3.0.3 MSP without replacing the active 2.x channel."""
import getpass
import hashlib
import json
from pathlib import Path
import stat
import sys
import urllib.request
import paramiko
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from engine.update_manifest import verify_file
folder=Path('C:/Users/Sadness/Desktop/patches-for-server')
data=json.loads((folder/'update.json').read_text(encoding='utf-8'))
assert data['version']=='3.0.3' and set(data['patches'])=={'3.0.2'}
package=data['patches']['3.0.2'];name='SadnessVPN-3.0.2-to-3.0.3-Beta-Update-x64.msp'
source=folder/name;verify_file(source,package)
evidence=json.loads((ROOT/'build/admin-patch-test-3.0.2-to-3.0.3/result.json').read_text(encoding='utf-8'))
assert evidence['ok'] is True and evidence['patch_sha256']==package['sha256'] and evidence['mismatches']==[]
config=json.loads((ROOT/'installer/vps-config.production.example.json').read_text(encoding='utf-8'))
client=paramiko.SSHClient();client.load_system_host_keys(str(Path.home()/'.ssh/known_hosts'))
client.set_missing_host_key_policy(paramiko.RejectPolicy())
client.connect(config['ssh_host'],username=config['ssh_user'],password=getpass.getpass('SSH password (not saved): '),allow_agent=False,look_for_keys=False,timeout=15)
directory='/var/www/sadness-vpn/updates/releases/3.0.3'
try:
    sftp=client.open_sftp()
    try:info=sftp.lstat(directory)
    except FileNotFoundError:sftp.mkdir(directory,mode=0o755)
    else:
        if not stat.S_ISDIR(info.st_mode):raise ValueError('Unsafe release path')
    target=directory+'/'+name
    try:sftp.lstat(target)
    except FileNotFoundError:
        temporary=target+'.upload'
        try:sftp.lstat(temporary)
        except FileNotFoundError:pass
        else:raise ValueError('Existing incomplete upload; inspect before retrying')
        sftp.put(str(source),temporary)
        sftp.chmod(temporary,0o644)
        with sftp.open(temporary,'rb') as stream:
            checksum=hashlib.sha256()
            while chunk:=stream.read(1024*1024):checksum.update(chunk)
        if checksum.hexdigest()!=package['sha256']:raise ValueError('Remote hash mismatch')
        sftp.rename(temporary,target)
finally:client.close()
with urllib.request.urlopen(package['url'],timeout=30) as response:
    checksum=hashlib.sha256();size=0
    while chunk:=response.read(1024*1024):checksum.update(chunk);size+=len(chunk)
assert checksum.hexdigest()==package['sha256'] and size==package['size']
print(json.dumps(dict(url=package['url'],bytes=size,verified=True,channel_changed=False)))
