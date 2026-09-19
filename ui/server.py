"""
ui/server.py — Sadness VPN Flask backend
"""
import ctypes
import ctypes.wintypes
import ipaddress
import copy
import hashlib
import io
import subprocess
import threading
import time
import socket
import json
import os
import secrets
import sys
import uuid as _uuid_mod
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, jsonify, request, render_template, send_file
from flask_sock import Sock
from PIL import Image, UnidentifiedImageError

from engine.singbox import SingBoxManager, SINGBOX_VERSION
from engine.mihomo import MultiCoreManager, MIHOMO_VERSION
from engine.core_config import build_proxy_config, choose_core, CORES
from engine.route_info import observed_app_routes, observed_rule_routes
from engine.amneziawg import AmneziaWGManager
from engine.config import parse_link, fetch_subscription
from engine.storage import load_groups, save_groups
from engine.wg_storage import load_wg_groups, save_wg_groups
from engine.wg_config import (
    parse_wg_conf,
    fetch_wg_subscription,
    build_wg_tun_config,
)
from engine.ping import ping_groups, wg_ping, ping_color, tunnel_ping
from engine.stats import tracker as stats_tracker
from engine.apps import load_apps, save_apps, get_running_processes, POPULAR_APPS
from engine.hwid import generate_hwid
from engine import autostart
from ui import profile_state
from ui.zapret_service import ZapretService
from engine.paths import data_dir
from engine.connection_state import ConnectionCoordinator
from engine.reconnect import Reconnector
from engine.json_store import atomic_write_json
from engine.task_state import BackgroundTaskCoordinator

from engine.diagnostics import journal, export_journal
from ui import window_control
from engine.app_meta import APP_VERSION
# Настройки живут в ui/app_state.py. Имена сохранены прежними: словарь
# _app_settings — тот же объект, что и app_state.app_settings.
from ui.app_state import (  # noqa: E402
    TUNNEL_KEYS as _TUNNEL_KEYS,
    save_settings as _save_settings,
    app_settings as _app_settings,
    port_number as _port_number,
    CLASH_PORT_DEFAULT as _CLASH_PORT_DEFAULT,
    RESERVED_LOCAL_PORTS as _RESERVED_LOCAL_PORTS,
)

SING_BOX_VERSION = "1.10.x"

# ── Traffic stats ────────────────────────────────────────────
import http.client
import json as _json

_traffic_thread = None
_traffic_stop   = threading.Event()


