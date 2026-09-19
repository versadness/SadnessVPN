"""Server-side deployment helper. Install in /opt/sadness-release with engine modules.

ROOT and trust configuration are administrator-controlled, not uploaded by clients.
One lock covers validation, publication, HTTP verification, rollback and cleanup.
"""
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.request
from datetime import datetime,timezone

from engine.update_manifest import parse,verify,verify_file,version,MAX_MANIFEST,safe_url,packages as manifest_packages

ROOT=Path('/var/www/sadness-vpn/updates')
CONFIG=Path('/etc/sadness-release.json')


def checked_child(parent,name):
    target=parent/name
    if not name or Path(name).name!=name or target.is_symlink() or target.resolve()!=target.absolute():
        raise ValueError('Unsafe release path')
    if target.parent.resolve()!=parent.resolve():raise ValueError('Path escaped release directory')
    return target


def referenced_versions(manifests):
    # Derive retained directories from signed package URLs, not only version labels.
    result=set()
    from urllib.parse import urlsplit
    for data in manifests:
        for package in manifest_packages(data):
            parts=urlsplit(package['url']).path.split('/')
            if len(parts)<3 or parts[-3]!='releases':raise ValueError('Package outside releases')
            version(parts[-2]);result.add(parts[-2])
    return result


def remove_release(child, retained=()):
    """Only flat package directories under the fixed releases root are removable."""
    parent=checked_child(ROOT,'releases')
    child=checked_child(parent,child.name)
    if child.name in retained:raise ValueError('Active release cannot be removed')
    if not re.fullmatch(r'(?:\d+\.\d+\.\d+|incoming-[0-9a-f]{32})',child.name):raise ValueError('Invalid cleanup target')
    files=list(child.iterdir())
    for path in files:
        checked_child(child,path.name)
        if not path.is_file():raise ValueError('Unexpected nested release content')
    with (ROOT/'publication.log').open('a',encoding='utf-8') as log:
        log.write(json.dumps(dict(action='delete',path=str(child.resolve()),files=[str(p.resolve()) for p in files]))+'\n')
        log.flush();os.fsync(log.fileno())
    for path in files:path.unlink()
    child.rmdir()


def activate(stage_name):
    if not re.fullmatch('incoming-[0-9a-f]{32}',stage_name):raise ValueError('Invalid staging token')
    stage=checked_child(checked_child(ROOT,'releases'),stage_name)
    try:
        return _activate(stage_name)
    except Exception:
        if stage.exists():remove_release(stage)
        raise


def cleanup_expired_uploads(now=None):
    """Uploads renew their directory lease; 24h without activity expires it.

    Called under the publication lock after successful activation. An expired
    uploader must start a new staging token; it cannot activate a removed folder.
    """
    now=time.time() if now is None else now
    releases=checked_child(ROOT,'releases');removed=[]
    for child in releases.iterdir():
        if not re.fullmatch(r'incoming-[0-9a-f]{32}',child.name):continue
        child=checked_child(releases,child.name)
        if not child.is_dir():continue
        files=list(child.iterdir())
        if any(p.is_symlink() or not p.is_file() or (p.name!='manifest.json' and p.suffix.lower() not in {'.msi','.msp'}) for p in files):continue
        latest=max([child.stat().st_mtime,*[p.stat().st_mtime for p in files]])
        if now-latest<24*60*60:continue
        remove_release(child);removed.append(child.name)
    return removed


def _activate(stage_name):
    if not re.fullmatch('incoming-[0-9a-f]{32}',stage_name):raise ValueError('Invalid staging token')
    config=json.loads(CONFIG.read_text());public=config['public_key_base64'];hosts=config['allowed_hosts']
    if ROOT.resolve()!=ROOT.absolute():raise ValueError('Updates root must not be a symlink')
    safe_url(config['https_base'],hosts)
    stage=checked_child(checked_child(ROOT,'releases'),stage_name);data=parse((stage/'manifest.json').read_bytes());channel=data.get('channel')
    verify(data,public,hosts,channel)
    releases=checked_child(ROOT,'releases');releases.mkdir(exist_ok=True)
    target=checked_child(releases,data['version'])
    if target.exists():raise ValueError('Published versions are immutable')
    packages=manifest_packages(data)
    expected={'manifest.json'}
    for package in packages:
        filename=package['url'].rsplit('/',1)[-1];expected.add(filename)
        if '/releases/'+data['version']+'/' not in package['url']:raise ValueError('Package directory mismatch')
        verify_file(checked_child(stage,filename),package)
    if {p.name for p in stage.iterdir()}!=expected:raise ValueError('Unexpected staging content')
    pointer=checked_child(ROOT,channel+'.json');previous=pointer.read_bytes() if pointer.exists() else None
    if previous:
        old=verify(parse(previous),public,hosts,channel)
        if version(data['version'])<=version(old['version']):raise ValueError('Version must advance')
        if data.get('distribution')=='patch-only':
            required=set(old.get('patches',{}))|{old['version']}
            if not required.issubset(data.get('patches',{})):
                raise ValueError('New release must preserve direct upgrades from all supported versions')
    # Verify all active channels BEFORE switching or removing any package.
    active=[]
    for c in ('stable','beta'):
        path=checked_child(ROOT,c+'.json')
        if path.exists():active.append(verify(parse(path.read_bytes()),public,hosts,c))
    retained_before=referenced_versions(active)
    stage.rename(target)
    temporary=checked_child(ROOT,channel+'.json.new')
    try:
        temporary.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
        os.replace(temporary,pointer)
        # HTTPS verifies the actual public location, before deletion of old packages.
        with urllib.request.urlopen(config['https_base'].rstrip('/')+'/'+channel+'.json',timeout=15) as response:
            served=verify(parse(response.read(MAX_MANIFEST+1)),public,hosts,channel)
        if served!=data:raise ValueError('Public manifest does not match')
        import hashlib
        for package in packages:
            checksum=hashlib.sha256();size=0
            with urllib.request.urlopen(package['url'],timeout=30) as response:
                while chunk:=response.read(1024*1024):
                    size+=len(chunk)
                    if size>package['size']:raise ValueError('Public payload too large')
                    checksum.update(chunk)
            if size!=package['size'] or checksum.hexdigest()!=package['sha256']:raise ValueError('Public payload mismatch')
    except Exception:
        if previous is None:pointer.unlink(missing_ok=True)
        else:temporary.write_bytes(previous);os.replace(temporary,pointer)
        if temporary.exists():temporary.unlink()
        if data['version'] not in retained_before:remove_release(target,retained_before)
        raise
    active=[]
    for c in ('stable','beta'):
        path=checked_child(ROOT,c+'.json')
        if path.exists():active.append(verify(parse(path.read_bytes()),public,hosts,c))
    retained=referenced_versions(active);removed=[]
    for child in releases.iterdir():
        if not re.fullmatch(r'\d+\.\d+\.\d+',child.name) or child.name in retained:continue
        checked_child(releases,child.name)
        if not child.is_dir():continue
        removed.append(child.name)
        remove_release(child,retained)
    expired=cleanup_expired_uploads()
    with (ROOT/'publication.log').open('a',encoding='utf-8') as log:
        log.write(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(),version=data['version'],channel=channel,removed=removed,expired_uploads=expired))+'\n')


if __name__=='__main__':
    import fcntl
    with (ROOT/'.publish.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX);activate(sys.argv[1])
