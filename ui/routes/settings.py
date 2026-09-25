"""Порты прокси, пользовательские настройки, параметры туннеля и пинга."""
import secrets
import string
from types import SimpleNamespace

from flask import Blueprint, jsonify, request

from engine import autostart
from ui import app_state

bp = Blueprint("settings", __name__)

# tunnel_busy() отвечает, поднят ли сейчас туннель: сетевые параметры нельзя
# менять на живом соединении, и это знание принадлежит ui/server.py.
deps = SimpleNamespace(broadcast=None, log=None, tunnel_busy=None)


def init(broadcast, log, tunnel_busy):
    deps.broadcast = broadcast
    deps.log = log
    deps.tunnel_busy = tunnel_busy


@bp.route("/api/settings", methods=["POST"])
def api_settings():
    settings = app_state.app_settings
    data = request.get_json(silent=True) or {}
    try:
        socks_port = app_state.port_number(data.get("socks", settings["socks"]))
        http_port = app_state.port_number(data.get("http", settings["http"]))
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)})
    if socks_port == http_port:
        return jsonify({"ok": False, "error": "Порты SOCKS и HTTP должны отличаться"})
    if socks_port in app_state.RESERVED_LOCAL_PORTS or http_port in app_state.RESERVED_LOCAL_PORTS:
        return jsonify({"ok": False, "error": "Этот порт зарезервирован SadnessVPN"})
    previous = (settings["socks"], settings["http"])
    settings["socks"], settings["http"] = socks_port, http_port
    if not app_state.save_settings(settings):
        settings["socks"], settings["http"] = previous
        return jsonify({"ok": False, "error": "Не удалось сохранить порты"})
    return jsonify({"ok": True})


@bp.route("/api/app-settings", methods=["POST"])
def api_app_settings():
    settings = app_state.app_settings
    data = request.get_json(silent=True) or {}
    key, value = data.get("key"), data.get("value")
    if key not in app_state.USER_APP_SETTING_KEYS:
        return jsonify({"ok": False, "error": "Неизвестная настройка"})
    try:
        value = app_state.normalize_app_setting(key, value)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)})
    if key == "lan" and value and not (
        settings.get("socks5_auth")
        and settings.get("socks5_user")
        and settings.get("socks5_pass")
    ):
        return jsonify({
            "ok": False,
            "error": "Сначала включите SOCKS5-аутентификацию и задайте логин с паролем",
        })
    previous = settings.get(key)
    settings[key] = value
    if key == "startup":
        try:
            if value:
                deps.log(f"Автозапуск включён (планировщик задач): {autostart.enable()}", "ok")
            else:
                autostart.disable()
                deps.log("Автозапуск отключён", "info")
        except Exception as exc:
            settings[key] = previous
            return jsonify({"ok": False, "error": str(exc)})
    if not app_state.save_settings(settings):
        settings[key] = previous
        return jsonify({"ok": False, "error": "Не удалось сохранить настройку"})
    deps.broadcast({
        "type": "app_settings_updated",
        "settings": {item: settings.get(item) for item in app_state.USER_APP_SETTING_KEYS},
    })
    return jsonify({"ok": True})


@bp.route("/api/tunnel-settings", methods=["GET"])
def api_tunnel_settings_get():
    return jsonify({k: app_state.app_settings.get(k) for k in app_state.TUNNEL_KEYS})


@bp.route("/api/tunnel-settings", methods=["POST"])
def api_tunnel_settings_post():
    settings = app_state.app_settings
    data = request.get_json(silent=True) or {}
    # Сортировка серверов ничего не меняет в сети, её правят и на живом туннеле.
    if deps.tunnel_busy() and set(data) != {"server_sort"}:
        return jsonify({"ok": False, "error": "Отключите туннель перед изменением сетевых настроек"}), 409
    try:
        updates = {
            key: app_state.normalize_tunnel_setting(key, value)
            for key, value in data.items()
            if key in app_state.TUNNEL_KEYS
        }
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)})
    candidate = {**settings, **updates}
    if candidate.get("lan") and not (
        candidate.get("socks5_auth")
        and candidate.get("socks5_user")
        and candidate.get("socks5_pass")
    ):
        return jsonify({
            "ok": False,
            "error": "LAN-прокси требует SOCKS5-аутентификацию, логин и пароль",
        })
    if candidate.get("dns_preset") == "custom" and not str(candidate.get("custom_dns") or "").strip():
        # Иначе пустой «Свой DNS» молча подменялся бы Cloudflare + Google.
        return jsonify({"ok": False, "error": "Для пресета «Свой DNS» укажите хотя бы один адрес"})
    previous = {key: settings.get(key) for key in updates}
    settings.update(updates)
    if not app_state.save_settings(settings):
        settings.update(previous)
        return jsonify({"ok": False, "error": "Не удалось сохранить настройки туннеля"})
    deps.broadcast({"type": "settings_updated", "settings": {
        k: settings.get(k) for k in app_state.TUNNEL_KEYS
    }})
    return jsonify({"ok": True})


@bp.route("/api/socks5/regenerate", methods=["POST"])
def api_socks5_regen():
    settings = app_state.app_settings
    chars = string.ascii_letters + string.digits
    user = "vpn_" + "".join(secrets.choice(chars) for _ in range(8))
    password = "".join(secrets.choice(chars) for _ in range(16))
    previous = (settings.get("socks5_user", ""), settings.get("socks5_pass", ""))
    settings["socks5_user"], settings["socks5_pass"] = user, password
    if not app_state.save_settings(settings):
        settings["socks5_user"], settings["socks5_pass"] = previous
        return jsonify({"ok": False, "error": "Не удалось сохранить данные SOCKS5"})
    deps.broadcast({"type": "socks5_creds", "user": user, "pass": password})
    deps.broadcast({"type": "settings_updated",
                    "settings": {"socks5_user": user, "socks5_pass": password}})
    return jsonify({"ok": True, "user": user, "pass": password})


@bp.route("/api/ping-settings", methods=["POST"])
def api_ping_settings():
    settings = app_state.app_settings
    data = request.get_json(silent=True) or {}
    try:
        updates = {
            key: app_state.normalize_tunnel_setting(key, data[key])
            for key in ("ping_type", "ping_url", "ping_timeout")
            if key in data
        }
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)})
    previous = {key: settings.get(key) for key in updates}
    settings.update(updates)
    if not app_state.save_settings(settings):
        settings.update(previous)
        return jsonify({"ok": False, "error": "Не удалось сохранить настройки пинга"})
    return jsonify({"ok": True})
