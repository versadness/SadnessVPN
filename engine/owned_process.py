"""Учёт процессов, которые приложение запустило само.

Если бэкенд падает или его завершают принудительно, дочерние mihomo.exe и
winws.exe продолжают работать: Windows не завершает их вместе с родителем.
Такой mihomo держит TUN и порты, и следующий запуск отказывал «порт занят»,
а winws считался чужим и блокировал Zapret.

Здесь записывается PID, время создания и путь к исполняемому файлу. При
следующем запуске останавливается только процесс, совпавший по всем трём
признакам, — чужой mihomo или winws с тем же именем так не пострадает.
"""
from __future__ import annotations

import json
import os

from engine.json_store import atomic_write_json
from engine.paths import data_dir


def _record_path(name: str) -> str:
    return os.path.join(data_dir(), "runtime", "owned", f"{name}.json")


def _same_path(first: str, second: str) -> bool:
    # realpath: на Linux процесс сообщает настоящий путь, а записан мог быть
    # путь через символическую ссылку (например, python из venv).
    return os.path.normcase(os.path.realpath(first)) == os.path.normcase(os.path.realpath(second))


def remember(name: str, pid: int) -> None:
    try:
        import psutil
        process = psutil.Process(pid)
        record = {"pid": pid, "created": process.create_time(), "exe": process.exe()}
        atomic_write_json(_record_path(name), record)
    except Exception:
        # Учёт — страховка на случай сбоя, он не должен мешать запуску.
        pass


def forget(name: str) -> None:
    try:
        os.remove(_record_path(name))
    except OSError:
        pass


def reap(name: str, expected_exe) -> bool:
    """Остановить процесс, оставшийся от прошлого запуска. True — был остановлен.

    expected_exe — путь или несколько путей: на Linux ядро запускается либо из
    пакета, либо из копии с правами в /usr/local/libexec.
    """
    expected = [expected_exe] if isinstance(expected_exe, str) else list(expected_exe)
    path = _record_path(name)
    try:
        with open(path, encoding="utf-8") as handle:
            record = json.load(handle)
        pid, created, exe = int(record["pid"]), float(record["created"]), str(record["exe"])
    except (OSError, ValueError, KeyError, TypeError):
        forget(name)
        return False
    try:
        import psutil
        process = psutil.Process(pid)
        matches = (abs(process.create_time() - created) < 1.0
                   and _same_path(process.exe(), exe)
                   and any(_same_path(exe, item) for item in expected))
        if not matches:
            return False
        process.terminate()
        try:
            process.wait(timeout=5)
        except psutil.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        return True
    except Exception:
        return False
    finally:
        forget(name)
