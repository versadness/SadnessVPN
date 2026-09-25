"""Роуты Telegram WS Proxy (вкладка Zapret). Движок — engine/tg_proxy.py."""
import os
import threading
from types import SimpleNamespace

from flask import Blueprint, jsonify, request

from engine import tg_proxy
from ui import app_state

bp = Blueprint("tg_proxy", __name__)

deps = SimpleNamespace(manager=None, broadcast=None, log=None, reserved_ports=lambda: {})
_busy = threading.Lock()


def init(manager, broadcast, log, reserved_ports=None):
    deps.manager = manager
    deps.broadcast = broadcast
    deps.log = log
    if reserved_ports is not None:
        deps.reserved_ports = reserved_ports


def _config():
    stored = app_state.app_settings.get("tg_proxy")
    config = tg_proxy.normalize_stored(stored)
    if config != stored:
        # Секрет создаётся один раз: иначе ссылка менялась бы при каждом запросе.
        _save(config)
    return config


def status():
    config = _config()
    running = deps.manager.running
    return {
        "state": "on" if running else "off",
        "running": running,
        "host": tg_proxy.HOST,
        # Пока прокси работает, показываем порт, на котором он реально слушает.
        "port": deps.manager.port if running else config["port"],
        "secret": config["secret"],
        "link": tg_proxy.link({**config, "port": deps.manager.port if running else config["port"]}),
        "enabled": config["enabled"],
    }


def _save(config) -> bool:
    settings = app_state.app_settings
    previous = settings.get("tg_proxy")
    settings["tg_proxy"] = config
    if not app_state.save_settings(settings):
        settings["tg_proxy"] = previous
        return False
    return True


def _publish():
    payload = status()
    deps.broadcast({"type": "tgproxy_status", **payload})
    return payload


def _restart_if_running(config):
    if not deps.manager.running:
        return True, None
    deps.manager.stop(quiet=True)
    return deps.manager.start(config)


def handle_exit(_error):
    """Прокси упал сам: интерфейс должен увидеть выключенное состояние."""
    _publish()


def autostart():
    """Поднять прокси при запуске приложения, если пользователь его оставил включённым."""
    config = _config()
    if not config["enabled"]:
        return
    ok, error = deps.manager.start(config)
    if not ok:
        deps.log(f"Telegram-прокси не запущен: {error}", "warn")
    _publish()


@bp.route("/api/tgproxy", methods=["GET"])
def api_tgproxy_status():
    return jsonify(ok=True, **status())


@bp.route("/api/tgproxy/start", methods=["POST"])
def api_tgproxy_start():
    data = request.get_json(silent=True) or {}
    if not _busy.acquire(blocking=False):
        return jsonify(ok=False, error="Прокси уже запускается"), 409
    try:
        try:
            config = tg_proxy.normalize(
                {**_config(), "port": data.get("port", _config()["port"]), "enabled": True},
                reserved=deps.reserved_ports(),
            )
        except tg_proxy.TgProxyError as exc:
            return jsonify(ok=False, error=str(exc)), 400
        # Повторный запуск с другим портом перезапускает уже работающий прокси.
        if deps.manager.running:
            deps.manager.stop(quiet=True)
        ok, error = deps.manager.start(config)
        if not ok:
            return jsonify(ok=False, error=error, **_publish()), 409
        if not _save(config):
            deps.log("Telegram-прокси: не удалось сохранить настройку", "warn")
        return jsonify(ok=True, **_publish())
    finally:
        _busy.release()


@bp.route("/api/tgproxy/stop", methods=["POST"])
def api_tgproxy_stop():
    with _busy:
        deps.manager.stop()
        _save({**_config(), "enabled": False})
        return jsonify(ok=True, **_publish())


@bp.route("/api/tgproxy/secret", methods=["POST"])
def api_tgproxy_secret():
    """Новый секрет. Старая ссылка в Telegram после этого перестаёт работать."""
    with _busy:
        config = {**_config(), "secret": tg_proxy.new_secret()}
        if not _save(config):
            return jsonify(ok=False, error="Не удалось сохранить новый ключ"), 500
        ok, error = _restart_if_running(config)
        if not ok:
            return jsonify(ok=False, error=error, **_publish()), 409
        return jsonify(ok=True, **_publish())


@bp.route("/api/tgproxy/open", methods=["POST"])
def api_tgproxy_open():
    """Передать ссылку tg://proxy установленному Telegram Desktop."""
    if not deps.manager.running:
        return jsonify(ok=False, error="Сначала запустите прокси"), 409
    try:
        os.startfile(status()["link"])  # ссылка собрана из проверенных чисел и hex
    except (AttributeError, OSError):
        return jsonify(ok=False, error="Telegram Desktop не найден — добавьте прокси вручную"), 404
    return jsonify(ok=True)
