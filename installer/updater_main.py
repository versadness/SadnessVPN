"""Fixed-purpose updater, packaged separately so the client runtime can be serviced.

No command or path is accepted from the manifest or command line.
The elevated helper independently re-verifies the embedded publisher key.
"""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import winreg

from engine import update_policy as policy
from engine.update_manifest import parse,verify,select_package,verify_file
from engine.json_store import atomic_write_json
from installer.recovery_cache import cache_full,recovery_package
from installer.msi_source import stage_minor_msi
from engine.app_meta import APP_VERSION

CREATE_NO_WINDOW=0x08000000


def record_result(path, outcome):
    """Persist attempts once in the helper, never once per client restart."""
    previous = {}
    try:
        previous = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(previous, dict): previous = {}
    except (OSError, ValueError): pass
    count = previous.get('failure_count', 0)
    if type(count) is not int or count < 0: count = 0
    same_version = bool(outcome.get('version')) and previous.get('version') == outcome['version']
    outcome = {**outcome, 'failure_count': 0 if outcome.get('ok') else (count + 1 if same_version else 1),
               'completed_at': int(time.time())}
    atomic_write_json(str(path), outcome)
    return outcome


def installed_version():
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,'SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\'+policy.PRODUCT_CODE,0,winreg.KEY_READ|winreg.KEY_WOW64_64KEY) as key:
        return winreg.QueryValueEx(key,'DisplayVersion')[0]


def protected_directory():
    import win32file
    import win32con
    import win32security
    import pywintypes
    root=Path(os.environ['ProgramData'])/'SadnessVPN-Update'
    descriptor=win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        'O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)',1)
    attrs=pywintypes.SECURITY_ATTRIBUTES();attrs.SECURITY_DESCRIPTOR=descriptor
    try:win32file.CreateDirectory(str(root),attrs)
    except pywintypes.error as exc:
        if exc.winerror!=183:raise
    if root.resolve()!=root.absolute() or root.is_symlink():raise ValueError('Unsafe updater directory')
    sd=win32security.GetNamedSecurityInfo(str(root),win32security.SE_FILE_OBJECT,
        win32security.OWNER_SECURITY_INFORMATION|win32security.DACL_SECURITY_INFORMATION)
    trusted={'S-1-5-18','S-1-5-32-544'}
    if win32security.ConvertSidToStringSid(sd.GetSecurityDescriptorOwner()) not in trusted:raise ValueError('Untrusted updater directory owner')
    acl=sd.GetSecurityDescriptorDacl()
    if acl is None:raise ValueError('Missing updater directory ACL')
    for index in range(acl.GetAceCount()):
        ace=acl.GetAce(index)
        if win32security.ConvertSidToStringSid(ace[-1]) not in trusted:raise ValueError('Unexpected updater directory permissions')
    return root


