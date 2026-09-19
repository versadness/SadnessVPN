"""Use the app-local Fixed Version runtime; never install it system-wide."""
from pathlib import Path
import os
import subprocess
import sys

from engine.runtime_validation import PE_MACHINE_AMD64, read_pe_machine


RUNTIME_VERSION = "152.0.4191.62"


def validate_webview_runtime(directory):
    root = Path(directory).resolve()
    for name in ("msedgewebview2.exe", "msedge.dll", "icudtl.dat", "resources.pak"):
        if not root.joinpath(name).is_file():
            raise RuntimeError("Отсутствует компонент интерфейса: " + name + ". Выполните восстановление через установщик Sadness VPN.")
    if not root.joinpath("locales", "en-US.pak").is_file():
        raise RuntimeError("Не найдены языковые ресурсы интерфейса. Выполните восстановление через установщик Sadness VPN.")
    if read_pe_machine(str(root / "msedgewebview2.exe")) != PE_MACHINE_AMD64:
        raise RuntimeError("Для этой сборки нужен встроенный WebView2 x64.")
    return root


def prepare_webview_runtime(base_dir, settings, *, frozen=None, windows_build=None):
    """Pin the renderer before pywebview imports its Windows backend.

    Win10 requires AppContainer read/execute access to this app-owned folder.
    No browser install, registry edits, or sandbox-disabling flags are used.
    """
    root = Path(base_dir).resolve() / "bin" / "webview2"
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if not root.exists() and not frozen:
        return None  # Source development can still use an installed runtime.
    root = validate_webview_runtime(root)
    if str(root).startswith("\\\\"):
        raise RuntimeError("Распакуйте приложение на локальный диск: сетевые папки не поддерживаются.")
    if windows_build is None:
        windows_build = sys.getwindowsversion().build if sys.platform == "win32" else 0
    if 0 < windows_build < 22000:
        command = str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "icacls.exe")
        result = subprocess.run(
            [command, str(root), "/grant", "*S-1-15-2-2:(OI)(CI)(RX)", "*S-1-15-2-1:(OI)(CI)(RX)"],
            capture_output=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode:
            raise RuntimeError("Windows не дала интерфейсу доступ к его файлам. Распакуйте приложение в новую локальную папку.")
    settings["WEBVIEW2_RUNTIME_PATH"] = str(root)
    return root
