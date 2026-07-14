import os
import sys


def _base_dir() -> str:
    """Возвращает корневую папку проекта — работает и в dev и в PyInstaller.

    В PyInstaller --onedir (COLLECT):
      sys.frozen = True
      sys._MEIPASS → папка _internal/ (туда COLLECT кладёт bin/, data/, ui/)
      sys.executable → SadnessVPN.exe

    В PyInstaller --onefile:
      sys.frozen = True
      sys._MEIPASS → временная папка распаковки (там тоже будет bin/ если добавить в datas)

    В dev-режиме:
      sys.frozen не установлен
    """
    if getattr(sys, "frozen", False):
        # При --onedir: _MEIPASS = _internal/, туда COLLECT положил bin/, data/, ui/templates/
        # При --onefile: _MEIPASS = temp, там bin/ если добавлен в datas
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


def bin_path(filename: str) -> str:
    """Возвращает полный путь к файлу в папке bin/."""
    return os.path.join(_base_dir(), "bin", filename)


def data_dir() -> str:
    """Возвращает полный путь к папке data/ (создаёт если не существует)."""
    d = os.path.join(_base_dir(), "data")
    os.makedirs(d, exist_ok=True)
    return d