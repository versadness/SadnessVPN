"""Группы прокси-серверов: импорт подписок, выбор, переименование, удаление."""
import copy

from flask import Blueprint, jsonify, request

from engine.config import parse_link
from engine.core_config import ensure_supported
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


@bp.route("/api/groups/refresh-all", methods=["POST"])
def api_refresh_all_groups():
    return _start_subscription_refresh_all()


@bp.route("/api/groups/rename", methods=["POST"])
def api_rename_group():
    data = request.get_json(silent=True) or {}
    gid  = data.get("id")
    name = data.get("name", "").strip()
    if not name or len(name) > 160:
        return jsonify(ok=False, error="Название должно содержать от 1 до 160 символов"), 400
    for g in profile_state.groups:
        if g["id"] == gid:
            previous = g["name"]
            g["name"] = name
            try:
                profile_state.save_proxy_groups()
            except OSError:
                g["name"] = previous
                return jsonify(ok=False, error="Не удалось сохранить название группы"), 500
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
    profile_state.save_proxy_groups()
    _save_settings(_app_settings)
    _broadcast_groups()
    # Маршруты, указывавшие на серверы удалённой группы, переводим на
    # основной VPN — иначе подключение упадёт при следующей попытке.
    _repair_saved_routes("удаление группы серверов")
    return jsonify({"ok": True})


@bp.route("/api/servers/add", methods=["POST"])
def api_add_server():
    data = request.get_json(silent=True) or {}
    link = data.get("link", "").strip()
    if not link:
        return jsonify({"ok": False, "error": "Пустая ссылка"})
    try:
        parsed = parse_link(link)
        # Та же проверка, что при импорте подписки: неподдерживаемый сервер
        # отклоняется сразу, а не ошибкой при подключении.
        ensure_supported(parsed)
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
    """Выбрать сервер. Пока VPN работает через Mihomo — смена на лету, без
    переподключения: ядро переключает группу manual (engine/failover.py)."""
    data = request.get_json(silent=True) or {}
    gid  = data.get("group_id")
    idx  = data.get("index")
    for g in profile_state.groups:
        if g["id"] == gid:
            srvs = g.get("servers", [])
            if idx is not None and 0 <= idx < len(srvs):
                state = _live_switch_state()
                if state not in ("off", "live"):
                    return jsonify(ok=False, error=state), 409
                previous_settings = copy.deepcopy(_app_settings)
                _app_settings["selected_group"] = gid
                _app_settings["selected_index"] = idx
                _app_settings["active_protocol"] = "vless"
                if not _save_settings(_app_settings):
                    _app_settings.clear()
                    _app_settings.update(previous_settings)
                    return jsonify(ok=False, error="Не удалось сохранить выбранный сервер"), 500
                # Persist the selection before changing the real traffic path.
                # A disk failure must not leave the UI on the previous server
                # while the core is already forwarding through the new one.
                if state == "live":
                    ok, error = _switch_live_server(srvs[idx])
                    if not ok:
                        _app_settings.clear()
                        _app_settings.update(previous_settings)
                        if not _save_settings(_app_settings):
                            return jsonify(ok=False, error=error + ". Не удалось восстановить сохранённый выбор сервера"), 500
                        return jsonify(ok=False, error=error), 409
                return jsonify({"ok": True, "live": state == "live"})
    return jsonify({"ok": False, "error": "Неверный индекс"})


@bp.route("/api/servers/probe", methods=["POST"])
def api_probe_server():
    """Проверить один сервер настоящим запросом через outbound Mihomo.

    Открытый порт — не подтверждение работы транспорта, поэтому состояния
    «порт доступен» и «соединение подтверждено» здесь разные. Проверяемый
    сервер поднимается изолированно: запрос не может уйти через основной
    сервер или напрямую.
    """
    from engine.server_probe import probe

    data = request.get_json(silent=True) or {}
    gid, index = data.get("group_id"), data.get("index")
    if not isinstance(index, int):
        return jsonify(ok=False, error="Не указан сервер"), 400
    for group in profile_state.groups:
        if group.get("id") != gid:
            continue
        servers = group.get("servers", [])
        if not 0 <= index < len(servers):
            break
        try:
            result = probe(servers[index])
        except OSError as exc:
            return jsonify(ok=False, error=f"Проверка не запустилась: {exc}"), 500
        _log(f"Проверка сервера «{servers[index].get('remark', '')}»: {result['label']}",
             "ok" if result["state"] == "connected" else "warn")
        return jsonify(ok=True, **result)
    return jsonify(ok=False, error="Сервер не найден"), 404


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
                # Маршруты на этот сервер переводятся на основной VPN сразу,
                # а не при следующем подключении.
                _repair_saved_routes("удаление сервера")
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