def _wait_clash_ready(timeout: float = 8.0, cancelled=None, alive=None) -> bool:
    """Ждём, пока ядро реально поднимет Clash API на выбранном порту.
    Ожидание прекращается сразу после отмены текущей попытки.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cancelled and cancelled():
            return False
        if alive and not alive():
            return False
        try:
            c = http.client.HTTPConnection("127.0.0.1", _clash_port, timeout=1.0)
            c.request("GET", "/version")
            r = c.getresponse()
            r.read()
            c.close()
            if r.status == 200 and not (cancelled and cancelled()) and not (alive and not alive()):
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


_TRAFFIC_POLL_SECONDS = 2.0
# Тишина дольше этого при живых соединениях означает, что туннель поднят,
# но байты до сервера не доходят — молча это больше не проходит.
_TRAFFIC_STALL_TICKS = 15
_TRAFFIC_FAILURE_TICKS = 3


def _traffic_loop(attempt, stop_event):
    """Опрашивает Clash API и транслирует статистику по приложениям.
    HTTP Keep-Alive снижает нагрузку на процессор.
    """
    CLASH_HOST = "127.0.0.1"
    CLASH_PORT = _clash_port
    conn = None
    failures = 0
    stalled = 0
    reported_failure = False
    reported_stall = False
    last_totals = None
    last_routes = None

    while not stop_event.is_set():
        try:
            if conn is None:
                conn = http.client.HTTPConnection(CLASH_HOST, CLASH_PORT, timeout=2.0)

            conn.request("GET", "/connections")
            resp = conn.getresponse()

            if resp.status == 200:
                raw_data = resp.read().decode('utf-8')
                data = _json.loads(raw_data)

                conns = data.get("connections", [])
                total_up   = data.get("uploadTotal",   0)
                total_down = data.get("downloadTotal", 0)

                if reported_failure:
                    _log("Статистика туннеля снова доступна", "info")
                failures, reported_failure = 0, False

                # Счётчики стоят, хотя соединения есть: трафик не проходит.
                if conns and (total_up, total_down) == last_totals:
                    stalled += 1
                else:
                    if reported_stall:
                        _log("Трафик через туннель пошёл", "info")
                    stalled, reported_stall = 0, False
                last_totals = (total_up, total_down)
                if stalled >= _TRAFFIC_STALL_TICKS and not reported_stall:
                    reported_stall = True
                    _log(
                        f"Туннель поднят, но за {int(_TRAFFIC_STALL_TICKS * _TRAFFIC_POLL_SECONDS)} с "
                        f"не прошло ни байта при {len(conns)} активных соединениях. "
                        "Трафик не доходит до сервера — проверьте сервер и выбранное ядро.",
                        "warn",
                    )

                def publish():
                    nonlocal last_routes
                    stats_tracker.update(total_up, total_down)
                    # Сырой массив соединений интерфейс не читает — гонять его
                    # по вебсокету каждые две секунды незачем. Агрегаты шлём
                    # только когда они изменились: иначе UI перерисовывает
                    # маршруты вхолостую.
                    payload = {
                        "type":      "traffic_stats",
                        "totalUp":   total_up,
                        "totalDown": total_down,
                    }
                    routes = (observed_app_routes(conns),
                              observed_rule_routes(conns, profile_state.apps_config.get('rules', [])))
                    if routes != last_routes:
                        payload["appRoutes"], payload["ruleRoutes"] = routes
                        last_routes = routes
                    _broadcast(payload)
                    _broadcast({
                        "type":  "stats",
                        **stats_tracker.get_snapshot(include_weekly=False),
                    })

                if stop_event.is_set() or not _connection.run_if_connected(
                    attempt,
                    publish,
                ):
                    break
            else:
                resp.read()
                failures += 1
                if failures >= _TRAFFIC_FAILURE_TICKS and not reported_failure:
                    reported_failure = True
                    _log(f"Clash API отвечает {resp.status} — статистика недоступна", "warn")

        except Exception as exc:
            if conn:
                conn.close()
                conn = None
            failures += 1
            if failures >= _TRAFFIC_FAILURE_TICKS and not reported_failure:
                reported_failure = True
                _log(f"Статистика туннеля недоступна: {exc}", "warn")

        stop_event.wait(timeout=_TRAFFIC_POLL_SECONDS)

    if conn:
        conn.close()


def _awg_traffic_loop(attempt, stop_event):
    """Publishes native AmneziaWG interface counters."""
    while not stop_event.is_set():
        uploaded, downloaded = awg_engine.get_transfer()

        def publish():
            stats_tracker.update(uploaded, downloaded)
            _broadcast({
                "type": "traffic_stats",
                "totalUp": uploaded,
                "totalDown": downloaded,
            })
            _broadcast({"type": "stats", **stats_tracker.get_snapshot(include_weekly=False)})

        if not _connection.run_if_connected(attempt, publish):
            break
        stop_event.wait(timeout=2.0)


def _start_traffic_monitor(attempt, backend="singbox"):
    global _traffic_thread, _traffic_stop
    _traffic_stop.set()
    stop_event = threading.Event()
    _traffic_stop = stop_event
    _traffic_thread = threading.Thread(
        target=_awg_traffic_loop if backend == "amneziawg" else _traffic_loop,
        args=(attempt, stop_event),
        daemon=True,
    )
    _traffic_thread.start()


def _stop_traffic_monitor():
    _traffic_stop.set()


app  = Flask(__name__, template_folder="templates")
sock = Sock(app)

SERVER_INSTANCE_ID = secrets.token_urlsafe(24)
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
# Порт Clash API текущей сессии; пересчитывается при каждом подключении.
_clash_port = _CLASH_PORT_DEFAULT
_stopping = False
_disconnect_lock = threading.Lock()


def _request_host_port() -> tuple[str | None, int | None]:
    parsed = urlsplit(f"//{request.host}")
    try:
        port = parsed.port
    except ValueError:
        return parsed.hostname, None
    if port is None:
        port = 443 if request.scheme == "https" else 80
    return parsed.hostname, port


@app.before_request
def _protect_local_api():
    host, port = _request_host_port()
    if request.remote_addr not in ("127.0.0.1", "::1") or host not in _LOOPBACK_HOSTS:
        return jsonify({"ok": False, "error": "Доступ разрешён только локально"}), 403

    origin = request.headers.get("Origin")
    if origin:
        parsed = urlsplit(origin)
        try:
            origin_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        except ValueError:
            return jsonify({"ok": False, "error": "Некорректный источник запроса"}), 403
        if (
            parsed.scheme not in ("http", "https")
            or parsed.hostname not in _LOOPBACK_HOSTS
            or origin_port != port
        ):
            return jsonify({"ok": False, "error": "Недоверенный источник запроса"}), 403


@app.after_request
def _secure_local_response(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; "
        "connect-src 'self' ws://127.0.0.1:* ws://localhost:*; "
        "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    )
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response

_DATA_DIR      = data_dir()

from ui.update_api import register as register_updates


def _close_for_update():
    """Закрыть интерфейс перед установкой обновления.

    В сборке на Electron окном владеет оболочка, контроллера здесь нет, и
    обращение к нему роняло установку: /api/updates/install отвечал 500 уже
    после запуска установщика с правами администратора. Приложение при этом
    не закрывалось, установщик не дожидался освобождения файлов и отменял
    обновление, а статус навсегда оставался 'installing' — все следующие
    попытки получали «Пакет не готов».

    Возвращает True, если окно закрыто здесь, и False, если закрыть его
    должна оболочка: тогда об этом сообщается странице.
    """
    controller = window_control.controller
    if controller is None:
        return False
    controller.close()
    return True


_updates = register_updates(app, lambda: _connection.state == 'off' and zapret_service.state == 'off',
                            _close_for_update)


@app.before_request
def _validate_mutation():
    if request.method != "POST" or not request.path.startswith("/api/") or request.mimetype == "multipart/form-data":
        return
    data = request.get_json(silent=True)
    if data is None:
        if request.get_data():
            return jsonify(ok=False, error="Некорректный JSON"), 400
        data = {}
    if not isinstance(data, dict):
        return jsonify(ok=False, error="Ожидается JSON-объект"), 400
    string_fields = {"exe", "name", "path", "link", "conf", "url", "group_id", "id", "protocol", "mode", "key", "strategy_id", "edge"}
    for key in string_fields & data.keys():
        if not isinstance(data[key], str) or len(data[key]) > (8*1024*1024 if key == "conf" else 65536 if key == "link" else 4096):
            return jsonify(ok=False, error=f"Некорректное поле {key}"), 400
    if "index" in data and (type(data["index"]) is not int or data["index"] < 0):
        return jsonify(ok=False, error="Некорректный индекс"), 400
    if "enabled" in data and type(data["enabled"]) is not bool:
        return jsonify(ok=False, error="enabled должен быть true или false"), 400
    changing_network = request.path in {"/api/settings", "/api/protocol", "/api/socks5/regenerate"} or request.path.startswith(("/api/servers/", "/api/groups/", "/api/wg/servers/", "/api/wg/groups/")) or request.path in {"/api/apps/mode", "/api/apps/add", "/api/apps/remove", "/api/apps/toggle"}
    if changing_network and (_stopping or _connection.state != "off"):
        return jsonify(ok=False, error="Сначала отключите VPN; изменения применяются перед подключением"), 409
    if (changing_network or request.path == "/api/hwid/regenerate") and _subscription_lock.locked():
        return jsonify(ok=False, error="Дождитесь завершения обновления подписки"), 409


@app.errorhandler(ValueError)
def _invalid_value(exc):
    return jsonify(ok=False, error=str(exc)), 400




def _ping_timeout_seconds(value) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        return 3.0
    timeout /= 1000.0
    return min(30.0, max(0.2, timeout))


def _tunnel_kwargs() -> dict:
    socks5_auth = None
    if _app_settings.get("socks5_auth"):
        u = _app_settings.get("socks5_user", "")
        p = _app_settings.get("socks5_pass", "")
        if u and p:
            socks5_auth = {"user": u, "pass": p}

    custom_dns_raw = _app_settings.get("custom_dns", "")
    custom_dns = [d.strip() for d in custom_dns_raw.split(",") if d.strip()] \
                  if custom_dns_raw else None

    lan_is_secured = bool(
        _app_settings.get("lan")
        and socks5_auth
        and socks5_auth.get("user")
        and socks5_auth.get("pass")
    )

    return dict(
        kill_switch    = _app_settings.get("kill_switch",    False),
        block_udp      = _app_settings.get("block_udp",      False),
        socks5_auth    = socks5_auth,
        dns_preset     = _app_settings.get("dns_preset",     "cf_google"),
        custom_dns     = custom_dns,
        fakedns        = _app_settings.get("fakedns",        False),
        mux            = _app_settings.get("mux",            False),
        preferred_ip   = _app_settings.get("preferred_ip",   "ipv4"),
        allow_lan      = lan_is_secured,
    )


def _replace_group_servers(group, servers, wireguard=False):
    old = group.get("servers", [])
    identities = {}
    for item in old:
        identities.setdefault(profile_state.server_fingerprint(item), []).append(item.get("ui_id"))
    selected_group = _app_settings["selected_wg_group"] if wireguard else _app_settings["selected_group"]
    selected_index = _app_settings["selected_wg_index"] if wireguard else _app_settings["selected_index"]
    selected_id = old[selected_index].get("ui_id") if selected_group == group["id"] and type(selected_index) is int and 0 <= selected_index < len(old) else None
    for item in servers:
        pool = identities.get(profile_state.server_fingerprint(item), [])
        if pool:
            item["ui_id"] = pool.pop(0)
    group["servers"] = servers
    profile_state.ensure_server_ids([group])
    if selected_group == group["id"]:
        new_index = next((i for i, item in enumerate(servers) if item.get("ui_id") == selected_id), None)
        _app_settings["selected_wg_index" if wireguard else "selected_index"] = new_index
        if not _save_settings(_app_settings):
            raise OSError("Не удалось сохранить выбор сервера")


# Автогенерация HWID если не задан
if not _app_settings.get("hwid"):
    _app_settings["hwid"] = generate_hwid()
    if not _save_settings(_app_settings):
        raise RuntimeError("Не удалось сохранить постоянный HWID. Проверьте права на папку данных приложения.")

_ws_clients  = []
_ws_lock     = threading.Lock()
_connection  = ConnectionCoordinator()
_conn_server = ""
_ping_value  = "—"
_ping_color  = "dim"
_ping_thread = None
_ping_stop   = threading.Event()
# Порты локального прокси хранятся только в настройках: отдельные глобалы
# дублировали их и требовали ручной синхронизации в пяти местах.
_app_settings["socks"] = _port_number(_app_settings.get("socks"), 1080)
_app_settings["http"] = _port_number(_app_settings.get("http"), 8080)
if (
    _app_settings["socks"] == _app_settings["http"]
    or _app_settings["socks"] in _RESERVED_LOCAL_PORTS
    or _app_settings["http"] in _RESERVED_LOCAL_PORTS
):
    _app_settings["socks"], _app_settings["http"] = 1080, 8080
    _save_settings(_app_settings)

# ── VLESS state ─────────────────────────────────────────

# ── WG state ────────────────────────────────────────



# ── App routing state ───────────────────────────────────

# ── Ping scan state ───────────────────────────────────
_ping_scans = BackgroundTaskCoordinator()
_wg_ping_scans = BackgroundTaskCoordinator()

# ── Helpers ────────────────────────────────────────

_subscription_lock = threading.Lock()


def _start_subscription_update(data, refresh=False, wireguard=False):
    groups = profile_state.wg_groups if wireguard else profile_state.groups
    save = profile_state.save_wireguard_groups if wireguard else profile_state.save_proxy_groups
    broadcast = _broadcast_wg_groups if wireguard else _broadcast_groups
    target = next((g for g in groups if g["id"] == data.get("id")), None) if refresh else None
    url = target.get("url", "") if target else data.get("url", "").strip()
    if (refresh and not target) or not url.startswith(("https://", "http://")):
        return jsonify(ok=False, error="Нужна ссылка подписки http:// или https://"), 400
    name = data.get("name", "").strip()
    if len(name) > 160:
        return jsonify(ok=False, error="Название не должно превышать 160 символов"), 400
    if not target:
        target = next((g for g in groups if g.get("url") == url), None)
    is_new = target is None
    if is_new:
        target = {"id": ("wg-" if wireguard else "") + str(_uuid_mod.uuid4())[:8],
                  "name": name or ("WG Подписка" if wireguard else "Подписка"), "url": url, "servers": []}
    if not _subscription_lock.acquire(blocking=False):
        return jsonify(ok=False, error="Подписка уже обновляется"), 409

    def work():
        try:
            _broadcast({"type": "subscription_busy", "busy": True})
            _log("Загрузка подписки…", "info")
            error = ""
            metadata = {}
            servers = None
            try:
                fetch = fetch_wg_subscription if wireguard else fetch_subscription
                servers = fetch(url, hwid=_app_settings.get("hwid", ""))
                metadata = getattr(servers, "metadata", {})
                if not servers:
                    raise ValueError("Провайдер не передал ни одного поддерживаемого сервера")
            except Exception as exc:
                from engine.subscriptions import SubscriptionError
                metadata = getattr(exc, "metadata", {})
                error = str(exc) if isinstance(exc, SubscriptionError) else "Не удалось прочитать подписку. Проверьте формат ссылки и доступность сервиса."
            previous = copy.deepcopy(target)
            previous_settings = copy.deepcopy(_app_settings)
            previous_indices = (_app_settings["selected_index"], _app_settings["selected_wg_index"])

            def commit():
                if _stopping:
                    raise ValueError("VPN отключается; повторите обновление после остановки")
                if error:
                    target.setdefault("subscription", {}).update({k: v for k, v in metadata.items() if k != "updated_at"})
                    target["subscription"].update(error=error, checked_at=int(time.time()))
                else:
                    _replace_group_servers(target, servers, wireguard=wireguard)
                    target["subscription"] = {**metadata, "updated_at": int(time.time()), "error": ""}
                if is_new:
                    if not name and metadata.get("provider_name"):
                        target["name"] = metadata["provider_name"]
                    groups.append(target)
                save()

            try:
                if not _connection.run_if_idle(commit):
                    raise ValueError("VPN был включён во время загрузки. Отключите его и повторите обновление.")
            except Exception:
                if is_new and target in groups:
                    groups.remove(target)
                target.clear()
                target.update(previous)
                _app_settings["selected_index"], _app_settings["selected_wg_index"] = previous_indices
                _app_settings.clear()
                _app_settings.update(previous_settings)
                _save_settings(_app_settings)
                raise
            broadcast()
            _log(error, "err") if error else _log(f"Подписка обновлена: {len(servers)} серверов", "ok")
        except Exception as exc:
            _log("Не удалось применить обновление подписки: " + (str(exc) if isinstance(exc, ValueError) else "ошибка сохранения данных"), "err")
        finally:
            _subscription_lock.release()
            _broadcast({"type": "subscription_busy", "busy": False})

    try:
        threading.Thread(target=work, daemon=True).start()
    except Exception:
        _subscription_lock.release()
        raise
    return jsonify(ok=True)

def _get_selected_server():
    if _app_settings["selected_group"] is None or _app_settings["selected_index"] is None:
        return None
    for g in profile_state.groups:
        if g["id"] == _app_settings["selected_group"]:
            srvs = g.get("servers", [])
            if 0 <= _app_settings["selected_index"] < len(srvs):
                return srvs[_app_settings["selected_index"]]
    return None


def _get_selected_wg_server():
    if _app_settings["selected_wg_group"] is None or _app_settings["selected_wg_index"] is None:
        return None
    for g in profile_state.wg_groups:
        if g["id"] == _app_settings["selected_wg_group"]:
            srvs = g.get("servers", [])
            if 0 <= _app_settings["selected_wg_index"] < len(srvs):
                return srvs[_app_settings["selected_wg_index"]]
    return None


def _groups_for_ui():
    return [
        {
            "id":      g["id"],
            "name":    g["name"],
            "url":     g.get("url"),
            "subscription": g.get("subscription", {}),
            "count":   len(g.get("servers", [])),
            "servers": [
                {
                    "ui_id": s.get("ui_id", ""),
                    "remark": s.get("remark", ""),
                    "protocol": s.get("protocol", "vless"),
                    "transport": "quic" if s.get("protocol") == "hysteria2" else s.get("type", "tcp"),
                    "reality": s.get("security") == "reality",
                }
                for s in g.get("servers", [])
            ],
        }
        for g in profile_state.groups
    ]


def _wg_groups_for_ui():
    return [
        {
            "id":      g["id"],
            "name":    g["name"],
            "url":     g.get("url"),
            "subscription": g.get("subscription", {}),
            "count":   len(g.get("servers", [])),
            "servers": [
                {
                    "ui_id": s.get("ui_id", ""),
                    "remark": s.get("remark", ""),
                    "is_awg": s.get("is_awg", False),
                }
                for s in g.get("servers", [])
            ],
        }
        for g in profile_state.wg_groups
    ]


def _ensure_manual_group():
    for g in profile_state.groups:
        if g["id"] == "manual":
            return g
    g = {"id": "manual", "name": "Вручную", "url": None, "servers": []}
    profile_state.groups.insert(0, g)
    return g


def _ensure_wg_manual_group():
    for g in profile_state.wg_groups:
        if g["id"] == "manual-wg":
            return g
    g = {"id": "manual-wg", "name": "Вручную", "url": None, "servers": []}
    profile_state.wg_groups.insert(0, g)
    return g


def _broadcast(data: dict):
    dead = []
    msg = json.dumps(data)
    with _ws_lock:
        clients = list(_ws_clients)
    for ws in clients:
        try:
            ws.send(msg)
        except Exception:
            dead.append(ws)
    if dead:
        with _ws_lock:
            for d in dead:
                if d in _ws_clients:
                    _ws_clients.remove(d)


from engine.core_logs import ErrorNotifications

_error_notifications = ErrorNotifications()


def _log(msg, tag="log"):
    journal.log({"err": 40, "warn": 30}.get(tag, 20), str(msg))
    _broadcast({"type": "log", "msg": msg, "tag": tag})
    if tag == "err" and _error_notifications.should_notify(msg):
        _broadcast({"type": "operation_error", "message": msg})


def _broadcast_groups():
    _broadcast({
        "type":     "groups_updated",
        "groups":   _groups_for_ui(),
        "selGroup": _app_settings["selected_group"],
        "selIndex": _app_settings["selected_index"],
    })


def _broadcast_wg_groups():
    _broadcast({
        "type":        "wg_groups_updated",
        "wgGroups":    _wg_groups_for_ui(),
        "selWgGroup":  _app_settings["selected_wg_group"],
        "selWgIndex":  _app_settings["selected_wg_index"],
        "activeProtocol": _app_settings["active_protocol"],
    })


def _get_routed_exes() -> list:
    exes = []
    for a in profile_state.apps_config.get("apps", []):
        if not a.get("enabled", True):
            continue
        exe = a["exe"].strip()
        exe = os.path.basename(exe)
        if exe:
            exes.append(exe)
    return exes


def _handle_vpn_exit(_return_code):
    previous = _connection.cancel(_reset_connection_state)
    if previous != "off":
        _broadcast({"type": "status", "state": "off"})
    if previous == "on" and not _stopping:
        _reconnector.start()


def _reconnect_selected():
    with app.test_request_context('/api/connect', method='POST', json={'protocol': _app_settings["active_protocol"]}):
        result = api_connect()
        if isinstance(result, tuple): result = result[0]
        return result.get_json().get('ok') is True


_reconnector = Reconnector(_reconnect_selected, lambda: _connection.state,
    lambda: _app_settings.get('reconnect') is True and not _stopping,
    lambda message: _log(message, 'warn'))


vpn_engine = MultiCoreManager(
    log_callback=_log,
    exit_callback=_handle_vpn_exit,
)
awg_engine = AmneziaWGManager(
    log_callback=_log,
    exit_callback=_handle_vpn_exit,
)
_vpn_engine_lock = threading.RLock()
_vpn_error = False


def _next_available_local_port(preferred: int, excluded: set[int]) -> int | None:
    candidates = list(range(preferred + 1, min(65536, preferred + 101)))
    candidates += list(range(1024, min(preferred, 65536)))
    for candidate in candidates:
        if candidate in excluded or candidate in _RESERVED_LOCAL_PORTS:
            continue
        if vpn_engine._port_free(candidate):
            return candidate
    return None


def _ensure_local_proxy_ports() -> bool:
    """Move auxiliary proxy listeners away from occupied third-party ports.

    The TUN connection must not fail merely because Telegram or another local
    proxy already uses 1080/8080. The selected replacement is persisted so the
    UI and programs using Sadness VPN's local proxy see one stable value.
    """
    with _vpn_engine_lock:
        previous = (_app_settings["socks"], _app_settings["http"])
        occupied = {*previous, *_RESERVED_LOCAL_PORTS}
        changes = []
        for label, key in (("SOCKS5", "socks"), ("HTTP", "http")):
            current = _app_settings[key]
            if vpn_engine._port_free(current):
                continue
            replacement = _next_available_local_port(current, occupied)
            if replacement is None:
                raise ValueError(f"Не найден свободный локальный порт для {label}")
            owner = vpn_engine._port_owner(current)
            _app_settings[key] = replacement
            occupied.add(replacement)
            changes.append((label, current, replacement, owner))
        if not changes:
            return False
        if not _save_settings(_app_settings):
            _app_settings["socks"], _app_settings["http"] = previous
            raise ValueError("Не удалось сохранить автоматически выбранные порты")
        for label, old, new, owner in changes:
            _log(f"{label}: порт {old} занят ({owner}); выбран свободный порт {new}", "warn")
        _broadcast({"type": "app_settings_updated", "settings": {
            "socks": _app_settings["socks"],
            "http": _app_settings["http"],
        }})
        return True


def _ensure_clash_port() -> int:
    """Выбрать порт для Clash API ядра.

    Порт не пользовательский и нигде не сохраняется: он нужен только на время
    сессии. Раньше 9090 был зашит в конфиги, монитор трафика и пинг, и чужой
    процесс на этом порту давал невнятное «ядро не подняло Clash API за 8с».
    """
    global _clash_port
    if vpn_engine._port_free(_CLASH_PORT_DEFAULT):
        _clash_port = _CLASH_PORT_DEFAULT
        return _clash_port
    owner = vpn_engine._port_owner(_CLASH_PORT_DEFAULT)
    replacement = _next_available_local_port(_CLASH_PORT_DEFAULT, {_app_settings["socks"], _app_settings["http"]})
    if replacement is None:
        raise ValueError(f"Порт {_CLASH_PORT_DEFAULT} занят ({owner}), свободной замены не нашлось")
    _clash_port = replacement
    _log(f"Clash API: порт {_CLASH_PORT_DEFAULT} занят ({owner}); выбран {replacement}", "warn")
    return _clash_port


zapret_service = ZapretService(log_callback=_log, broadcast=_broadcast)
zapret_engine = zapret_service.engine


def _start_vpn_for_attempt(attempt: int, config: dict) -> bool:
    """Start only while the same attempt is still current."""
    with _vpn_engine_lock:
        if not _connection.is_current(attempt):
            return False
        return vpn_engine.start(config)


def _stop_vpn_engine():
    with _vpn_engine_lock:
        vpn_engine.stop()
        awg_engine.stop()


def _activate_vpn_attempt(
    attempt: int,
    server_name: str,
    backend: str = "singbox",
) -> bool:
    def activate():
        global _conn_server
        _conn_server = server_name
        if backend == "amneziawg":
            _log("Нативный AmneziaWG-интерфейс поднят", "ok")
        else:
            _log("TUN-интерфейс поднят", "ok")
        _broadcast({"type": "status", "state": "on", "server": _conn_server,
                    "core": "AmneziaWG" if backend == "amneziawg" else vpn_engine.name})
        stats_tracker.start()
        _start_ping_monitor(attempt)
        _start_traffic_monitor(attempt, backend=backend)

    return _connection.complete(attempt, activate)


def _finish_vpn_attempt(attempt: int, config: dict, server_name: str):
    started = _start_vpn_for_attempt(attempt, config)
    ready = started and _wait_clash_ready(
        cancelled=lambda: not _connection.is_current(attempt),
        alive=vpn_engine.is_alive,
    )

    if ready and _activate_vpn_attempt(attempt, server_name):
        return

    if started:
        _stop_vpn_engine()

    if _connection.fail(attempt):
        if started:
            _log(f"{vpn_engine.name} не поднял собственный Clash API за 8с — смотри логи выше", "err")
        _broadcast({"type": "status", "state": "off"})


def _finish_awg_attempt(attempt: int, server: dict, server_name: str):
    global _vpn_error
    try:
        with _vpn_engine_lock:
            if not _connection.is_current(attempt):
                return
            started = awg_engine.start(server, cancelled=lambda: not _connection.is_current(attempt))
    except Exception as exc:
        _log(str(exc), "err")
        if awg_engine.running:
            _vpn_error = True
            _connection.complete(attempt)
            _broadcast({"type": "status", "state": "error", "server": server_name})
            return
        started = False
    if started and _activate_vpn_attempt(
        attempt,
        server_name,
        backend="amneziawg",
    ):
        return

    if started:
        awg_engine.stop()
    if _connection.fail(attempt):
        _log("AmneziaWG не установил защищённое соединение", "err")
        _broadcast({"type": "status", "state": "off"})


def _reset_connection_state():
    global _ping_value, _ping_color, _conn_server, _vpn_error
    _vpn_error = False
    _stop_ping_monitor()
    _stop_traffic_monitor()
    stats_tracker.stop()
    _ping_value = "—"
    _ping_color = "dim"
    _conn_server = ""


def _cancel_vpn_connection():
    global _vpn_error
    _reconnector.cancel()
    awg_engine.request_stop()
    _connection.cancel()
    try:
        _stop_vpn_engine()
    except Exception:
        if awg_engine.running:
            _vpn_error = True
            attempt = _connection.begin()
            if attempt is not None:
                _connection.complete(attempt)
        raise
    _reset_connection_state()

# ── WebSocket ────────────────────────────────────────
@sock.route("/ws")
def ws_handler(ws):
    try:
        _app_settings["startup"] = autostart.enabled()
    except Exception:
        journal.warning("Не удалось прочитать состояние автозапуска")
    with _ws_lock:
        _ws_clients.append(ws)
    connection_state = "stopping" if _stopping else "error" if _vpn_error else _connection.state
    ws.send(json.dumps({
        "type"           : "state",
        "connected"      : connection_state in ("on", "error"),
        "status"         : connection_state,
        "server"         : _conn_server,
        "ping"           : _ping_value,
        "pingColor"      : _ping_color,
        "groups"         : _groups_for_ui(),
        "subscriptionBusy": _subscription_lock.locked(),
        "selGroup"       : _app_settings["selected_group"],
        "selIndex"       : _app_settings["selected_index"],
        "wgGroups"       : _wg_groups_for_ui(),
        "selWgGroup"     : _app_settings["selected_wg_group"],
        "selWgIndex"     : _app_settings["selected_wg_index"],
        "activeProtocol" : _app_settings["active_protocol"],
        "socks"          : _app_settings["socks"],
        "http"           : _app_settings["http"],
        "appSettings"    : _app_settings,
        "core"           : "AmneziaWG" if _app_settings["active_protocol"] == "wg" and awg_engine.running else vpn_engine.name,
        "coreVersions"   : f"sing-box {SINGBOX_VERSION} · Mihomo {MIHOMO_VERSION}",
        "tunnelSettings" : {k: _app_settings.get(k) for k in _TUNNEL_KEYS},
        "appsConfig"      : profile_state.apps_config,
        "hwid"            : _app_settings.get("hwid", ""),
        "stats"           : stats_tracker.get_snapshot(),
        "zapretRunning"   : zapret_service.running,
        "zapretState"     : zapret_service.state,
        "zapretStrategy"  : zapret_service.strategy,
        "zapretStrategies": zapret_service.strategies(),
        "appVersion"       : APP_VERSION,
        "engineVersion"    : SING_BOX_VERSION,
    }))
    try:
        while True:
            ws.receive()
    except Exception:
        pass
    with _ws_lock:
        if ws in _ws_clients:
            _ws_clients.remove(ws)

# ── Ping loop ──────────────────────────────────────
def _ping_loop(attempt, stop_event):
    while not stop_event.is_set():
        try:
            ms = tunnel_ping(
                test_url=_app_settings.get("ping_url") or "https://www.gstatic.com/generate_204",
                timeout=_app_settings.get("ping_timeout", 3000) / 1000,
                native_awg=_app_settings["active_protocol"] == "wg" and awg_engine.running,
                clash_port=_clash_port,
            )
            value = f"{ms}ms" if ms is not None else "—"
            color = ping_color(ms)
        except Exception:
            value = "—"
            color = "red"

        def publish():
            global _ping_value, _ping_color
            _ping_value = value
            _ping_color = color
            _broadcast({"type": "ping", "value": value, "color": color})

        if stop_event.is_set() or not _connection.run_if_connected(
            attempt,
            publish,
        ):
            break
        stop_event.wait(timeout=5.0)


def _start_ping_monitor(attempt):
    global _ping_thread, _ping_stop
    _ping_stop.set()
    stop_event = threading.Event()
    _ping_stop = stop_event
    _ping_thread = threading.Thread(
        target=_ping_loop,
        args=(attempt, stop_event),
        daemon=True,
    )
    _ping_thread.start()


def _stop_ping_monitor():
    _ping_stop.set()

# ── API ───────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/health", methods=["GET"])
def api_health():
    return jsonify({
        "ok": True,
        "app": "SadnessVPN",
        "version": APP_VERSION,
        "instance": SERVER_INSTANCE_ID,
    })


_PUBLIC_IP_SOURCES = (
    ("ipify", "https://api64.ipify.org?format=json", "json"),
    ("Cloudflare", "https://www.cloudflare.com/cdn-cgi/trace", "trace"),
    ("icanhazip", "https://icanhazip.com/", "text"),
    ("ifconfig.me", "https://ifconfig.me/ip", "text"),
)


def _parse_public_ip(
    raw: bytes,
    response_type: str,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    text = raw.decode("utf-8-sig", errors="strict").strip()
    if response_type == "json":
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("Invalid public IP response")
        value = payload.get("ip", "")
    elif response_type == "trace":
        values = {}
        for line in text.splitlines():
            key, separator, value = line.partition("=")
            if separator:
                values[key.strip()] = value.strip()
        value = values.get("ip", "")
    else:
        value = text.splitlines()[0].strip() if text else ""
    return ipaddress.ip_address(str(value).strip())


def _fetch_public_ip(source_name: str, url: str, response_type: str):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"SadnessVPN/{APP_VERSION}",
            "Accept": "application/json,text/plain;q=0.9,*/*;q=0.5",
        },
    )
    with urllib.request.urlopen(req, timeout=3.0) as response:
        address = _parse_public_ip(response.read(4096), response_type)
    return address, source_name


@app.route("/api/network/ip", methods=["POST"])
def api_network_ip():
    for source_name, url, response_type in _PUBLIC_IP_SOURCES:
        try:
            address, source = _fetch_public_ip(source_name, url, response_type)
            return jsonify({
                "ok": True,
                "ip": str(address),
                "version": address.version,
                "source": source,
            })
        except Exception:
            continue
    return jsonify({
        "ok": False,
        "error": "Не удалось определить внешний IP ни через один источник",
    })



# ── HWID API ──────────────────────────────────────
@app.route("/api/hwid", methods=["GET"])
def api_hwid_get():
    return jsonify({"hwid": _app_settings.get("hwid", "")})


@app.route("/api/hwid/regenerate", methods=["POST"])
def api_hwid_regenerate():
    previous = _app_settings.get("hwid", "")
    _app_settings["hwid"] = generate_hwid()
    if not _save_settings(_app_settings):
        _app_settings["hwid"] = previous
        return jsonify({"ok": False, "error": "Не удалось сохранить новый HWID"})
    _log("Создан новый HWID устройства", "info")
    return jsonify({"ok": True, "hwid": _app_settings["hwid"]})


# Роуты оформления — в ui/routes/appearance.py.


# ── App routing API ───────────────────────────────────








@app.post('/api/routing/conflicts')
def api_routing_conflicts():
    from engine.rule_conflicts import analyze
    try:
        return jsonify(ok=True, conflicts=analyze((request.get_json(silent=True) or {}).get('rules')))
    except (ValueError, TypeError):
        return jsonify(ok=False, error='Некорректный список правил'), 400


@app.post('/api/routing/validate')
def api_routing_validate():
    from engine.routing_rules import normalize_rule, validate_rules
    raw=request.get_json(silent=True) or {}
    try:
        rule=normalize_rule({**raw,'destination':'proxy'})
        validate_rules([rule],profile_state.groups)
    except (ValueError,TypeError):
        return jsonify(ok=False,field='value',error='Проверьте значение и тип правила. Для категорий используйте список.'),400
    try:
        rule['destination']=raw.get('destination','proxy')
        validate_rules([rule],profile_state.groups)
    except (ValueError,TypeError):
        return jsonify(ok=False,field='server',error='Выберите доступный сервер или основной маршрут.'),400
    return jsonify(ok=True,rule=rule)


















@app.get('/api/apps/catalog')
def api_process_catalog():
    from engine.process_catalog import process_catalog
    return jsonify(ok=True,apps=process_catalog())


@app.get('/api/apps/icon')
def api_process_icon():
    from engine.process_catalog import process_icon
    icon=process_icon(request.args.get('exe'))
    if not icon:return '',404
    return send_file(io.BytesIO(icon),mimetype='image/png',max_age=300)

# ── VLESS серверы ───────────────────────────────────















# ── WireGuard / AmneziaWG серверы ─────────────────────────















# ── Ping all ─────────────────────────────────────────
@app.route("/api/ping/all", methods=["POST"])
def api_ping_all():
    generation, stop = _ping_scans.begin()
    results = {}
    groups_snapshot = [
        {"id": g["id"], "servers": list(g.get("servers", []))}
        for g in profile_state.groups
    ]
    def on_result(gid, idx, ms, color):
        def publish():
            results[(gid, idx)] = ms
            server_id = next(
                (
                    group["servers"][idx].get("ui_id", "")
                    for group in groups_snapshot
                    if group["id"] == gid and 0 <= idx < len(group["servers"])
                ),
                "",
            )
            _broadcast({"type": "ping_result", "gid": gid, "index": idx,
                        "sid": server_id, "ms": ms, "color": color,
                        "label": f"{ms}ms" if ms is not None else "—"})

        _ping_scans.run_if_current(
            generation,
            stop,
            publish,
        )
    def run_ping():
        ping_type = _app_settings.get("ping_type", "tcp")
        ping_groups(
            groups_snapshot,
            on_result,
            stop,
            ping_type=ping_type,
            test_url=str(_app_settings.get("ping_url", "")),
            timeout=_ping_timeout_seconds(_app_settings.get("ping_timeout")),
        )
        def finish():
            _broadcast({"type": "ping_done"})

        _ping_scans.run_if_current(generation, stop, finish)
    threading.Thread(target=run_ping, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/ping/stop", methods=["POST"])
def api_ping_stop():
    _ping_scans.cancel()
    _broadcast({"type": "ping_done"})
    return jsonify({"ok": True})



# ── Connect / Disconnect ─────────────────────────────────
@app.route("/api/protocol", methods=["POST"])
def api_protocol():
    protocol = (request.get_json(silent=True) or {}).get("protocol")
    if protocol not in ("vless", "wg"):
        return jsonify({"ok": False, "error": "Неизвестный протокол"}), 400
    if _connection.state != "off":
        return jsonify({"ok": False, "error": "Сначала отключите VPN"}), 409
    previous = _app_settings["active_protocol"]
    _app_settings["active_protocol"] = protocol
    if not _save_settings(_app_settings):
        _app_settings["active_protocol"] = previous
        return jsonify(ok=False, error="Не удалось сохранить протокол"), 500
    return jsonify({"ok": True})


@app.route("/api/connect", methods=["POST"])
def api_connect():
    if _stopping:
        return jsonify(ok=False, error="Дождитесь завершения отключения"), 409
    if _connection.state != "off":
        return jsonify(ok=False, error="Подключение уже активно или выполняется"), 409
    data = request.get_json(silent=True) or {}
    proto = data.get("protocol", _app_settings["active_protocol"])

    if proto == "wg":
        if any(r.get("enabled", True) for r in profile_state.apps_config.get("rules", [])):
            return jsonify(ok=False, error="Пользовательские правила требуют TUN / Mihomo"), 400
        if any(a.get("enabled") is not False and a.get("destination", "default") != "default" for a in profile_state.apps_config.get("apps", [])):
            return jsonify(ok=False, error="Индивидуальные серверы требуют TUN с ядром Авто / Mihomo. В режиме WG/AWG верните назначения на основной маршрут."), 400
        server = _get_selected_wg_server()
        if not server:
            return jsonify({"ok": False, "error": "WG сервер не выбран"})
        mode        = profile_state.apps_config.get("mode", "all")
        routed_exes = _get_routed_exes()
        is_awg = server.get("is_awg", False)
        cfg = None
        if not is_awg:
            try:
                _ensure_local_proxy_ports()
                cfg = build_wg_tun_config(
                    server,
                    socks_port   = _app_settings["socks"],
                    http_port    = _app_settings["http"],
                    clash_port   = _ensure_clash_port(),
                    routing_mode = mode,
                    routed_apps  = routed_exes,
                    **_tunnel_kwargs(),
                )
            except ValueError as exc:
                return jsonify(ok=False, error=str(exc)), 500
        attempt = _connection.begin()
        if attempt is None:
            error = "Уже подключено" if _connection.connected else "Подключение уже выполняется"
            return jsonify({"ok": False, "error": error})

        def do_connect_wg():
            def announce():
                _broadcast({"type": "status", "state": "connecting"})
                proto_label = "AmneziaWG native" if is_awg else "WireGuard"
                _log(f"Подключение к {server['remark']} [{proto_label}] ...", "info")
                if is_awg:
                    _log(
                        "AWG использует системный туннель для всего компьютера; "
                        "маршрутизация по отдельным приложениям и локальные SOCKS/HTTP "
                        "в этом режиме недоступны.",
                        "info",
                    )

            if not _connection.run_if_current(attempt, announce):
                return
            if is_awg:
                _finish_awg_attempt(attempt, server, server.get("remark", ""))
            else:
                _finish_vpn_attempt(attempt, cfg, server.get("remark", ""))

        threading.Thread(target=do_connect_wg, daemon=True).start()
        return jsonify({"ok": True})

    else:  # vless / ss / trojan / hysteria2
        server = _get_selected_server()
        if not server:
            return jsonify({"ok": False, "error": "Сервер не выбран"})
        mode        = profile_state.apps_config.get("mode", "all")
        routed_exes = _get_routed_exes()
        from engine.app_routes import assignments, build_multi_route_config
        from engine.routing_rules import resolve_rules
        try:
            _ensure_local_proxy_ports()
            explicit_routes = resolve_rules(profile_state.apps_config.get("rules", []), profile_state.groups) + \
                assignments(profile_state.apps_config.get("apps", []), profile_state.groups)
            config_builder = (lambda server, **kwargs: build_multi_route_config(server, explicit_routes, **kwargs)) if explicit_routes else build_proxy_config
            cfg = config_builder(
                server,
                preference   = "mihomo" if explicit_routes else _app_settings.get("core", "auto"),
                socks_port   = _app_settings["socks"],
                http_port    = _app_settings["http"],
                clash_port   = _ensure_clash_port(),
                routing_mode = mode,
                routed_apps  = routed_exes,
                **_tunnel_kwargs(),
            )
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 500
        proto_label = server.get("protocol", "vless").upper()
        attempt = _connection.begin()
        if attempt is None:
            error = "Уже подключено" if _connection.connected else "Подключение уже выполняется"
            return jsonify({"ok": False, "error": error})

        def do_connect_vless():
            def announce():
                _broadcast({"type": "status", "state": "connecting"})
                _log(f"Подключение к {server['remark']} [{proto_label}] ...", "info")
                selected_core = "mihomo (индивидуальные маршруты)" if explicit_routes else choose_core(server, _app_settings.get('core', 'auto'))
                _log(f"Ядро: {selected_core} | транспорт: {server.get('type', 'tcp')} | Reality: {'да' if server.get('security') == 'reality' else 'нет'}", "info")
                _log(f"Режим: TUN | маршрутизация: {mode} ({len(routed_exes)} приложений)", "info")
                if mode == "whitelist" and routed_exes:
                    shown = ", ".join(routed_exes[:5]) + ("..." if len(routed_exes) > 5 else "")
                    _log(f"Через VPN: {shown}", "info")
                    _log("⚠ Браузеры и другие приложения работают НАПРЯМУЮ — без VPN", "warn")

            if not _connection.run_if_current(attempt, announce):
                return
            _finish_vpn_attempt(attempt, cfg, server.get("remark", ""))

        threading.Thread(target=do_connect_vless, daemon=True).start()
        return jsonify({"ok": True})


@app.route("/api/disconnect", methods=["POST"])
def api_disconnect():
    global _stopping
    _reconnector.cancel()
    if not _disconnect_lock.acquire(blocking=False):
        return jsonify(ok=True)
    _stopping = True
    awg_engine.request_stop()
    _connection.cancel()
    _broadcast({"type": "status", "state": "stopping"})
    def finish():
        global _stopping
        try:
            _cancel_vpn_connection()
            _log("Отключено", "info")
            _broadcast({"type": "status", "state": "off"})
        except Exception as exc:
            _log(str(exc), "err")
            _broadcast({"type": "status", "state": "error" if awg_engine.running else "off"})
        finally:
            _stopping = False
            _disconnect_lock.release()
    threading.Thread(target=finish, daemon=True).start()
    return jsonify(ok=True)






def _window_command(command):
    if window_control.controller is None:
        return jsonify({"ok": False, "error": "Оконный интерфейс не запущен"}), 503
    try:
        getattr(window_control.controller, command)()
        return jsonify({"ok": True})
    except Exception as exc:
        journal.exception("Команда окна: %s", command)
        return jsonify({"ok": False, "error": str(exc)}), 500


def close_to_tray_enabled():
    return _app_settings.get('mintray') is True


# Роуты окна, статистики и диагностики живут в ui/routes/system.py.
# Роуты портов, настроек, туннеля и пинга — в ui/routes/settings.py.


def shutdown_engines():
    try:
        _cancel_vpn_connection()
    except Exception:
        journal.exception("Не удалось завершить VPN")
        raise
    try:
        zapret_service.stop()
    except Exception:
        journal.exception("Не удалось завершить Zapret")


class _Late:
    """Позднее связывание имени из этого модуля.

    Блюпринты получают помощники через init(), и обычная передача значением
    делала бы снимок: подмена ui.server._broadcast в тестах уже не доходила бы
    до роутов. Прокси разрешает имя в момент обращения, поэтому существующие
    точки подмены продолжают работать, а состояние остаётся в одном месте.
    """
    def __init__(self, name):
        object.__setattr__(self, "_name", name)

    def _target(self):
        return globals()[object.__getattribute__(self, "_name")]

    def __call__(self, *args, **kwargs):
        return self._target()(*args, **kwargs)

    def __getattr__(self, attribute):
        return getattr(self._target(), attribute)


# Блюпринты регистрируются последними: к этому моменту все зависимости,
# которые им передаются, уже определены в этом модуле.
from ui.routes import apps as _apps_routes  # noqa: E402
from ui.routes import appearance as _appearance_routes  # noqa: E402
from ui.routes import servers as _servers_routes  # noqa: E402
from ui.routes import settings as _settings_routes  # noqa: E402
from ui.routes import system as _system_routes  # noqa: E402
from ui.routes import wireguard as _wireguard_routes  # noqa: E402
from ui.routes import zapret as _zapret_routes  # noqa: E402

_system_routes.init(broadcast=_broadcast, window_command=_window_command)
app.register_blueprint(_system_routes.bp)

_zapret_routes.init(service=zapret_service, broadcast=_broadcast, log=_log)
app.register_blueprint(_zapret_routes.bp)

_appearance_routes.init(broadcast=_broadcast)
app.register_blueprint(_appearance_routes.bp)

_settings_routes.init(broadcast=_broadcast, log=_log,
                      tunnel_busy=lambda: _stopping or _connection.state != "off")
app.register_blueprint(_settings_routes.bp)

_servers_routes.init(_log=_Late("_log"), _broadcast_groups=_Late("_broadcast_groups"),
                     _groups_for_ui=_Late("_groups_for_ui"),
                     _ensure_manual_group=_Late("_ensure_manual_group"),
                     _start_subscription_update=_Late("_start_subscription_update"),
                     _save_settings=_Late("_save_settings"))
app.register_blueprint(_servers_routes.bp)

_wireguard_routes.init(_log=_Late("_log"), _broadcast=_Late("_broadcast"),
                       _broadcast_wg_groups=_Late("_broadcast_wg_groups"),
                       _ensure_wg_manual_group=_Late("_ensure_wg_manual_group"),
                       _start_subscription_update=_Late("_start_subscription_update"),
                       _ping_timeout_seconds=_Late("_ping_timeout_seconds"),
                       _wg_ping_scans=_Late("_wg_ping_scans"),
                       _save_settings=_Late("_save_settings"))
app.register_blueprint(_wireguard_routes.bp)

_apps_routes.init(_log=_Late("_log"), _broadcast=_Late("_broadcast"),
                  _connection=_Late("_connection"), save_apps=_Late("save_apps"))
app.register_blueprint(_apps_routes.bp)


def run(host="127.0.0.1", port=45678):
    app.run(host=host, port=port, debug=False, use_reloader=False)
