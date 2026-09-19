"""Owner-authorized publication of the supplied 3.0.3 -> 3.0.4 patch only."""
import base64,getpass,json,shlex,sys,uuid
from pathlib import Path
import paramiko
from cryptography.hazmat.primitives.serialization import load_pem_private_key
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from engine.update_manifest import verify_file,verify,canonical
from engine.update_policy import PUBLIC_KEY_BASE64,ALLOWED_HOSTS
folder=Path('C:/Users/Sadness/Desktop/SadnessVPN-3.0.4/patches-for-server')
data=json.loads((folder/'update.json').read_text(encoding='utf-8'))
assert data['version']=='3.0.4' and set(data['patches'])=={'3.0.3'}
data.pop('full');data['distribution']='patch-only'
data['notes'].append('Теперь номер лаунчера подставляется при сборке из того же источника, что и версия приложения, чтобы журнал запуска не вводил в заблуждение при диагностике.')
package=data['patches']['3.0.3'];name=package['url'].rsplit('/',1)[-1]
assert name=='SadnessVPN-3.0.3-to-3.0.4-Beta-Update-x64.msp'
verify_file(folder/name,package)
evidence=json.loads((ROOT/'build/admin-patch-test-3.0.3-to-3.0.4/result.json').read_text())
assert evidence['ok'] is True and evidence['patch_sha256']==package['sha256'] and evidence['mismatches']==[] and evidence['files']==675
key=load_pem_private_key((Path.home()/'AppData/Local/SadnessVPN-ReleaseKeys/publisher-ed25519.pem').read_bytes(),password=None)
data['signature']=base64.b64encode(key.sign(canonical(data))).decode()
verify(data,PUBLIC_KEY_BASE64,ALLOWED_HOSTS,'beta')
client=paramiko.SSHClient();client.load_system_host_keys(str(Path.home()/'.ssh/known_hosts'));client.set_missing_host_key_policy(paramiko.RejectPolicy())
client.connect('193.233.75.219',username='root',password=getpass.getpass('SSH password (not saved): '),allow_agent=False,look_for_keys=False,timeout=15)
stage='incoming-'+uuid.uuid4().hex
remote=r'''
import json,sys,os,fcntl,urllib.request,hashlib
from pathlib import Path
sys.path.insert(0,'/opt/sadness-release')
from activate_release import checked_child
from engine.update_manifest import parse,verify,verify_file,MAX_MANIFEST
root=Path('/var/www/sadness-vpn/updates');config=json.loads(Path('/etc/sadness-release.json').read_text())
with (root/'.publish.lock').open('a') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX)
 releases=checked_child(root,'releases');stage=checked_child(releases,sys.argv[1])
 data=verify(parse((stage/'manifest.json').read_bytes()),config['public_key_base64'],config['allowed_hosts'],'beta')
 assert data['version']=='3.0.4' and set(data['patches'])=={'3.0.3'} and data['distribution']=='patch-only'
 p=data['patches']['3.0.3'];name=p['url'].rsplit('/',1)[-1]
 assert p['url']==config['https_base']+'/releases/3.0.4/'+name
 assert {f.name for f in stage.iterdir()}=={'manifest.json',name}
 verify_file(checked_child(stage,name),p)
 pointer=checked_child(root,'beta.json');previous=pointer.read_bytes()
 old=verify(parse(previous),config['public_key_base64'],config['allowed_hosts'],'beta');assert old['version']=='3.0.3'
 backup=checked_child(root,'beta-before-3.0.4.json')
 if backup.exists():assert backup.read_bytes()==previous
 else:backup.write_bytes(previous)
 target=checked_child(releases,'3.0.4');assert not target.exists()
 stage.rename(target)
 temporary=checked_child(root,'beta-3.0.4.new');assert not temporary.exists()
 with temporary.open('x',encoding='utf-8') as stream:
  json.dump(data,stream,ensure_ascii=False);stream.flush();os.fsync(stream.fileno())
 os.replace(temporary,pointer)
 try:
  with urllib.request.urlopen(config['https_base']+'/beta.json',timeout=20) as response:
   assert verify(parse(response.read(MAX_MANIFEST+1)),config['public_key_base64'],config['allowed_hosts'],'beta')==data
  checksum=hashlib.sha256();size=0
  with urllib.request.urlopen(p['url'],timeout=30) as response:
   while chunk:=response.read(1024*1024):checksum.update(chunk);size+=len(chunk)
  assert size==p['size'] and checksum.hexdigest()==p['sha256']
 except Exception:
  temporary.write_bytes(previous);os.replace(temporary,pointer);raise
 with (root/'publication.log').open('a') as stream:
  stream.write(json.dumps({'action':'owner-authorized-base-restriction','from':'3.0.3','to':'3.0.4','bases':['3.0.3'],'old_files_retained':True})+'\n')
 print('3.0.4 Beta active; signature and HTTPS payload verified')
'''
try:
    sftp=client.open_sftp();directory='/var/www/sadness-vpn/updates/releases/'+stage;sftp.mkdir(directory,mode=0o755)
    last=[-1]
    def progress(sent,total):
        percent=int(sent*100/total)//10*10
        if percent!=last[0]:print(f'Upload {percent}%',flush=True);last[0]=percent
    sftp.put(str(folder/name),directory+'/'+name,callback=progress)
    sftp.chmod(directory+'/'+name,0o644)
    with sftp.open(directory+'/manifest.json','w') as stream:stream.write(json.dumps(data,ensure_ascii=False))
    sftp.chmod(directory+'/manifest.json',0o644)
    stdin,stdout,stderr=client.exec_command('/usr/bin/python3 -c '+shlex.quote(remote)+' '+stage)
    output=stdout.read().decode();error=stderr.read().decode()
    if stdout.channel.recv_exit_status():raise RuntimeError(error)
    print(output)
finally:client.close()
