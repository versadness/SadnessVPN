"""Keep Windows Installer's registered package name during a minor upgrade.

Payload bytes are verified independently; the basename comes only from the local
machine's Installer registration, never from the remote manifest.
"""
import ctypes
from ctypes import wintypes
from pathlib import Path
import re
import shutil
from engine.update_manifest import verify_file
from engine.update_policy import PRODUCT_CODE


def registered_package_name():
    library = ctypes.WinDLL('msi', use_last_error=True)
    get_info = library.MsiSourceListGetInfoW
    get_info.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                         wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPWSTR,
                         ctypes.POINTER(wintypes.DWORD)]
    get_info.restype = wintypes.UINT
    value = ctypes.create_unicode_buffer(1024)
    length = wintypes.DWORD(len(value))
    code = get_info(PRODUCT_CODE, None, 4, 0, 'PackageName', value, ctypes.byref(length))
    if code != 0:
        raise ValueError('Не удалось определить исходное имя MSI')
    return validate_name(value.value)


def validate_name(name):
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 _.-]{0,190}\.msi', name, re.I):
        raise ValueError('Некорректное зарегистрированное имя MSI')
    if '..' in name:
        raise ValueError('Некорректное зарегистрированное имя MSI')
    return name


def stage_minor_msi(source, protected, package):
    name = registered_package_name()
    checksum = package.get('sha256', '')
    if not re.fullmatch(r'[0-9a-f]{64}', checksum):
        raise ValueError('Некорректный хеш MSI')
    verify_file(source, package)
    directory = Path(protected) / ('install-' + checksum)
    directory.mkdir(exist_ok=True)
    if directory.is_symlink() or directory.resolve() != directory.absolute():
        raise ValueError('Небезопасный каталог MSI')
    target = directory / name
    if target.is_symlink() or target.resolve() != target.absolute():
        raise ValueError('Небезопасный путь MSI')
    if not target.exists():
        with Path(source).open('rb') as src, target.open('xb') as dst:
            shutil.copyfileobj(src, dst)
    verify_file(target, package)
    return target
