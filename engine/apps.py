"""
engine/apps.py — управление списком приложений для маршрутизации
Оптимизировано: Добавлена нативная поддержка psutil для моментального считывания процессов.
"""
import json
import os
import subprocess

from engine.paths import data_dir

_DATA_DIR  = data_dir()
_APPS_PATH = os.path.join(_DATA_DIR, "apps.json")

_DEFAULT = {
    "mode": "all",
    "apps": []
}

POPULAR_APPS = [
    {"name": "Google Chrome",       "exe": "chrome.exe"},
    {"name": "Mozilla Firefox",     "exe": "firefox.exe"},
    {"name": "Microsoft Edge",      "exe": "msedge.exe"},
    {"name": "Opera",               "exe": "opera.exe"},
    {"name": "Brave Browser",       "exe": "brave.exe"},
    {"name": "Telegram",            "exe": "Telegram.exe"},
    {"name": "Discord",             "exe": "Discord.exe"},
    {"name": "Spotify",             "exe": "Spotify.exe"},
    {"name": "Steam",               "exe": "steam.exe"},
    {"name": "Epic Games Launcher", "exe": "EpicGamesLauncher.exe"},
    {"name": "qBittorrent",         "exe": "qbittorrent.exe"},
    {"name": "uTorrent",            "exe": "utorrent.exe"},
    {"name": "Skype",               "exe": "Skype.exe"},
    {"name": "Zoom",                "exe": "Zoom.exe"},
    {"name": "WhatsApp",            "exe": "WhatsApp.exe"},
    {"name": "VK",                  "exe": "VK.exe"},
    {"name": "Python",              "exe": "python.exe"},
    {"name": "Node.js",             "exe": "node.exe"},
    {"name": "curl",                "exe": "curl.exe"},
    {"name": "git",                 "exe": "git.exe"},
]

def load_apps() -> dict:
    try:
        with open(_APPS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return {**_DEFAULT, **data}
    except Exception:
        return dict(_DEFAULT)

def save_apps(data: dict):
    with open(_APPS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_running_processes() -> list:
    """Возвращает список уникальных .exe процессов которые сейчас запущены"""
    try:
        import psutil
        procs = set()
        for p in psutil.process_iter(['name']):
            try:
                name = p.info['name']
                if name and name.lower().endswith('.exe'):
                    procs.add(name)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        return sorted(list(procs))
    except ImportError:
        # Fallback на tasklist если psutil не установлен
        try:
            result = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            seen = set()
            procs = []
            for line in result.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = line.split('","')
                if parts:
                    exe = parts[0].strip('"')
                    if exe and exe not in seen and exe.endswith(".exe"):
                        seen.add(exe)
                        procs.append(exe)
            return sorted(procs)
        except Exception:
            return []

def get_installed_apps() -> list:
    """Возвращает список установленных приложений из реестра Windows"""
    apps = []
    try:
        import winreg
        keys = [
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        ]
        for key_path in keys:
            try:
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path)
                i = 0
                while True:
                    try:
                        sub_name = winreg.EnumKey(key, i)
                        sub_key  = winreg.OpenKey(key, sub_name)
                        try:
                            name = winreg.QueryValueEx(sub_key, "DisplayName")[0]
                            loc  = winreg.QueryValueEx(sub_key, "InstallLocation")[0]
                            if name and loc and os.path.isdir(loc):
                                for f in os.listdir(loc):
                                    if f.endswith(".exe"):
                                        apps.append({
                                            "name": name,
                                            "exe":  f,
                                            "path": os.path.join(loc, f),
                                        })
                                        break
                        except Exception:
                            pass
                        winreg.CloseKey(sub_key)
                        i += 1
                    except OSError:
                        break
                winreg.CloseKey(key)
            except Exception:
                pass
    except Exception:
        pass
    return apps