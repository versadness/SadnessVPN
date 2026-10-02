"""Права ядра Mihomo на Linux: пароль администратора — один раз.

Для TUN ядру нужна возможность CAP_NET_ADMIN, а само приложение (Electron и
Python) работает от обычного пользователя. Поэтому права выдаются не
приложению, а одному файлу ядра — через файловые возможности (setcap):

  1. Пакеты .deb/.rpm/pacman выдают их при установке (пароль спрашивает
     пакетный менеджер) — тогда при подключении пароль не нужен вовсе.
  2. AppImage (в том числе на Bazzite, где система только для чтения) при
     первом подключении один раз просит пароль через pkexec: копия ядра
     ставится в /usr/local/libexec/sadness-vpn/ от root и получает права.
     Файл принадлежит root, поэтому подменить его без пароля нельзя, а
     /usr/local не монтируется с nosuid (на nosuid-разделах возможности
     файлов игнорируются — так бывает с /home).
  3. Пароль понадобится снова, только если обновление приложения заменит
     само ядро: у новой версии другой файл, и права нужно выдать ему.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import struct
import subprocess
import tempfile

INSTALL_DIR = "/usr/local/libexec/sadness-vpn"
INSTALLED_CORE = INSTALL_DIR + "/mihomo"
CAPABILITIES = "cap_net_admin,cap_net_bind_service,cap_net_raw+ep"
CAP_NET_ADMIN = 12
_SECURE_PATH = "/usr/sbin:/usr/bin:/sbin:/bin"


class CoreSetupError(RuntimeError):
    """Права ядру выдать не удалось — текст показывается пользователю."""


def has_net_admin(path: str) -> bool:
    """У файла есть действующая возможность CAP_NET_ADMIN (security.capability)."""
    try:
        raw = os.getxattr(path, "security.capability")
    except (OSError, AttributeError):
        return False
    if len(raw) < 8:
        return False
    magic, permitted = struct.unpack_from("<II", raw, 0)
    effective = bool(magic & 0x000001)  # VFS_CAP_FLAGS_EFFECTIVE
    return effective and bool(permitted & (1 << CAP_NET_ADMIN))


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _installed_matches(bundled: str) -> bool:
    try:
        info = os.stat(INSTALLED_CORE)
    except OSError:
        return False
    return (info.st_uid == 0 and has_net_admin(INSTALLED_CORE)
            and _sha256(INSTALLED_CORE) == _sha256(bundled))


def privileged_core(bundled: str) -> str | None:
    """Ядро, которое уже может поднять TUN, без запроса пароля; иначе None."""
    if has_net_admin(bundled):
        return bundled  # права выданы при установке пакета
    if os.geteuid() == 0:
        return bundled  # приложение запущено от root
    if _installed_matches(bundled):
        return INSTALLED_CORE
    return None


def install_privileged_core(bundled: str, log=lambda message, tag: None, runner=subprocess.run) -> str:
    """Один раз выдать ядру права через pkexec. Возвращает путь к ядру."""
    pkexec = shutil.which("pkexec", path=_SECURE_PATH)
    setcap = shutil.which("setcap", path=_SECURE_PATH)
    manual = (f"sudo install -D -m 0755 -o root -g root \"{bundled}\" {INSTALLED_CORE} && "
              f"sudo setcap {CAPABILITIES} {INSTALLED_CORE}")
    if not setcap:
        raise CoreSetupError("В системе нет утилиты setcap (пакет libcap / libcap2-bin). "
                             "Установите его и повторите подключение.")
    if not pkexec:
        raise CoreSetupError("Нет pkexec (polkit), чтобы запросить пароль администратора. "
                             "Выдайте права ядру вручную один раз:\n" + manual)
    # Файлы внутри смонтированного AppImage недоступны root (FUSE без allow_other),
    # поэтому ядро сначала копируется во временную папку, читаемую root.
    staging = tempfile.mkdtemp(prefix="sadness-vpn-core-")
    try:
        staged = os.path.join(staging, "mihomo")
        shutil.copy2(bundled, staged)
        os.chmod(staging, 0o755)
        os.chmod(staged, 0o755)
        script = (
            'set -e; '
            f'install -d -m 0755 "{INSTALL_DIR}"; '
            f'install -m 0755 -o root -g root "$1" "{INSTALLED_CORE}.new"; '
            f'mv -f "{INSTALLED_CORE}.new" "{INSTALLED_CORE}"; '
            f'"{setcap}" {CAPABILITIES} "{INSTALLED_CORE}"'
        )
        log("Для VPN нужны права администратора — Linux один раз спросит пароль. "
            "После этого VPN будет подключаться без пароля.", "info")
        try:
            result = runner([pkexec, "/bin/sh", "-c", script, "sadness-vpn-core", staged],
                            capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired:
            raise CoreSetupError("Пароль администратора не введён за 5 минут — подключение отменено.") from None
        if result.returncode in (126, 127) and not os.path.exists(INSTALLED_CORE):
            raise CoreSetupError("Запрос пароля администратора отменён — без прав VPN не может "
                                 "создать сетевой интерфейс. Повторите подключение.")
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip().splitlines()[-1:] or [""]
            raise CoreSetupError("Не удалось выдать права ядру VPN"
                                 + (f": {detail[0][:200]}" if detail[0] else "")
                                 + ". Вручную: " + manual)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    if not has_net_admin(INSTALLED_CORE):
        raise CoreSetupError("Права ядру выданы, но система их не применила "
                             "(файловые возможности не поддерживаются). Вручную: " + manual)
    log("Права ядру VPN выданы; дальше пароль не понадобится", "ok")
    return INSTALLED_CORE


def ready_core(bundled: str, log=lambda message, tag: None, runner=subprocess.run) -> str:
    """Путь к ядру, готовому поднять TUN; при необходимости — один запрос пароля."""
    return privileged_core(bundled) or install_privileged_core(bundled, log, runner)
