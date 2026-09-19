"""Install only the isolated updates publication helper; never touch VPN services."""
import getpass
import json
from pathlib import Path
import stat
import paramiko

ROOT=Path(__file__).resolve().parents[1]
config=json.loads((ROOT/'installer/vps-config.production.example.json').read_text(encoding='utf-8'))
client=paramiko.SSHClient()
client.load_system_host_keys(str(Path.home()/'.ssh/known_hosts'))
client.set_missing_host_key_policy(paramiko.RejectPolicy())
client.connect(config['ssh_host'],username=config['ssh_user'],password=getpass.getpass('SSH password (not saved): '),
               allow_agent=False,look_for_keys=False,timeout=15)
try:
    sftp=client.open_sftp()
    for directory in ('/opt/sadness-release','/opt/sadness-release/engine'):
        try:info=sftp.lstat(directory)
        except FileNotFoundError:sftp.mkdir(directory,mode=0o755)
        else:
            if not stat.S_ISDIR(info.st_mode):raise ValueError('Unexpected helper path')
    payloads={
        '/opt/sadness-release/activate_release.py':(ROOT/'tools/activate_release.py').read_bytes(),
        '/opt/sadness-release/engine/update_manifest.py':(ROOT/'engine/update_manifest.py').read_bytes(),
        '/opt/sadness-release/engine/__init__.py':b'',
        '/etc/sadness-release.json':json.dumps({key:config[key] for key in ('https_base','allowed_hosts','public_key_base64')}).encode(),
    }
    for target,content in payloads.items():
        try:sftp.lstat(target)
        except FileNotFoundError:pass
        else:raise ValueError('Helper already exists; review instead of overwriting: '+target)
        with sftp.open(target,'wx') as stream:stream.write(content)
        sftp.chmod(target,0o644)
    stdin,stdout,stderr=client.exec_command('cd /opt/sadness-release && /usr/bin/python3 -c "import activate_release; import cryptography; print(\'Publisher ready\')"')
    output=stdout.read().decode();error=stderr.read().decode()
    if stdout.channel.recv_exit_status():raise RuntimeError(error)
    print(output.strip())
finally:client.close()
