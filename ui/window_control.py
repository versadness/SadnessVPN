"""Связь бэкенда с окном Electron-оболочки.

Окном владеет Electron. Он сообщает о загрузке интерфейса через
/api/shell/ready (по этому признаку updater решает, что новая версия
запустилась) и держит длинный опрос /api/shell/show-wait, через который
бэкенд просит показать окно или завершить приложение.
"""
import threading

shell_ready = threading.Event()
# Просьба поднять окно; будит длинный опрос оболочки.
show_request = threading.Event()
# Просьба полностью завершить приложение (updater перед восстановлением).
quit_request = threading.Event()


def ui_ready() -> bool:
    return shell_ready.is_set()


def request_quit() -> None:
    quit_request.set()
    show_request.set()
