import hashlib
import os
import platform
import socket
import subprocess
import uuid

def _get_smbios_uuid() -> str:
    """Возвращает настоящий аппаратный UUID материнской платы."""
    try:
        r = subprocess.run(
            ["wmic", "csproduct", "get", "uuid"],
            capture_output=True, text=True, timeout=2, creationflags=0x08000000
        )
        for line in r.stdout.splitlines():
            line = line.strip()
            if line and line.lower() != "uuid":
                return line
    except Exception:
        return ""

def _get_machine_guid() -> str:
    """Читает MachineGuid из реестра Windows."""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography")
        guid, _ = winreg.QueryValueEx(key, "MachineGuid")
        winreg.CloseKey(key)
        return guid
    except Exception:
        return ""

def generate_hwid() -> str:
    # Сначала пробуем железный UUID (к которому скорее всего привязана подписка)
    guid = _get_smbios_uuid() or _get_machine_guid()
    if guid:
        return guid

    # Фолбэк
    try:
        mac = uuid.getnode()
        if not (mac >> 40 & 1):
            return ":".join(f"{(mac >> (5 - i) * 8) & 0xff:02x}" for i in range(6))
    except Exception:
        pass
        
    return str(uuid.uuid1())