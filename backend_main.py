"""Headless-точка входа бэкенда для Electron-оболочки.

Окно, трей и управление окном переехали в Electron; Python остаётся сервером
API на 127.0.0.1:45678 до окончания переноса движков на Node.

Дополнительно регистрируется /api/shell/shutdown: оболочка обязана дать
движкам (mihomo, AmneziaWG, zapret) корректно остановиться,
иначе после закрытия окна в системе останутся поднятый TUN и правила маршрутов.
"""
import os
import sys
import threading
import time

from flask import jsonify

from engine.diagnostics import journal
from engine.legacy_cleanup import remove_obsolete_files
from ui.server import app, run as run_server, shutdown_engines


# Повторный запуск не должен поднимать второе окно. Лаунчер спрашивает этот
# API и, если оболочка на связи, просто просит показать уже открытое окно —
# без запроса прав администратора и без старта второго процесса Electron.
_show_request = threading.Event()
_shell_seen_at = 0.0
_SHELL_WAIT_SECONDS = 25.0
# Оболочка перезапрашивает ожидание сразу после ответа, поэтому пропуск
# длиннее одного цикла означает, что окна больше нет.
_SHELL_ATTACHED_SECONDS = _SHELL_WAIT_SECONDS * 2


def _shell_attached():
    return (time.monotonic() - _shell_seen_at) < _SHELL_ATTACHED_SECONDS


@app.route("/api/shell/show", methods=["POST"])
def shell_show():
    """Просьба поднять уже запущенное окно. attached=false — оболочки нет."""
    attached = _shell_attached()
    if attached:
        _show_request.set()
    return jsonify({"ok": True, "attached": attached})


@app.route("/api/shell/show-wait", methods=["GET"])
def shell_show_wait():
    """Длинный опрос оболочки: держим один запрос вместо частых проверок."""
    global _shell_seen_at
    _shell_seen_at = time.monotonic()
    shown = _show_request.wait(_SHELL_WAIT_SECONDS)
    if shown:
        _show_request.clear()
    _shell_seen_at = time.monotonic()
    return jsonify({"show": shown})


@app.route("/api/shell/shutdown", methods=["POST"])
def shell_shutdown():
    try:
        shutdown_engines()
    except Exception as exc:
        journal.exception("Остановка движков не удалась")
        return jsonify({"ok": False, "error": str(exc)}), 500
    journal.info("Backend: движки остановлены, завершение процесса")
    # Flask уже отдал ответ — выходим следом, не дожидаясь сборки мусора.
    threading.Timer(0.25, lambda: os._exit(0)).start()
    return jsonify({"ok": True})


def main():
    port = 45678
    for index, argument in enumerate(sys.argv):
        if argument == "--port" and index + 1 < len(sys.argv):
            port = int(sys.argv[index + 1])
    # Обновление поверх прежней версии не должно оставлять бинарники ядра,
    # которого в приложении больше нет.
    try:
        remove_obsolete_files()
    except Exception:
        journal.exception("Очистка устаревших файлов не удалась")
    journal.info("Backend: запуск на 127.0.0.1:%s", port)
    run_server(host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
