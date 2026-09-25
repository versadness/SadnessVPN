"""Удаление файлов, оставшихся от удалённых компонентов, при обновлении.

Windows Installer переустанавливает набор компонентов новой версии, но файл,
которого в новом пакете уже нет, может остаться лежать в каталоге установки.
После удаления ядра sing-box это означало бы 32 МБ мёртвого бинарника внутри
установленной программы.

Правила здесь намеренно жёсткие:

* удаляются только имена из OBSOLETE_FILES — фиксированного списка файлов,
  которые приложение само когда-то поставляло;
* только внутри каталога ресурсов приложения (bin/ рядом с движками);
* каталог пользовательских данных не затрагивается вообще;
* символические ссылки и точки повторной обработки пропускаются, чтобы
  удаление не ушло за пределы каталога установки;
* отказ в доступе — это запись в журнал, а не падение запуска.
"""
from __future__ import annotations

import os

from engine.diagnostics import journal
from engine.paths import bin_path

# Известные файлы приложения, снятые с поставки. Имя, а не шаблон: маска могла
# бы задеть чужой файл, случайно попавший в bin/.
OBSOLETE_FILES = (
    "sing-box.exe",  # ядро удалено целиком начиная с 3.0.11
    "xray.exe",      # никогда не поставлялось в 3.x, но встречалось в 2.x
)

# Файлы лицензий удалённых компонентов лежат в bin/licenses.
OBSOLETE_LICENSES = ("xray-MPL-2.0.txt",)


def _safe_to_remove(path: str, root: str) -> bool:
    try:
        resolved = os.path.realpath(path)
    except OSError:
        return False
    if os.path.normcase(os.path.dirname(resolved)) != os.path.normcase(os.path.realpath(root)):
        return False
    return os.path.isfile(resolved) and not os.path.islink(path)


def remove_obsolete_files() -> list[str]:
    """Удалить устаревшие файлы приложения. Вернуть список удалённых имён."""
    removed: list[str] = []
    root = os.path.dirname(bin_path("mihomo.exe"))
    if not os.path.isdir(root):
        return removed
    licenses = os.path.join(root, "licenses")
    targets = [(root, name) for name in OBSOLETE_FILES]
    targets += [(licenses, name) for name in OBSOLETE_LICENSES]
    for folder, name in targets:
        path = os.path.join(folder, name)
        if not os.path.exists(path):
            continue
        if not _safe_to_remove(path, folder):
            journal.warning("Пропущен устаревший файл вне каталога приложения: %s", name)
            continue
        try:
            os.remove(path)
            removed.append(name)
        except OSError as exc:
            journal.warning("Не удалось удалить устаревший файл %s: %s", name, exc)
    if removed:
        journal.info("Удалены устаревшие файлы прошлых версий: %s", ", ".join(removed))
    return removed
