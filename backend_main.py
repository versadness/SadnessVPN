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

# До любых HTTPS-запросов: на Fedora, Bazzite и Arch встроенный OpenSSL
# иначе не находит корневые сертификаты (engine/linux_tls.py).
from engine import linux_tls
linux_tls.configure()

from flask import jsonify

from engine import autostart
from engine.diagnostics import journal
from engine.legacy_cleanup import remove_obsolete_files
from ui import app_state, window_control
from ui.server import app, run as run_server, shutdown_engines


# Повторный запуск не должен поднимать второе окно. Лаунчер спрашивает этот
# API и, если оболочка на связи, просто просит показать уже открытое окно —
# без запроса прав администратора и без старта второго процесса Electron.
_show_request = window_control.show_request
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
    if window_control.quit_request.is_set():
        # Updater перед восстановлением: оболочка завершает приложение целиком.
        window_control.quit_request.clear()
        return jsonify({"show": False, "quit": True})
    return jsonify({"show": shown})


@app.route("/api/shell/ready", methods=["POST"])
def shell_ready():
    """Окно загружено. По этому признаку updater решает, что новая версия запустилась."""
    window_control.shell_ready.set()
    return jsonify({"ok": True})


@app.route("/api/shell/startup", methods=["GET"])
def shell_startup():
    """Настройки запуска, которые нужны оболочке до показа окна."""
    return jsonify({"ok": True, "silent": app_state.app_settings.get("silent") is True})


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
    try:
        if autostart.ensure_current():
            journal.info("Автозапуск перенаправлен на лаунчер: %s", autostart.target_path())
    except Exception:
        journal.exception("Не удалось проверить задачу автозапуска")
    journal.info("Backend: запуск на 127.0.0.1:%s", port)
    run_server(host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
