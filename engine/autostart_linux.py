"""Автозапуск на Linux: файл .desktop в ~/.config/autostart (стандарт XDG).

Работает в KDE (в том числе Bazzite), GNOME, Xfce и других окружениях без
прав администратора. Запускается само приложение (Electron) с --autostart —
как и на Windows, иначе не поднимаются окно, трей и автоподключение.

Путь к приложению передаёт Electron в переменной SADNESS_APP_EXEC: для AppImage
это сам файл .AppImage (его можно переложить — тогда ensure_current обновит
запись), для пакетов — исполняемый файл в /opt.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

AUTOSTART_ARGUMENT = "--autostart"
FILE_NAME = "sadness-vpn.desktop"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _autostart_file(environ=None) -> Path:
    env = os.environ if environ is None else environ
    config = env.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return Path(config) / "autostart" / FILE_NAME


def _command(environ=None) -> list[str]:
    env = os.environ if environ is None else environ
    executable = env.get("SADNESS_APP_EXEC", "")
    if executable:
        return [executable, AUTOSTART_ARGUMENT]
    if getattr(sys, "frozen", False):
        raise RuntimeError("Приложение не сообщило свой путь (SADNESS_APP_EXEC) — "
                           "перезапустите Sadness VPN и повторите")
    electron = _PROJECT_ROOT / "node_modules" / "electron" / "dist" / "electron"
    return [str(electron), str(_PROJECT_ROOT), AUTOSTART_ARGUMENT]


def _quote(argument: str) -> str:
    """Аргумент строки Exec по спецификации Desktop Entry."""
    if argument and not any(ch in argument for ch in ' \t\n"\'\\$`<>~|&;*?#()'):
        return argument
    escaped = argument.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$")
    return f'"{escaped}"'


def desktop_entry(environ=None) -> str:
    exec_line = " ".join(_quote(item) for item in _command(environ))
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Sadness VPN\n"
        "Comment=Sadness Private Network\n"
        f"Exec={exec_line}\n"
        "Icon=sadness-vpn\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
        "X-KDE-autostart-after=panel\n"
    )


def target_path() -> str:
    return _command()[0]


def enable() -> str:
    path = _autostart_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(desktop_entry(), encoding="utf-8")
    os.replace(temporary, path)
    return target_path()


def disable():
    try:
        _autostart_file().unlink()
    except FileNotFoundError:
        pass


def enabled() -> bool:
    path = _autostart_file()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    lowered = text.lower()
    return "hidden=true" not in lowered and "x-gnome-autostart-enabled=false" not in lowered


def ensure_current() -> bool:
    """Обновить запись, если приложение переехало (например, AppImage переложили)."""
    if not enabled():
        return False
    try:
        current = _autostart_file().read_text(encoding="utf-8")
        expected = desktop_entry()
    except (OSError, RuntimeError):
        return False
    if current == expected:
        return False
    enable()
    return True
