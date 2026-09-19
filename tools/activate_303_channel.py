"""Explicitly authorized channel migration from 2.x to 3.0.3; retain rollback files."""
import base64
import getpass
import json
from pathlib import Path
import sys
import paramiko
from cryptography.hazmat.primitives.serialization import load_pem_private_key
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from engine.update_manifest import canonical,verify,verify_file
from engine.update_policy import PUBLIC_KEY_BASE64,ALLOWED_HOSTS
folder=Path('C:/Users/Sadness/Desktop/patches-for-server')
data=json.loads((folder/'update.json').read_text(encoding='utf-8'))
assert data['version']=='3.0.3' and set(data['patches'])=={'3.0.2'}
data.pop('full');data['distribution']='patch-only'
package=data['patches']['3.0.2'];verify_file(folder/package['url'].rsplit('/',1)[-1],package)
key=load_pem_private_key((Path.home()/'AppData/Local/SadnessVPN-ReleaseKeys/publisher-ed25519.pem').read_bytes(),password=None)
data['signature']=base64.b64encode(key.sign(canonical(data))).decode()
verify(data,PUBLIC_KEY_BASE64,ALLOWED_HOSTS,'beta')
config=json.loads((ROOT/'installer/vps-config.production.example.json').read_text(encoding='utf-8'))
client=paramiko.SSHClient();client.load_system_host_keys(str(Path.home()/'.ssh/known_hosts'));client.set_missing_host_key_policy(paramiko.RejectPolicy())
client.connect(config['ssh_host'],username=config['ssh_user'],password=getpass.getpass('SSH password (not saved): '),allow_agent=False,look_for_keys=False,timeout=15)
remote_code=r'''
import sys,json,os,fcntl,hashlib,urllib.request
from pathlib import Path
sys.path.insert(0,'/opt/sadness-release')
from engine.update_manifest import parse,verify,verify_file,MAX_MANIFEST
root=Path('/var/www/sadness-vpn/updates')
config=json.loads(Path('/etc/sadness-release.json').read_text())
data=parse(sys.stdin.buffer.read(MAX_MANIFEST+1))
verify(data,config['public_key_base64'],config['allowed_hosts'],'beta')
assert data['version']=='3.0.3' and set(data['patches'])=={'3.0.2'} and data['distribution']=='patch-only'
with (root/'.publish.lock').open('a') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX)
 package=data['patches']['3.0.2'];file=root/'releases/3.0.3'/package['url'].rsplit('/',1)[-1]
 assert not file.is_symlink() and file.resolve()==file.absolute()
 verify_file(file,package)
 pointer=root/'beta.json';previous=pointer.read_bytes()
 old=verify(parse(previous),config['public_key_base64'],config['allowed_hosts'],'beta')
 assert old['version'] in ('2.0.24','3.0.3'), 'Unexpected active release'
 if old==data:
  print('Already active');sys.exit(0)
 backup=root/'beta-before-3.0.3.json'
 if backup.exists():assert backup.read_bytes()==previous
 else:
  with backup.open('xb') as stream:stream.write(previous)
 temporary=root/'beta-3.0.3.new'
 assert not temporary.exists()
 with temporary.open('x',encoding='utf-8') as stream:
  json.dump(data,stream,ensure_ascii=False);stream.flush();os.fsync(stream.fileno())
 os.replace(temporary,pointer)
 try:
  with urllib.request.urlopen(config['https_base']+'/beta.json',timeout=20) as response:
   served=verify(parse(response.read(MAX_MANIFEST+1)),config['public_key_base64'],config['allowed_hosts'],'beta')
  assert served==data
  checksum=hashlib.sha256();size=0
  with urllib.request.urlopen(package['url'],timeout=30) as response:
   while chunk:=response.read(1024*1024):checksum.update(chunk);size+=len(chunk)
  assert size==package['size'] and checksum.hexdigest()==package['sha256']
 except Exception:
  temporary.write_bytes(previous);os.replace(temporary,pointer);raise
 with (root/'publication.log').open('a') as stream:
  stream.write(json.dumps({'action':'owner-authorized-major-channel-transition','from':old['version'],'to':'3.0.3','bases':['3.0.2'],'old_files_retained':True})+'\n')
 print('3.0.3 Beta active; HTTPS verified; old manifest and packages retained')
'''
try:
    import shlex
    stdin,stdout,stderr=client.exec_command('/usr/bin/python3 -c '+shlex.quote(remote_code))
    stdin.write(json.dumps(data));stdin.flush();stdin.channel.shutdown_write()
    output=stdout.read().decode();error=stderr.read().decode()
    if stdout.channel.recv_exit_status():raise RuntimeError(error)
    print(output)
finally:client.close()
