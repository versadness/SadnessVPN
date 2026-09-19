"""Explicit local full-MSI upgrade test; preserves and hashes the user profile."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine.json_store import atomic_write_json
from engine.update_manifest import version
from installer.msi_source import stage_minor_msi
from installer.updater_main import installed_version, protected_directory


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    parser.add_argument('--new', required=True)
    parser.add_argument('--reapply', action='store_true', help='Explicitly test reinstalling an unpublished local build of the same version')
    args = parser.parse_args()
    if version(args.new) < version(args.base) or (version(args.new) == version(args.base) and not args.reapply):
        raise ValueError('Target must be newer than base')
    if installed_version() != args.base:
        raise RuntimeError('Unexpected installed version')
    installed = Path(os.environ['ProgramFiles']) / 'Sadness VPN'
    for process in psutil.process_iter(['name', 'exe', 'cmdline']):
        if (process.info['name'] or '').lower() == 'msiexec.exe':
            # The Windows Installer service remains idle after a successful run.
            # Do not confuse its /V host with a second installer client.
            arguments = [a.lower() for a in (process.info['cmdline'] or [])[1:]]
            if arguments != ['/v']:
                raise RuntimeError('Another Windows Installer client exists')
        if process.info['exe'] and Path(process.info['exe']).is_relative_to(installed):
            raise RuntimeError('Close the installed client first')
    msi = ROOT / 'dist' / f'SadnessVPN-{args.new}-Setup-x64.msi'
    checksum = digest(msi)
    folder = ROOT / 'build' / f'full-msi-test-{args.base}-to-{args.new}'
    folder.mkdir(exist_ok=False)
    profile = Path(os.environ['LOCALAPPDATA']) / 'SadnessVPN' / 'data'
    names = ['settings.json', 'servers.json', 'wg_servers.json', 'apps.json', 'stats.json']
    before = {n: digest(profile / n) for n in names if (profile / n).is_file()}
    backup = folder / 'profile-backup'
    backup.mkdir()
    for name in before:
        shutil.copy2(profile / name, backup / name)
    report = dict(base=args.base, version=args.new, msi_sha256=checksum,
                  profile_before=before, ok=False)
    output = folder / 'result.json'
    atomic_write_json(str(output), report)
    staged = stage_minor_msi(msi, protected_directory(),
                             dict(sha256=checksum, size=msi.stat().st_size))
    result = subprocess.run(['msiexec.exe', '/i', str(staged), 'REINSTALL=ALL',
                             'REINSTALLMODE=vomus', '/qn', '/norestart', '/L*v',
                             str(folder / 'install.log')], creationflags=0x08000000)
    after = {n: digest(profile / n) for n in names if (profile / n).is_file()}
    actual = installed_version()
    report.update(exit_code=result.returncode, installed_version=actual,
                  profile_preserved=before == after,
                  ok=result.returncode in (0, 3010) and actual == args.new and before == after)
    atomic_write_json(str(output), report)
    print(json.dumps({k: report[k] for k in ('base', 'version', 'exit_code', 'installed_version', 'profile_preserved', 'ok')}))
    if not report['ok']:
        raise RuntimeError('MSI upgrade failed; see local install.log')


if __name__ == '__main__':
    main()