def main():
    import psutil
    if len(sys.argv)>1:
        if len(sys.argv)!=3 or sys.argv[1]!='--cache-installed' or not ctypes.windll.shell32.IsUserAnAdmin():return 1
        try:
            cache_full(Path(sys.argv[2]),protected_directory(),APP_VERSION)
            return 0
        except Exception:return 1
    if not ctypes.windll.shell32.IsUserAnAdmin():return 1
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_wchar_p]
    kernel.CreateMutexW.restype=ctypes.c_void_p
    kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    mutex=kernel.CreateMutexW(None,True,'Local\\SadnessVPN.Update')
    if not mutex:return 1
    if ctypes.get_last_error()==183:
        kernel.CloseHandle(mutex);return 1
    root=Path(os.environ['ProgramFiles'])/'Sadness VPN'
    directory=Path(os.environ['LOCALAPPDATA'])/'SadnessVPN'/'data'/'updates'
    directory.mkdir(parents=True,exist_ok=True)
    protected=protected_directory()
    result_path=protected/'result.json'
    attempted_version=None
    try:
        raw=(directory/'manifest.json').read_bytes()
        data=parse(raw)
        verify(data,policy.PUBLIC_KEY_BASE64,policy.ALLOWED_HOSTS,data.get('channel'))
        attempted_version=data['version']
        previous=installed_version();package=select_package(data,previous)
        if package is None:raise ValueError('Нет совместимого обновления')
        extension='.msp' if data.get('patches',{}).get(previous)==package else '.msi'
        rollback_package=None
        if extension=='.msi':
            # Full MSI rollback needs the previous full payload locally; the VPS
            # may already have removed it. Never promise recovery without it.
            rollback_package=recovery_package(protected,previous)
        if data.get('full'):
            full_source=directory/(data['full']['sha256']+'.msi')
            verify_file(full_source,data['full'])
            cache_full(full_source,protected,data['version'])
        source=directory/(package['sha256']+extension)
        verify_file(source,package)
        # Stage in an administrator-only directory before asking MSI to open it.
        target=protected/(package['sha256']+extension)
        if not target.exists():
            import shutil
            with source.open('rb') as src,target.open('xb') as dst:shutil.copyfileobj(src,dst)
        if target.is_symlink() or target.resolve()!=target.absolute():raise ValueError('Unsafe package path')
        verify_file(target,package)
        if extension=='.msi':target=stage_minor_msi(target,protected,package)
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            running=[]
            for proc in psutil.process_iter(['exe']):
                if proc.info['exe'] and Path(proc.info['exe']).is_relative_to(root):running.append(proc)
            if not running:break
            time.sleep(.3)
        else:raise ValueError('Приложение не завершилось; установка отменена')
        command=['msiexec.exe','/p' if extension=='.msp' else '/i',str(target),'/qn','/norestart','/L*v',str(protected/'installer.log')]
        if extension=='.msi':command+=['REINSTALL=ALL','REINSTALLMODE=vomus']
        code=subprocess.run(command,creationflags=CREATE_NO_WINDOW).returncode
        if code not in (0,3010) or installed_version()!=data['version']:raise ValueError('Установка завершилась с ошибкой '+str(code))
        subprocess.Popen([str(root/'SadnessVPN.exe'),'--show'],creationflags=CREATE_NO_WINDOW)
        ready=False
        for _ in range(90):
            try:
                with urllib.request.urlopen('http://127.0.0.1:45678/api/updates/state',timeout=1) as response:
                    state=json.load(response)
                    if state.get('version')==data['version'] and state.get('ui_ready'):ready=True;break
            except Exception:pass
            time.sleep(1)
        if not ready:
            # Request graceful cleanup before Windows Installer rollback.
            try:
                req=urllib.request.Request('http://127.0.0.1:45678/api/updates/close-for-recovery',data=b'{}',headers={'Content-Type':'application/json'})
                urllib.request.urlopen(req,timeout=5).close()
            except Exception:pass
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                if not any(p.info['exe'] and Path(p.info['exe']).is_relative_to(root) for p in psutil.process_iter(['exe'])):break
                time.sleep(.5)
            else:raise ValueError('Не удалось завершить новую версию для восстановления')
            if extension=='.msp':
                import msilib
                db=msilib.OpenDatabase(str(target),32)
                revision=db.GetSummaryInformation(0).GetProperty(9)
                if isinstance(revision,bytes):revision=revision.decode('ascii')
                patch_id=revision.split(';')[0]
                import re
                if not re.fullmatch(r'\{[A-Fa-f0-9-]{36}\}',patch_id):raise ValueError('Неизвестный идентификатор патча')
                rollback=['msiexec.exe','/package',policy.PRODUCT_CODE,'/uninstall',patch_id]
            else:
                # Windows Installer cannot reliably downgrade a minor-updated
                # component graph in place. Preserve the validated MSI cache and
                # user profile, remove the failed product, then restore that MSI.
                remove_code=subprocess.run(['msiexec.exe','/x',policy.PRODUCT_CODE,'/qn','/norestart',
                    '/L*v',str(protected/'rollback-remove.log')],creationflags=CREATE_NO_WINDOW).returncode
                if remove_code not in (0,3010):raise ValueError('Не удалось подготовить восстановление приложения')
                rollback=['msiexec.exe','/i',str(rollback_package)]
            rollback+=['/qn','/norestart','/L*v',str(protected/'rollback.log')]
            rollback_code=subprocess.run(rollback,creationflags=CREATE_NO_WINDOW).returncode
            if rollback_code not in (0,3010) or installed_version()!=previous:raise ValueError('Восстановление требует ручной проверки')
            subprocess.Popen([str(root/'SadnessVPN.exe'),'--show'],creationflags=CREATE_NO_WINDOW)
        outcome=dict(ok=ready,version=data['version'],previous=previous,reboot_required=code==3010,
                     message='Обновление установлено' if ready else 'Новая версия не запустилась. Предыдущая версия восстановлена.')
        record_result(result_path,outcome)
        return 0 if ready else 2
    except Exception as exc:
        # Only our own fixed messages are reported; never raw request URLs.
        message=str(exc) if isinstance(exc,ValueError) else 'Обновление не завершено. Подробности в installer.log.'
        record_result(result_path,dict(ok=False,version=attempted_version,message=message))
        if (root/'SadnessVPN.exe').is_file():
            subprocess.Popen([str(root/'SadnessVPN.exe'),'--show'],creationflags=CREATE_NO_WINDOW)
        return 1
    finally:kernel.CloseHandle(mutex)


if __name__=='__main__':sys.exit(main())
