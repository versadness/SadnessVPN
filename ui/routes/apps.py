"""Маршрутизация по приложениям и правилам."""
import copy
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, request

from engine.apps import POPULAR_APPS, get_running_processes
from engine.json_store import atomic_write_json
from ui import profile_state

bp = Blueprint("apps", __name__)


def init(**helpers):
    globals().update(helpers)


@bp.route("/api/apps", methods=["GET"])
def api_apps_get():
    return jsonify(profile_state.apps_config)


def _commit_apps(candidate):
    try:
        save_apps(candidate)
    except OSError:
        response = jsonify(ok=False, error="Не удалось сохранить маршрутизацию")
        response.status_code = 500
        return response
    profile_state.apps_config.clear()
    profile_state.apps_config.update(candidate)
    _broadcast({"type": "apps_config", "config": profile_state.apps_config})
    return jsonify(ok=True)


@bp.route("/api/apps/mode", methods=["POST"])
def api_apps_mode():
    data = request.get_json(silent=True) or {}
    mode = data.get("mode", "all")
    if mode not in ("all", "whitelist", "blacklist"):
        return jsonify({"ok": False, "error": "Неверный режим"})
    candidate = copy.deepcopy(profile_state.apps_config)
    candidate["mode"] = mode
    response = _commit_apps(candidate)
    if response.status_code == 200:
        _log(f"Режим маршрутизации: {mode}", "info")
    return response


@bp.route("/api/apps/add", methods=["POST"])
def api_apps_add():
    data = request.get_json(silent=True) or {}
    exe  = data.get("exe", "").strip()
    name = data.get("name", exe).strip()
    path = data.get("path", "").strip()
    if not exe:
        return jsonify({"ok": False, "error": "Нет exe"})
    if len(exe) > 260 or not name or len(name) > 256 or len(path) > 4096:
        return jsonify({"ok": False, "error": "Слишком длинное имя или путь"})
    # Те же требования, что у правила «Программа»: иначе недопустимое имя
    # (запятая, скобки, служебный процесс) ломало сборку конфигурации только
    # при подключении.
    from engine.routing_rules import normalize_rule
    try:
        exe = normalize_rule({"kind": "process", "value": exe})["value"]
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)})
    for a in profile_state.apps_config["apps"]:
        if a["exe"].lower() == exe.lower():
            return jsonify({"ok": False, "error": "Уже добавлено"})
    candidate = copy.deepcopy(profile_state.apps_config)
    candidate["apps"].append({"name": name, "exe": exe, "path": path, "enabled": True})
    return _commit_apps(candidate)


@bp.route("/api/apps/rename", methods=["POST"])
def api_apps_rename():
    data = request.get_json(silent=True) or {}
    exe = data.get("exe", "")
    name = data.get("name", "")
    if not isinstance(exe, str) or not isinstance(name, str):
        return jsonify({"ok": False, "error": "Некорректные данные правила"})
    exe = exe.strip()
    name = name.strip()
    if not exe or not name:
        return jsonify({"ok": False, "error": "Имя правила не может быть пустым"})
    if len(exe) > 260 or len(name) > 256:
        return jsonify({"ok": False, "error": "Слишком длинное имя правила"})
    candidate = copy.deepcopy(profile_state.apps_config)
    for app_rule in candidate.get("apps", []):
        if app_rule.get("exe", "").lower() == exe.lower():
            app_rule["name"] = name
            return _commit_apps(candidate)
    return jsonify({"ok": False, "error": "Правило не найдено"})


@bp.route("/api/apps/remove", methods=["POST"])
def api_apps_remove():
    data   = request.get_json(silent=True) or {}
    exe    = data.get("exe", "").strip()
    before = len(profile_state.apps_config["apps"])
    candidate = copy.deepcopy(profile_state.apps_config)
    candidate["apps"] = [a for a in candidate["apps"] if a["exe"].lower() != exe.lower()]
    if len(candidate["apps"]) == before:
        return jsonify({"ok": False, "error": "Не найдено"})
    return _commit_apps(candidate)


