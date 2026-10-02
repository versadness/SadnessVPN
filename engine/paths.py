import os
import shutil
import sys


_APP_DATA_DIRNAME = "SadnessVPN"
_MIGRATION_MARKER = ".legacy-data-migrated-v1"
_USER_DATA_FILES = (
    "apps.json",
    "servers.json",
    "servers.json.bak",
    "settings.json",
    "stats.json",
    "wg_servers.json",
)


def _base_dir() -> str:
    """Возвращает корневую папку ресурсов — работает и в dev и в PyInstaller.

    В PyInstaller --onedir (COLLECT):
      sys._MEIPASS → папка _internal/ с bin/ и шаблонами UI
      пользовательские данные хранятся отдельно в %LOCALAPPDATA%

    В PyInstaller --onefile:
      sys._MEIPASS → временная папка распаковки с ресурсами приложения

    В dev-режиме:
      sys.frozen не установлен
    """
    if getattr(sys, "frozen", False):
        # При --onedir: _MEIPASS = _internal/, туда COLLECT положил bin/ и ui/templates/.
        # При --onefile: _MEIPASS = temp, там bin/ если он добавлен в ресурсы.
        if hasattr(sys, "_MEIPASS"):
            meipass = sys._MEIPASS
            if os.path.isdir(os.path.join(meipass, "bin")):
                return meipass

        # Запасной вариант: bin/ лежит рядом с .exe (ручная раскладка portable)
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        if os.path.isdir(os.path.join(exe_dir, "bin")):
            return exe_dir

        # Крайний запасной — директория .exe
        return exe_dir

    # Режим разработки: корень проекта — две папки выше engine/paths.py
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _bin_dir() -> str:
    base = _base_dir()
    # Исходники держат двоичные файлы Linux отдельно (bin-linux/: mihomo для
    # Linux, geo-базы). В собранном пакете они уже лежат в bin/.
    if os.name != "nt" and not getattr(sys, "frozen", False):
        linux = os.path.join(base, "bin-linux")
        if os.path.isdir(linux):
            return linux
    return os.path.join(base, "bin")


def bin_path(filename: str) -> str:
    """Возвращает полный путь к файлу в папке bin/."""
    return os.path.join(_bin_dir(), filename)


def _development_data_dir() -> str:
    # Тесты подменяют каталог данных, чтобы не трогать профиль разработчика
    # в ./data. Установленная версия эту переменную не читает.
    override = os.environ.get("SADNESS_DATA_DIR")
    if override:
        return override
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def app_root_dir(environ=None, windows=None) -> str:
    """Корень данных приложения в профиле пользователя.

    Windows — %LOCALAPPDATA%\\SadnessVPN; Linux — $XDG_DATA_HOME/SadnessVPN
    (по умолчанию ~/.local/share/SadnessVPN).
    """
    env = os.environ if environ is None else environ
    windows = (os.name == "nt") if windows is None else windows
    if windows:
        local_appdata = env.get("LOCALAPPDATA")
        if not local_appdata:
            local_appdata = os.path.join(os.path.expanduser("~"), "AppData", "Local")
        return os.path.join(local_appdata, _APP_DATA_DIRNAME)
    xdg = env.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(xdg, _APP_DATA_DIRNAME)


def _frozen_data_dir(environ=None, windows=None) -> str:
    return os.path.join(app_root_dir(environ, windows), "data")


def _legacy_data_dirs() -> list:
    """Возвращает прежние каталоги data/ в порядке приоритета миграции."""
    candidates = []
    if hasattr(sys, "_MEIPASS"):
        candidates.append(os.path.join(sys._MEIPASS, "data"))

    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    candidates.append(os.path.join(exe_dir, "data"))

    result = []
    seen = set()
    for path in candidates:
        normalized = os.path.normcase(os.path.abspath(path))
        if normalized not in seen:
            seen.add(normalized)
            result.append(path)
    return result


def _migrate_legacy_data(target_dir: str, source_dirs: list) -> list:
    """Один раз копирует известные пользовательские файлы, ничего не перезаписывая."""
    marker = os.path.join(target_dir, _MIGRATION_MARKER)
    if os.path.exists(marker):
        return []

    target_normalized = os.path.normcase(os.path.abspath(target_dir))
    sources = [
        source
        for source in source_dirs
        if os.path.isdir(source)
        and os.path.normcase(os.path.abspath(source)) != target_normalized
    ]
    if not sources:
        return []

    copied = []
    migration_failed = False
    for source_dir in sources:
        for filename in _USER_DATA_FILES:
            source = os.path.join(source_dir, filename)
            target = os.path.join(target_dir, filename)
            if not os.path.isfile(source) or os.path.exists(target):
                continue
            try:
                shutil.copy2(source, target)
                copied.append(filename)
            except OSError:
                migration_failed = True

    if not migration_failed:
        try:
            with open(marker, "w", encoding="utf-8") as file:
                file.write("Legacy data migration completed.\n")
        except OSError:
            pass

    return copied


def data_dir() -> str:
    """Возвращает каталог пользовательских данных для dev и frozen-режимов."""
    if getattr(sys, "frozen", False):
        d = _frozen_data_dir()
        os.makedirs(d, exist_ok=True)
        _migrate_legacy_data(d, _legacy_data_dirs())
        return d

    d = _development_data_dir()
    os.makedirs(d, exist_ok=True)
    return d
