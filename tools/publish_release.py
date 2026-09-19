"""Publish only explicitly approved, hash-bound candidates over authenticated SFTP.

Developer dependency: paramiko. SSH keys and signing keys are external files.
Passwords are prompted only, never saved. No host-key bypass or post-test rebuild.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import posixpath
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.release_candidate import digest
from engine.update_manifest import canonical,verify,safe_url,version,packages
from cryptography.hazmat.primitives.serialization import load_pem_private_key,Encoding,PublicFormat


def prepare(candidate, config, signing_key):
    report=json.loads((candidate/'test-report.json').read_text(encoding='utf-8'))
    technical_only=report.get('publication_approval')=='owner_authorized_technical_only'
    if report.get('ready') is not True or (not report.get('manual') and not technical_only) or not report.get('automated'):
        raise ValueError('Micro-test and owner approval required')
    if any(v is not True for group in ('manual','automated') for v in report.get(group,{}).values()):
        raise ValueError('Micro-test is incomplete or failed')
    data=json.loads((candidate/'update.json').read_text(encoding='utf-8'));version(data['version'])
    if report.get('version')!=data['version']:raise ValueError('Report version mismatch')
    if technical_only:
        required=('unit_tests','singbox_dns_config','singbox_dns_interception','mihomo_six_rules',
                  'parallel_routes','subscription_api','ui_regression','msi_msp_roundtrip')
        if any(report['automated'].get(name) is not True for name in required):
            raise ValueError('Technical publication checks are incomplete')
        for base_version in data.get('patches',{}):
            if not any(report['automated'].get(prefix+base_version) is True
                       for prefix in ('direct_patch_from_','patch_image_from_')):
                raise ValueError('Patch has no servicing evidence: '+base_version)
    for filename,checksum in report['artifacts'].items():
        if Path(filename).name!=filename or digest(candidate/filename)!=checksum:raise ValueError('Candidate changed after testing')
    if 'trust-policy.json' not in report['artifacts']:raise ValueError('Candidate trust policy was not included in testing')
    trust=json.loads((candidate/'trust-policy.json').read_text(encoding='utf-8'))
    if not trust.get('public_key_base64') or trust['public_key_base64']!=config['public_key_base64']:
        raise ValueError('Candidate publisher key does not match publication configuration')
    if trust.get('manifest_base','').rstrip('/')!=config['https_base'].rstrip('/') or set(trust.get('allowed_hosts',[]))!=set(config['allowed_hosts']):
        raise ValueError('Candidate update endpoint differs from publication configuration; rebuild and retest')
    base=config['https_base'].rstrip('/');hosts=config['allowed_hosts']
    safe_url(base,hosts)
    if config.get('patch_only') is True:
        data.pop('full',None);data['distribution']='patch-only'
        if sum(p['size'] for p in packages(data))>100*1024*1024:
            raise ValueError('Патчи превышают бюджет 100 МиБ; публикация отменена')
    for package in packages(data):
        filename=package['url'].rsplit('/',1)[-1]
        if report['artifacts'].get(filename)!=package['sha256']:raise ValueError('Manifest package not covered by test report')
        package['url']=base+'/releases/'+data['version']+'/'+filename
    key=load_pem_private_key(signing_key.read_bytes(),password=None)
    public=base64.b64encode(key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)).decode('ascii')
    if public!=config['public_key_base64']:raise ValueError('Signing key does not match the built client trust policy')
    data['signature']=base64.b64encode(key.sign(canonical(data))).decode('ascii')
    verify(data,public,hosts,data['channel'])
    return data


def main():
    p=argparse.ArgumentParser();p.add_argument('--candidate',type=Path,required=True);p.add_argument('--config',type=Path,required=True)
    p.add_argument('--signing-key',type=Path,required=True);p.add_argument('--publish',action='store_true')
    args=p.parse_args();config=json.loads(args.config.read_text(encoding='utf-8'))
    manifest=prepare(args.candidate,config,args.signing_key)
    if not args.publish:print('Candidate verified. No upload. Use --publish after owner approval.');return
    import paramiko
    client=paramiko.SSHClient();client.load_system_host_keys(str(Path.home()/'.ssh/known_hosts'));client.set_missing_host_key_policy(paramiko.RejectPolicy())
    password=None
    if config.get('ssh_auth')=='password':
        import getpass
        password=getpass.getpass('SSH password (not saved): ')
    client.connect(config['ssh_host'],username=config.get('ssh_user','sadness-release'),key_filename=config.get('ssh_key'),password=password,allow_agent=password is None,look_for_keys=password is None,timeout=15)
    password=None
    try:
        sftp=client.open_sftp()
        # Pipelined file writes have outstanding request IDs on this channel.
        # Metadata requests on it can consume their replies and deadlock after
        # ~100 packets. Renew staging leases on a separate SFTP channel.
        lease_sftp=client.open_sftp()
        root='/var/www/sadness-vpn/updates';stage='incoming-'+uuid.uuid4().hex
        directory=root+'/releases/'+stage;sftp.mkdir(directory)
        upload_names=[p['url'].rsplit('/',1)[-1] for p in packages(manifest)]
        try:
            import time
            last_lease=[0.0]
            def renew_lease(sent,total):
                now=time.time()
                if now-last_lease[0]>=30:
                    lease_sftp.utime(directory,(now,now));last_lease[0]=now
            for filename in upload_names:
                sftp.put(str(args.candidate/filename),directory+'/'+filename,callback=renew_lease)
                print('Uploaded '+filename,flush=True)
            with sftp.open(directory+'/manifest.json','w') as stream:stream.write(json.dumps(manifest,ensure_ascii=False))
        except Exception:
            # Only known filenames in this invocation's generated incoming folder.
            # If SSH is down cleanup may fail; report failure without touching active releases.
            for filename in [*upload_names,'manifest.json']:
                try:sftp.remove(directory+'/'+filename)
                except OSError:pass
            try:sftp.rmdir(directory)
            except OSError:pass
            raise
        # Fixed helper and a generated alphanumeric token only; no user-provided command.
        stdin,stdout,stderr=client.exec_command('/usr/bin/python3 /opt/sadness-release/activate_release.py '+stage)
        code=stdout.channel.recv_exit_status()
        if code:
            detail=stderr.read(8192).decode('utf-8',errors='replace')
            raise RuntimeError('Server verification/activation failed: '+detail)
        print('Release activated; unreferenced previous release files cleaned by server helper.')
    finally:client.close()


if __name__=='__main__':main()