@bp.route("/api/apps/toggle", methods=["POST"])
def api_apps_toggle():
    data    = request.get_json(silent=True) or {}
    exe     = data.get("exe", "").strip()
    enabled = data.get("enabled", True)
    candidate = copy.deepcopy(profile_state.apps_config)
    for a in candidate["apps"]:
        if a["exe"].lower() == exe.lower():
            a["enabled"] = bool(enabled)
            return _commit_apps(candidate)
    return jsonify({"ok": False, "error": "Не найдено"})


@bp.route("/api/apps/export", methods=["POST"])
def api_apps_export():
    try:
        destination = Path.home() / "Downloads"
        destination.mkdir(parents=True, exist_ok=True)
        filename = f"SadnessVPN-routing-{datetime.now():%Y%m%d-%H%M%S-%f}.json"
        target = destination / filename
        atomic_write_json(str(target), profile_state.apps_config)
        return jsonify({"ok": True, "path": str(target)})
    except Exception as exc:
        return jsonify({"ok": False, "error": f"Не удалось экспортировать правила: {exc}"})


@bp.route("/api/apps/popular", methods=["GET"])
def api_apps_popular():
    return jsonify({"apps": POPULAR_APPS})


@bp.route("/api/apps/processes", methods=["GET"])
def api_apps_processes():
    from engine.routing_rules import BLOCKED_PROCESSES
    return jsonify({"processes": [p for p in get_running_processes() if p.lower() not in BLOCKED_PROCESSES]})


@bp.route("/api/apps/destination", methods=["POST"])
def api_app_destination():
    if _connection.state != "off":
        return jsonify(ok=False, error="Сначала отключите VPN"), 409
    data = request.get_json(silent=True) or {}
    exe, destination = data.get("exe"), data.get("destination")
    if not isinstance(exe, str) or not isinstance(destination, str):
        return jsonify(ok=False, error="Некорректное назначение"), 400
    candidate = copy.deepcopy(profile_state.apps_config)
    rule = next((a for a in candidate.get("apps", []) if a["exe"].lower() == exe.lower()), None)
    if rule is None:
        return jsonify(ok=False, error="Приложение не найдено"), 404
    rule["destination"] = destination
    from engine.app_routes import assignments
    try:
        assignments([{**rule, "enabled": True}], profile_state.groups)
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    accepted, reason = verify_with_core(candidate)
    if not accepted:
        return jsonify(ok=False, error=reason), 422
    try:
        save_apps(candidate)
    except OSError as exc:
        return jsonify(ok=False, error=str(exc)), 500
    profile_state.apps_config.clear()
    profile_state.apps_config.update(candidate)
    _broadcast({"type": "apps_config", "config": profile_state.apps_config})
    return jsonify(ok=True)


@bp.route("/api/routing/rules", methods=["GET", "POST"])
def api_routing_rules():
    if request.method == "GET":
        return jsonify(ok=True, rules=profile_state.apps_config.get("rules", []))
    if _connection.state != "off":
        return jsonify(ok=False, error="Сначала отключите VPN"), 409
    from engine.routing_rules import validate_rules
    try:
        candidate = copy.deepcopy(profile_state.apps_config)
        candidate["rules"] = validate_rules((request.get_json(silent=True) or {}).get("rules"), profile_state.groups)
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    # Проверка ядром до записи: прежняя рабочая конфигурация остаётся на диске,
    # пока Mihomo не принял новую.
    accepted, reason = verify_with_core(candidate)
    if not accepted:
        return jsonify(ok=False, error=reason), 422
    try:
        save_apps(candidate)
    except OSError as exc:
        return jsonify(ok=False, error=str(exc)), 500
    profile_state.apps_config.clear()
    profile_state.apps_config.update(candidate)
    _broadcast({"type": "apps_config", "config": profile_state.apps_config})
    return jsonify(ok=True, rules=candidate["rules"])


@bp.route("/api/routing/categories", methods=["GET"])
def api_routing_categories():
    from engine.geo_catalog import categories, category_items
    try:
        kind = request.args.get("kind")
        return jsonify(ok=True, categories=categories(kind), items=category_items(kind))
    except (ValueError, OSError):
        return jsonify(ok=False, error="Локальная база категорий недоступна"), 400
