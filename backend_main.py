"""Headless-точка входа бэкенда для Electron-оболочки.

Окно, трей и управление окном переехали в Electron; Python остаётся сервером
API на 127.0.0.1:45678 до окончания переноса движков на Node.

Дополнительно регистрируется /api/shell/shutdown: оболочка обязана дать
движкам (sing-box, mihomo, AmneziaWG, zapret) корректно остановиться,
иначе после закрытия окна в системе останутся поднятый TUN и правила маршрутов.
"""
import os
import sys
import threading

from flask import jsonify

from engine.diagnostics import journal
from ui.server import app, run as run_server, shutdown_engines


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
    journal.info("Backend: запуск на 127.0.0.1:%s", port)
    run_server(host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
