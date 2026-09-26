"""Серверы WireGuard и AmneziaWG: импорт, выбор, удаление, пинг."""
import copy
import threading
from concurrent.futures import ThreadPoolExecutor

from flask import Blueprint, jsonify, request

from engine.ping import ping_color, wg_ping
from engine.wg_config import parse_wg_conf
from ui import profile_state
from ui.app_state import app_settings as _app_settings

bp = Blueprint("wireguard", __name__)


def init(**helpers):
    globals().update(helpers)


@bp.route("/api/wg/servers/import", methods=["POST"])
def api_wg_import():
    data = request.get_json(silent=True) or {}
    return _start_subscription_update(data=data, wireguard=True)


@bp.route("/api/wg/groups/refresh", methods=["POST"])
def api_wg_refresh_group():
    data = request.get_json(silent=True) or {}
    return _start_subscription_update(data=data, refresh=True, wireguard=True)


@bp.route("/api/wg/groups/rename", methods=["POST"])
def api_wg_rename_group():
    data = request.get_json(silent=True) or {}
    gid  = data.get("id")
    name = data.get("name", "").strip()
    if not name or len(name) > 160:
        return jsonify(ok=False, error="Название должно содержать от 1 до 160 символов"), 400
    for g in profile_state.wg_groups:
        if g["id"] == gid:
            g["name"] = name
            profile_state.save_wireguard_groups()
            _broadcast_wg_groups()
            return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Не найдено"})


@bp.route("/api/wg/groups/delete", methods=["POST"])
def api_wg_delete_group():
    data   = request.get_json(silent=True) or {}
    gid    = data.get("id")
    before = len(profile_state.wg_groups)
    profile_state.wg_groups = [g for g in profile_state.wg_groups if g["id"] != gid]
    if len(profile_state.wg_groups) == before:
        return jsonify({"ok": False, "error": "Группа не найдена"})
    if _app_settings["selected_wg_group"] == gid:
        _app_settings["selected_wg_group"] = None
        _app_settings["selected_wg_index"] = None
        _app_settings["selected_wg_group"] = None
        _app_settings["selected_wg_index"] = None
    profile_state.save_wireguard_groups()
    _save_settings(_app_settings)
    _broadcast_wg_groups()
    return jsonify({"ok": True})


@bp.route("/api/wg/servers/add", methods=["POST"])
def api_wg_add_server():
    data = request.get_json(silent=True) or {}
    conf = data.get("conf", "").strip()
    if not conf:
        return jsonify({"ok": False, "error": "Пустой конфиг"})
    # Имя файла .conf (без расширения) — понятное название сервера при импорте файлом.
    name = data.get("name")
    name = name.strip()[:160] if isinstance(name, str) else ""
    try:
        servers = parse_wg_conf(conf)
        if not servers:
            return jsonify({"ok": False, "error": "Не удалось распарсить конфиг WireGuard"})
        if name:
            for index, s in enumerate(servers):
                label = name if len(servers) == 1 else f"{name} #{index + 1}"
                s["remark"] = ("[AWG] " if s.get("is_awg") else "") + label
        mg = _ensure_wg_manual_group()
        added = 0
        is_awg_warn = False
        for s in servers:
            if s.get("is_awg"):
                is_awg_warn = True
            mg["servers"].append(s)
            added += 1
        profile_state.save_wireguard_groups()
        _app_settings["selected_wg_group"] = "manual-wg"
        _app_settings["selected_wg_index"] = len(mg["servers"]) - 1
        _app_settings["active_protocol"] = "wg"
        _save_settings(_app_settings)
        _log(f"Добавлено WG серверов: {added}", "ok")
        if is_awg_warn:
            _log(
                "AmneziaWG: нативный движок, параметры обфускации сохраняются.",
                "warn",
            )
        _broadcast_wg_groups()
        return jsonify({"ok": True, "added": added, "is_awg": is_awg_warn})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@bp.route("/api/wg/servers/select", methods=["POST"])
