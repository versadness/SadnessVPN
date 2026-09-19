"""Группы прокси-серверов: импорт подписок, выбор, переименование, удаление."""
import copy

from flask import Blueprint, jsonify, request

from engine.config import parse_link
from ui import profile_state
from ui.app_state import app_settings as _app_settings

bp = Blueprint("servers", __name__)

# init() кладёт помощники ui/server.py прямо в globals модуля, поэтому тела
# роутов перенесены без единой правки — так переезд не может исказить логику.
def init(**helpers):
    globals().update(helpers)


@bp.route("/api/groups", methods=["GET"])
def api_groups():
    return jsonify({"groups": _groups_for_ui(), "selGroup": _app_settings["selected_group"], "selIndex": _app_settings["selected_index"]})


@bp.route("/api/servers/import", methods=["POST"])
def api_import():
    data = request.get_json(silent=True) or {}
    return _start_subscription_update(data=data)


@bp.route("/api/groups/refresh", methods=["POST"])
def api_refresh_group():
    data = request.get_json(silent=True) or {}
    return _start_subscription_update(data=data, refresh=True)


@bp.route("/api/groups/rename", methods=["POST"])
def api_rename_group():
    data = request.get_json(silent=True) or {}
    gid  = data.get("id")
    name = data.get("name", "").strip()
    if not name or len(name) > 160:
        return jsonify(ok=False, error="Название должно содержать от 1 до 160 символов"), 400
    for g in profile_state.groups:
        if g["id"] == gid:
            g["name"] = name
            profile_state.save_proxy_groups()
            _broadcast_groups()
            return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Не найдено"})


@bp.route("/api/groups/delete", methods=["POST"])
def api_delete_group():
    data   = request.get_json(silent=True) or {}
    gid    = data.get("id")
    before = len(profile_state.groups)
    profile_state.groups = [g for g in profile_state.groups if g["id"] != gid]
    if len(profile_state.groups) == before:
        return jsonify({"ok": False, "error": "Группа не найдена"})
    if _app_settings["selected_group"] == gid:
        _app_settings["selected_group"] = None
        _app_settings["selected_index"] = None
        _app_settings["selected_group"] = None
        _app_settings["selected_index"] = None
    profile_state.save_proxy_groups()
    _save_settings(_app_settings)
    _broadcast_groups()
    return jsonify({"ok": True})


@bp.route("/api/servers/add", methods=["POST"])
def api_add_server():
    data = request.get_json(silent=True) or {}
    link = data.get("link", "").strip()
    if not link:
        return jsonify({"ok": False, "error": "Пустая ссылка"})
    try:
        parsed = parse_link(link)
        mg = _ensure_manual_group()
        mg["servers"].append(parsed)
        profile_state.save_proxy_groups()
        _app_settings["selected_group"] = "manual"
        _app_settings["selected_index"] = len(mg["servers"]) - 1
        _save_settings(_app_settings)
        proto = parsed.get("protocol", "vless").upper()
        _log(f"Добавлен [{proto}]: {parsed['remark']}", "ok")
        _broadcast_groups()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@bp.route("/api/servers/select", methods=["POST"])
def api_select():
    data = request.get_json(silent=True) or {}
    gid  = data.get("group_id")
    idx  = data.get("index")
    for g in profile_state.groups:
        if g["id"] == gid:
            srvs = g.get("servers", [])
            if idx is not None and 0 <= idx < len(srvs):
                previous_settings = copy.deepcopy(_app_settings)
                _app_settings["selected_group"] = gid
                _app_settings["selected_index"] = idx
                _app_settings["active_protocol"] = "vless"
                if not _save_settings(_app_settings):
                    _app_settings.clear()
                    _app_settings.update(previous_settings)
                    return jsonify(ok=False, error="Не удалось сохранить выбранный сервер"), 500
                return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Неверный индекс"})


@bp.route("/api/servers/delete", methods=["POST"])
def api_delete_server():
    data = request.get_json(silent=True) or {}
    gid  = data.get("group_id")
    idx  = data.get("index")
    for g in profile_state.groups:
        if g["id"] == gid:
            srvs = g.get("servers", [])
            if idx is not None and 0 <= idx < len(srvs):
                name = srvs[idx].get("remark", "")
                srvs.pop(idx)
                if _app_settings["selected_group"] == gid and type(_app_settings["selected_index"]) is int and _app_settings["selected_index"] > idx:
                    _app_settings["selected_index"] -= 1
                elif _app_settings["selected_group"] == gid and _app_settings["selected_index"] == idx:
                    _app_settings["selected_group"] = None
                    _app_settings["selected_index"] = None
                profile_state.save_proxy_groups()
                _save_settings(_app_settings)
                _log(f"Удалён: {name}", "warn")
                _broadcast_groups()
                return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Не найдено"})


@bp.route("/api/servers/rename", methods=["POST"])
def api_rename_server():
    data = request.get_json(silent=True) or {}
    gid  = data.get("group_id")
    idx  = data.get("index")
    name = data.get("name", "").strip()
    for g in profile_state.groups:
        if g["id"] == gid:
            srvs = g.get("servers", [])
            if idx is not None and 0 <= idx < len(srvs) and name:
                srvs[idx]["remark"] = name
                profile_state.save_proxy_groups()
                _broadcast_groups()
                return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Ошибка"})