def api_wg_select():
    data = request.get_json(silent=True) or {}
    gid  = data.get("group_id")
    idx  = data.get("index")
    for g in profile_state.wg_groups:
        if g["id"] == gid:
            srvs = g.get("servers", [])
            if idx is not None and 0 <= idx < len(srvs):
                previous_settings = copy.deepcopy(_app_settings)
                _app_settings["selected_wg_group"] = gid
                _app_settings["selected_wg_index"] = idx
                _app_settings["active_protocol"] = "wg"
                if not _save_settings(_app_settings):
                    _app_settings.clear()
                    _app_settings.update(previous_settings)
                    return jsonify(ok=False, error="Не удалось сохранить выбранный сервер"), 500
                return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Неверный индекс"})


@bp.route("/api/wg/servers/delete", methods=["POST"])
def api_wg_delete_server():
    data = request.get_json(silent=True) or {}
    gid  = data.get("group_id")
    idx  = data.get("index")
    for g in profile_state.wg_groups:
        if g["id"] == gid:
            srvs = g.get("servers", [])
            if idx is not None and 0 <= idx < len(srvs):
                name = srvs[idx].get("remark", "")
                srvs.pop(idx)
                if _app_settings["selected_wg_group"] == gid and type(_app_settings["selected_wg_index"]) is int and _app_settings["selected_wg_index"] > idx:
                    _app_settings["selected_wg_index"] -= 1
                elif _app_settings["selected_wg_group"] == gid and _app_settings["selected_wg_index"] == idx:
                    _app_settings["selected_wg_group"] = None
                    _app_settings["selected_wg_index"] = None
                profile_state.save_wireguard_groups()
                _save_settings(_app_settings)
                _log(f"Удалён WG: {name}", "warn")
                _broadcast_wg_groups()
                return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Не найдено"})


@bp.route("/api/wg/servers/rename", methods=["POST"])
def api_wg_rename_server():
    data = request.get_json(silent=True) or {}
    gid  = data.get("group_id")
    idx  = data.get("index")
    name = data.get("name", "").strip()
    for g in profile_state.wg_groups:
        if g["id"] == gid:
            srvs = g.get("servers", [])
            if idx is not None and 0 <= idx < len(srvs) and name:
                srvs[idx]["remark"] = name
                profile_state.save_wireguard_groups()
                _broadcast_wg_groups()
                return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Ошибка"})


@bp.route("/api/wg/ping/all", methods=["POST"])
def api_wg_ping_all():
    from concurrent.futures import ThreadPoolExecutor
    generation, stop = _wg_ping_scans.begin()
    results = {}
    groups_snapshot = [
        {"id": g["id"], "servers": list(g.get("servers", []))}
        for g in profile_state.wg_groups
    ]
    def _ping_one(g, i, srv):
        if stop.is_set():
            return
        host = srv.get("endpoint", "")
        port = int(srv.get("port", 51820))
        if not host:
            return
        ms    = wg_ping(host, port)
        color = ping_color(ms)
        label = f"{ms}ms" if ms is not None else "—"
        def publish():
            results[(g["id"], i)] = ms
            _broadcast({"type": "wg_ping_result", "gid": g["id"], "index": i,
                        "sid": srv.get("ui_id", ""), "ms": ms,
                        "color": color, "label": label})

        _wg_ping_scans.run_if_current(
            generation,
            stop,
            publish,
        )
    def run():
        with ThreadPoolExecutor(max_workers=30) as ex:
            for g in groups_snapshot:
                for i, srv in enumerate(g.get("servers", [])):
                    ex.submit(_ping_one, g, i, srv)
        def finish():
            _broadcast({"type": "wg_ping_done"})

        _wg_ping_scans.run_if_current(generation, stop, finish)
    threading.Thread(target=run, daemon=True).start()
    return jsonify({"ok": True})
