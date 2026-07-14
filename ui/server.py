"""
ui/server.py — Sadness VPN Flask backend
"""
import ctypes
import ctypes.wintypes
import ipaddress
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

from flask import Flask, jsonify, request, render_template
from flask_sock import Sock

from engine.singbox import SingBoxManager
from engine.config import (
    parse_link,
    build_xray_tun_config as build_xray_config,
    fetch_subscription,
)
from engine.storage import load_groups, save_groups
from engine.wg_storage import load_wg_groups, save_wg_groups
from engine.wg_config import (
    parse_wg_conf,
    fetch_wg_subscription,
    build_wg_tun_config,
)
from engine.ping import ping_groups, wg_ping, ping_color
from engine.stats import tracker as stats_tracker
from engine.apps import load_apps, save_apps, get_running_processes, POPULAR_APPS
from engine.hwid import generate_hwid
from engine.zapret import ZapretManager
from engine.paths import data_dir
from engine.connection_state import ConnectionCoordinator
from engine.json_store import atomic_write_json
from engine.task_state import BackgroundTaskCoordinator

APP_VERSION = "2.0.2"
SING_BOX_VERSION = "1.10.x"

# ── Traffic stats ────────────────────────────────────────────
import http.client
import json as _json

_traffic_thread = None
_traffic_stop   = threading.Event()


def _wait_clash_ready(timeout: float = 8.0, cancelled=None) -> bool:
    """Ждём, пока sing-box реально поднимет Clash API на 9090.
    Ожидание прекращается сразу после отмены текущей попытки.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cancelled and cancelled():
            return False
        try:
            c = http.client.HTTPConnection("127.0.0.1", 9090, timeout=1.0)
            c.request("GET", "/version")
            r = c.getresponse()
            r.read()
            c.close()
            if r.status == 200 and not (cancelled and cancelled()):
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def _traffic_loop(attempt, stop_event):
    """Опрашивает Clash API и транслирует статистику по приложениям.
    HTTP Keep-Alive снижает нагрузку на процессор.
    """
    CLASH_HOST = "127.0.0.1"
    CLASH_PORT = 9090
    conn = None

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

                def publish():
                    stats_tracker.update(total_up, total_down)
                    _broadcast({
                        "type":        "traffic_stats",
                        "connections": conns,
                        "totalUp":     total_up,
                        "totalDown":   total_down,
                    })
                    _broadcast({
                        "type":  "stats",
                        **stats_tracker.get_snapshot(),
                    })

                if stop_event.is_set() or not _connection.run_if_connected(
                    attempt,
                    publish,
                ):
                    break
            else:
                resp.read()

        except Exception:
            if conn:
                conn.close()
                conn = None

        stop_event.wait(timeout=2.0)

    if conn:
        conn.close()


def _start_traffic_monitor(attempt):
    global _traffic_thread, _traffic_stop
    _traffic_stop.set()
    stop_event = threading.Event()
    _traffic_stop = stop_event
    _traffic_thread = threading.Thread(
        target=_traffic_loop,
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
_RESERVED_LOCAL_PORTS = {45678, 9090}


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
_SETTINGS_PATH = os.path.join(_DATA_DIR, "settings.json")

_TUNNEL_KEYS = (
    "kill_switch", "block_udp", "socks5_auth", "socks5_user", "socks5_pass",
    "mux", "fakedns", "preferred_ip", "dns_preset", "custom_dns",
    "ping_type", "ping_url", "ping_timeout", "server_sort",
)

_USER_APP_SETTING_KEYS = {
    "startup", "autoconn", "silent", "lan", "mintray",
    "animations", "petals", "favorite_servers",
}

_DEFAULT_SETTINGS = {
    "startup":          False,
    "autoconn":         False,
    "silent":           False,
    "lan":              False,
    "mintray":          False,
    "animations":       True,
    "petals":           True,
    "favorite_servers": [],
    "socks":            1080,
    "http":             8080,
    "selected_group":   None,
    "selected_index":   None,
    "selected_wg_group": None,
    "selected_wg_index": None,
    "active_protocol":  "vless",
    "hwid":             "",
    "ping_type":        "tcp",
    "ping_url":         "https://www.gstatic.com/generate_204",
    "ping_timeout":     3000,
    "kill_switch":      False,
    "block_udp":        False,
    "socks5_auth":      False,
    "socks5_user":      "",
    "socks5_pass":      "",
    "mux":              False,
    "fakedns":          False,
    "preferred_ip":     "ipv4",
    "dns_preset":       "cf_google",
    "custom_dns":       "",
    "server_sort":      "default",
}


def _load_settings() -> dict:
    try:
        with open(_SETTINGS_PATH, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if not isinstance(loaded, dict):
            raise ValueError("Invalid settings")
        settings = {**_DEFAULT_SETTINGS, **loaded}
        for key in (
            "startup", "autoconn", "silent", "lan", "mintray", "animations",
            "petals", "kill_switch",
            "block_udp", "socks5_auth", "mux", "fakedns",
        ):
            if not isinstance(settings.get(key), bool):
                settings[key] = _DEFAULT_SETTINGS[key]
        for key in ("socks5_user", "socks5_pass", "custom_dns", "ping_url"):
            if not isinstance(settings.get(key), str):
                settings[key] = _DEFAULT_SETTINGS[key]
        if settings.get("lan") and not (
            settings.get("socks5_auth")
            and settings.get("socks5_user")
            and settings.get("socks5_pass")
        ):
            settings["lan"] = False
        if settings.get("preferred_ip") not in ("ipv4", "ipv6", "auto"):
            settings["preferred_ip"] = "ipv4"
        if settings.get("dns_preset") not in (
            "cf_google", "google", "cloudflare", "adguard", "quad9",
            "xbox", "xbox_dot", "custom",
        ):
            settings["dns_preset"] = "cf_google"
        if settings.get("ping_type") not in ("tcp", "icmp", "http_get", "http_head"):
            settings["ping_type"] = "tcp"
        favorites = settings.get("favorite_servers")
        if not isinstance(favorites, list):
            settings["favorite_servers"] = []
        else:
            settings["favorite_servers"] = [
                item for item in favorites
                if isinstance(item, str) and 0 < len(item) <= 128
            ][:10000]
        if settings.get("server_sort") not in ("default", "ping", "name"):
            settings["server_sort"] = "default"
        for key in ("selected_index", "selected_wg_index"):
            if settings.get(key) is not None and not isinstance(settings.get(key), int):
                settings[key] = None
        for key in ("selected_group", "selected_wg_group"):
            if settings.get(key) is not None and not isinstance(settings.get(key), str):
                settings[key] = None
        if settings.get("active_protocol") not in ("vless", "wg"):
            settings["active_protocol"] = "vless"
        return settings
    except Exception:
        return dict(_DEFAULT_SETTINGS)


def _save_settings(cfg: dict):
    try:
        atomic_write_json(_SETTINGS_PATH, cfg)
        return True
    except Exception as e:
        print(f"Ошибка сохранения настроек: {e}")
        return False


_app_settings = _load_settings()


def _port_number(value, default=None) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        if default is not None:
            return default
        raise ValueError("Порт должен быть числом")
    if not 1 <= port <= 65535:
        if default is not None:
            return default
        raise ValueError("Порт должен быть в диапазоне от 1 до 65535")
    return port


def _ping_timeout_seconds(value) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        return 3.0
    if timeout > 60:
        timeout /= 1000.0
    return min(30.0, max(0.2, timeout))


def _normalize_tunnel_setting(key, value):
    if key in ("kill_switch", "block_udp", "socks5_auth", "mux", "fakedns"):
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be true or false")
        return value
    if key in ("socks5_user", "socks5_pass", "custom_dns"):
        if not isinstance(value, str) or len(value) > 2048:
            raise ValueError(f"Invalid {key}")
        return value
    if key == "preferred_ip":
        if value not in ("ipv4", "ipv6", "auto"):
            raise ValueError("Invalid IP preference")
        return value
    if key == "dns_preset":
        if value not in (
            "cf_google", "google", "cloudflare", "adguard", "quad9",
            "xbox", "xbox_dot", "custom",
        ):
            raise ValueError("Invalid DNS preset")
        return value
    if key == "ping_type":
        if value not in ("tcp", "icmp", "http_get", "http_head"):
            raise ValueError("Invalid ping type")
        return value
    if key == "ping_url":
        if not isinstance(value, str) or len(value) > 2048 or not value.startswith(("http://", "https://")):
            raise ValueError("Invalid ping URL")
        return value
    if key == "ping_timeout":
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            raise ValueError("Invalid ping timeout") from None
        if not 0.2 <= numeric <= 30000:
            raise ValueError("Invalid ping timeout")
        return value
    if key == "server_sort":
        if value not in ("default", "ping", "name"):
            raise ValueError("Invalid server sorting mode")
        return value
    raise ValueError("Unknown tunnel setting")


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


def _normalize_app_setting(key, value):
    if key in {"startup", "autoconn", "silent", "lan", "mintray", "animations", "petals"}:
        if not isinstance(value, bool):
            raise ValueError("Значение настройки должно быть true или false")
        return value
    if key == "favorite_servers":
        if not isinstance(value, list):
            raise ValueError("Некорректный список избранных серверов")
        cleaned = []
        for item in value:
            if not isinstance(item, str) or not 0 < len(item) <= 128:
                raise ValueError("Некорректный идентификатор сервера")
            if item not in cleaned:
                cleaned.append(item)
        if len(cleaned) > 10000:
            raise ValueError("Слишком много избранных серверов")
        return cleaned
    raise ValueError("Неизвестная настройка")


def _ensure_server_ids(groups: list) -> bool:
    """Give every persisted server a stable UI identity independent of list order."""
    changed = False
    seen = set()
    for group in groups:
        for server in group.get("servers", []):
            server_id = server.get("ui_id")
            if (
                not isinstance(server_id, str)
                or not server_id
                or len(server_id) > 128
                or server_id in seen
            ):
                server_id = _uuid_mod.uuid4().hex
                server["ui_id"] = server_id
                changed = True
            seen.add(server_id)
    return changed


# Автогенерация HWID если не задан
if not _app_settings.get("hwid"):
    _app_settings["hwid"] = generate_hwid()
    _save_settings(_app_settings)

_ws_clients  = []
_ws_lock     = threading.Lock()
_connection  = ConnectionCoordinator()
_conn_server = ""
_ping_value  = "—"
_ping_color  = "dim"
_ping_thread = None
_ping_stop   = threading.Event()
_socks_port  = _port_number(_app_settings.get("socks"), 1080)
_http_port   = _port_number(_app_settings.get("http"), 8080)
if (
    _socks_port == _http_port
    or _socks_port in _RESERVED_LOCAL_PORTS
    or _http_port in _RESERVED_LOCAL_PORTS
):
    _socks_port, _http_port = 1080, 8080
    _app_settings["socks"] = _socks_port
    _app_settings["http"] = _http_port
    _save_settings(_app_settings)

# ── VLESS state ─────────────────────────────────────────
_groups: list = load_groups()
if _ensure_server_ids(_groups):
    save_groups(_groups)
_sel_group    = _app_settings.get("selected_group")
_sel_index    = _app_settings.get("selected_index")

# ── WG state ────────────────────────────────────────
_wg_groups: list = load_wg_groups()
if _ensure_server_ids(_wg_groups):
    save_wg_groups(_wg_groups)
_sel_wg_group    = _app_settings.get("selected_wg_group")
_sel_wg_index    = _app_settings.get("selected_wg_index")
_active_protocol = _app_settings.get("active_protocol", "vless")


def _save_proxy_groups():
    _ensure_server_ids(_groups)
    save_groups(_groups)


def _save_wireguard_groups():
    _ensure_server_ids(_wg_groups)
    save_wg_groups(_wg_groups)

# ── App routing state ───────────────────────────────────
_apps_config  = load_apps()

# ── Ping scan state ───────────────────────────────────
_ping_scans = BackgroundTaskCoordinator()
_wg_ping_scans = BackgroundTaskCoordinator()

# ── Helpers ────────────────────────────────────────

def _get_selected_server():
    if _sel_group is None or _sel_index is None:
        return None
    for g in _groups:
        if g["id"] == _sel_group:
            srvs = g.get("servers", [])
            if 0 <= _sel_index < len(srvs):
                return srvs[_sel_index]
    return None


def _get_selected_wg_server():
    if _sel_wg_group is None or _sel_wg_index is None:
        return None
    for g in _wg_groups:
        if g["id"] == _sel_wg_group:
            srvs = g.get("servers", [])
            if 0 <= _sel_wg_index < len(srvs):
                return srvs[_sel_wg_index]
    return None


def _groups_for_ui():
    return [
        {
            "id":      g["id"],
            "name":    g["name"],
            "url":     g.get("url"),
            "count":   len(g.get("servers", [])),
            "servers": [
                {
                    "ui_id": s.get("ui_id", ""),
                    "remark": s.get("remark", ""),
                    "protocol": s.get("protocol", "vless"),
                }
                for s in g.get("servers", [])
            ],
        }
        for g in _groups
    ]


def _wg_groups_for_ui():
    return [
        {
            "id":      g["id"],
            "name":    g["name"],
            "url":     g.get("url"),
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
        for g in _wg_groups
    ]


def _ensure_manual_group():
    for g in _groups:
        if g["id"] == "manual":
            return g
    g = {"id": "manual", "name": "Вручную", "url": None, "servers": []}
    _groups.insert(0, g)
    return g


def _ensure_wg_manual_group():
    for g in _wg_groups:
        if g["id"] == "manual-wg":
            return g
    g = {"id": "manual-wg", "name": "Вручную", "url": None, "servers": []}
    _wg_groups.insert(0, g)
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


def _log(msg, tag="log"):
    _broadcast({"type": "log", "msg": msg, "tag": tag})


def _broadcast_groups():
    _broadcast({
        "type":     "groups_updated",
        "groups":   _groups_for_ui(),
        "selGroup": _sel_group,
        "selIndex": _sel_index,
    })


def _broadcast_wg_groups():
    _broadcast({
        "type":        "wg_groups_updated",
        "wgGroups":    _wg_groups_for_ui(),
        "selWgGroup":  _sel_wg_group,
        "selWgIndex":  _sel_wg_index,
    })


def _get_routed_exes() -> list:
    exes = []
    for a in _apps_config.get("apps", []):
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


vpn_engine = SingBoxManager(
    log_callback=_log,
    exit_callback=_handle_vpn_exit,
)
_vpn_engine_lock = threading.RLock()
_zapret_engine_lock = threading.RLock()
_zapret_running  = False
_zapret_strategy = None
_zapret_state = "off"
_zapret_generation = 0


def _handle_zapret_exit(_return_code):
    global _zapret_running, _zapret_strategy, _zapret_state, _zapret_generation
    with _zapret_engine_lock:
        _zapret_generation += 1
        _zapret_running = False
        _zapret_strategy = None
        _zapret_state = "off"
    _broadcast({"type": "zapret_status", "running": False, "strategy": None, "state": "off"})


zapret_engine = ZapretManager(
    log_callback=_log,
    exit_callback=_handle_zapret_exit,
)


def _stop_zapret_engine():
    global _zapret_running, _zapret_strategy, _zapret_state, _zapret_generation
    with _zapret_engine_lock:
        _zapret_generation += 1
        zapret_engine.stop()
        _zapret_running = False
        _zapret_strategy = None
        _zapret_state = "off"


def _start_vpn_for_attempt(attempt: int, config: dict) -> bool:
    """Start only while the same attempt is still current."""
    result = []

    def start():
        with _vpn_engine_lock:
            result.append(vpn_engine.start(config))

    if not _connection.run_if_current(attempt, start):
        return False
    return result[0]


def _stop_vpn_engine():
    with _vpn_engine_lock:
        vpn_engine.stop()


def _activate_vpn_attempt(attempt: int, server_name: str) -> bool:
    def activate():
        global _conn_server
        _conn_server = server_name
        _log("TUN-интерфейс поднят", "ok")
        _broadcast({"type": "status", "state": "on", "server": _conn_server})
        stats_tracker.start()
        _start_ping_monitor(attempt)
        _start_traffic_monitor(attempt)

    return _connection.complete(attempt, activate)


def _finish_vpn_attempt(attempt: int, config: dict, server_name: str):
    started = _start_vpn_for_attempt(attempt, config)
    ready = started and _wait_clash_ready(
        cancelled=lambda: not _connection.is_current(attempt)
    )

    if ready and _activate_vpn_attempt(attempt, server_name):
        return

    if started:
        _stop_vpn_engine()

    if _connection.fail(attempt):
        _log("sing-box не поднял Clash API за 8с — смотри логи выше", "err")
        _broadcast({"type": "status", "state": "off"})


def _reset_connection_state():
    global _ping_value, _ping_color, _conn_server
    _stop_ping_monitor()
    _stop_traffic_monitor()
    stats_tracker.stop()
    _ping_value = "—"
    _ping_color = "dim"
    _conn_server = ""


def _cancel_vpn_connection():
    def cancel():
        _reset_connection_state()
        _stop_vpn_engine()

    _connection.cancel(cancel)

# ── WebSocket ────────────────────────────────────────
@sock.route("/ws")
def ws_handler(ws):
    with _ws_lock:
        _ws_clients.append(ws)
    connection_state = _connection.state
    ws.send(json.dumps({
        "type"           : "state",
        "connected"      : connection_state == "on",
        "status"         : connection_state,
        "server"         : _conn_server,
        "ping"           : _ping_value,
        "pingColor"      : _ping_color,
        "groups"         : _groups_for_ui(),
        "selGroup"       : _sel_group,
        "selIndex"       : _sel_index,
        "wgGroups"       : _wg_groups_for_ui(),
        "selWgGroup"     : _sel_wg_group,
        "selWgIndex"     : _sel_wg_index,
        "activeProtocol" : _active_protocol,
        "socks"          : _socks_port,
        "http"           : _http_port,
        "appSettings"    : _app_settings,
        "tunnelSettings" : {k: _app_settings.get(k) for k in _TUNNEL_KEYS},
        "appsConfig"      : _apps_config,
        "hwid"            : _app_settings.get("hwid", ""),
        "stats"           : stats_tracker.get_snapshot(),
        "zapretRunning"   : _zapret_running,
        "zapretStrategy"  : _zapret_strategy,
        "zapretStrategies": zapret_engine.get_strategies(),
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
            t0 = time.perf_counter()
            s  = socket.create_connection(("1.1.1.1", 443), timeout=3)
            ms = (time.perf_counter() - t0) * 1000
            s.close()
            value = f"{ms:.0f}ms"
            color = "green" if ms < 150 else "yellow" if ms < 400 else "red"
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


@app.route("/api/network/ip", methods=["POST"])
def api_network_ip():
    try:
        req = urllib.request.Request(
            "https://api64.ipify.org?format=json",
            headers={"User-Agent": f"SadnessVPN/{APP_VERSION}"},
        )
        with urllib.request.urlopen(req, timeout=5.0) as response:
            payload = json.loads(response.read(4096).decode("utf-8"))
        value = str(payload.get("ip", "")).strip()
        ipaddress.ip_address(value)
        return jsonify({"ok": True, "ip": value})
    except Exception:
        return jsonify({"ok": False, "error": "Не удалось определить внешний IP"})


@app.route("/api/groups", methods=["GET"])
def api_groups():
    return jsonify({"groups": _groups_for_ui(), "selGroup": _sel_group, "selIndex": _sel_index})

# ── HWID API ──────────────────────────────────────
@app.route("/api/hwid", methods=["GET"])
def api_hwid_get():
    return jsonify({"hwid": _app_settings.get("hwid", "")})


@app.route("/api/hwid/regenerate", methods=["POST"])
def api_hwid_regenerate():
    global _app_settings
    previous = _app_settings.get("hwid", "")
    _app_settings["hwid"] = generate_hwid()
    if not _save_settings(_app_settings):
        _app_settings["hwid"] = previous
        return jsonify({"ok": False, "error": "Не удалось сохранить новый HWID"})
    _log(f"HWID перегенерирован: {_app_settings['hwid']}", "info")
    return jsonify({"ok": True, "hwid": _app_settings["hwid"]})

# ── App routing API ───────────────────────────────────
@app.route("/api/apps", methods=["GET"])
def api_apps_get():
    return jsonify(_apps_config)


@app.route("/api/apps/mode", methods=["POST"])
def api_apps_mode():
    global _apps_config
    data = request.get_json(silent=True) or {}
    mode = data.get("mode", "all")
    if mode not in ("all", "whitelist", "blacklist"):
        return jsonify({"ok": False, "error": "Неверный режим"})
    _apps_config["mode"] = mode
    save_apps(_apps_config)
    _broadcast({"type": "apps_config", "config": _apps_config})
    _log(f"Режим маршрутизации: {mode}", "info")
    return jsonify({"ok": True})


@app.route("/api/apps/add", methods=["POST"])
def api_apps_add():
    global _apps_config
    data = request.get_json(silent=True) or {}
    exe  = data.get("exe", "").strip()
    name = data.get("name", exe).strip()
    path = data.get("path", "").strip()
    if not exe:
        return jsonify({"ok": False, "error": "Нет exe"})
    if len(exe) > 260 or not name or len(name) > 256 or len(path) > 4096:
        return jsonify({"ok": False, "error": "Слишком длинное имя или путь"})
    for a in _apps_config["apps"]:
        if a["exe"].lower() == exe.lower():
            return jsonify({"ok": False, "error": "Уже добавлено"})
    _apps_config["apps"].append({"name": name, "exe": exe, "path": path, "enabled": True})
    save_apps(_apps_config)
    _broadcast({"type": "apps_config", "config": _apps_config})
    return jsonify({"ok": True})


@app.route("/api/apps/rename", methods=["POST"])
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
    for app_rule in _apps_config.get("apps", []):
        if app_rule.get("exe", "").lower() == exe.lower():
            app_rule["name"] = name
            save_apps(_apps_config)
            _broadcast({"type": "apps_config", "config": _apps_config})
            return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Правило не найдено"})


@app.route("/api/apps/export", methods=["POST"])
def api_apps_export():
    try:
        destination = Path.home() / "Downloads"
        destination.mkdir(parents=True, exist_ok=True)
        filename = f"SadnessVPN-routing-{datetime.now():%Y%m%d-%H%M%S-%f}.json"
        target = destination / filename
        atomic_write_json(str(target), _apps_config)
        return jsonify({"ok": True, "path": str(target)})
    except Exception as exc:
        return jsonify({"ok": False, "error": f"Не удалось экспортировать правила: {exc}"})


@app.route("/api/apps/remove", methods=["POST"])
def api_apps_remove():
    global _apps_config
    data   = request.get_json(silent=True) or {}
    exe    = data.get("exe", "").strip()
    before = len(_apps_config["apps"])
    _apps_config["apps"] = [a for a in _apps_config["apps"] if a["exe"].lower() != exe.lower()]
    if len(_apps_config["apps"]) == before:
        return jsonify({"ok": False, "error": "Не найдено"})
    save_apps(_apps_config)
    _broadcast({"type": "apps_config", "config": _apps_config})
    return jsonify({"ok": True})


@app.route("/api/apps/toggle", methods=["POST"])
def api_apps_toggle():
    global _apps_config
    data    = request.get_json(silent=True) or {}
    exe     = data.get("exe", "").strip()
    enabled = data.get("enabled", True)
    for a in _apps_config["apps"]:
        if a["exe"].lower() == exe.lower():
            a["enabled"] = bool(enabled)
            save_apps(_apps_config)
            _broadcast({"type": "apps_config", "config": _apps_config})
            return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Не найдено"})


@app.route("/api/apps/processes", methods=["GET"])
def api_apps_processes():
    return jsonify({"processes": get_running_processes()})


@app.route("/api/apps/popular", methods=["GET"])
def api_apps_popular():
    return jsonify({"apps": POPULAR_APPS})

# ── VLESS серверы ───────────────────────────────────
@app.route("/api/servers/add", methods=["POST"])
def api_add_server():
    global _sel_group, _sel_index
    data = request.get_json(silent=True) or {}
    link = data.get("link", "").strip()
    if not link:
        return jsonify({"ok": False, "error": "Пустая ссылка"})
    try:
        parsed = parse_link(link)
        mg = _ensure_manual_group()
        mg["servers"].append(parsed)
        _save_proxy_groups()
        _sel_group = "manual"
        _sel_index = len(mg["servers"]) - 1
        _app_settings["selected_group"] = _sel_group
        _app_settings["selected_index"] = _sel_index
        _save_settings(_app_settings)
        proto = parsed.get("protocol", "vless").upper()
        _log(f"Добавлен [{proto}]: {parsed['remark']}", "ok")
        _broadcast_groups()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/servers/import", methods=["POST"])
def api_import():
    data = request.get_json(silent=True) or {}
    url  = data.get("url", "").strip()
    name = data.get("name", "").strip() or "Подписка"
    if not url.startswith(("http://", "https://")):
        return jsonify({"ok": False, "error": "URL должен начинаться с http:// или https://"})

    def do_import():
        global _groups
        _log(f"Загрузка подписки: {url}", "info")
        try:
            hwid = _app_settings.get('hwid', '')
            if hwid:
                _log(f"HWID: {hwid}", "info")
            servers = fetch_subscription(url, hwid=hwid)
            if not servers:
                _log("Не найдено ни одного сервера", "warn")
                return
            gid = None
            for g in _groups:
                if g.get("url") == url:
                    g["servers"] = servers
                    g["name"]    = name
                    gid = g["id"]
                    break
            if gid is None:
                gid = str(_uuid_mod.uuid4())[:8]
                _groups.append({"id": gid, "name": name, "url": url, "servers": servers})
            _save_proxy_groups()
            _log(f"Импортировано {len(servers)} серверов в «{name}»!", "ok")
            _broadcast_groups()
        except Exception as e:
            _log(f"Ошибка импорта: {e}", "err")

    threading.Thread(target=do_import, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/groups/refresh", methods=["POST"])
def api_refresh_group():
    data   = request.get_json(silent=True) or {}
    gid    = data.get("id")
    target = next((g for g in _groups if g["id"] == gid), None)
    if not target or not target.get("url"):
        return jsonify({"ok": False, "error": "Нет URL для обновления"})

    def do_refresh():
        _log(f"Обновление подписки «{target['name']}»...", "info")
        try:
            hwid = _app_settings.get('hwid', '')
            servers = fetch_subscription(target["url"], hwid=hwid)
            if not servers:
                _log("Серверов не найдено", "warn")
                return
            target["servers"] = servers
            _save_proxy_groups()
            _log(f"Обновлено {len(servers)} серверов!", "ok")
            _broadcast_groups()
        except Exception as e:
            _log(f"Ошибка обновления: {e}", "err")

    threading.Thread(target=do_refresh, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/groups/delete", methods=["POST"])
def api_delete_group():
    global _groups, _sel_group, _sel_index
    data   = request.get_json(silent=True) or {}
    gid    = data.get("id")
    before = len(_groups)
    _groups = [g for g in _groups if g["id"] != gid]
    if len(_groups) == before:
        return jsonify({"ok": False, "error": "Группа не найдена"})
    if _sel_group == gid:
        _sel_group = None
        _sel_index = None
        _app_settings["selected_group"] = None
        _app_settings["selected_index"] = None
    _save_proxy_groups()
    _save_settings(_app_settings)
    _broadcast_groups()
    return jsonify({"ok": True})


@app.route("/api/groups/rename", methods=["POST"])
def api_rename_group():
    data = request.get_json(silent=True) or {}
    gid  = data.get("id")
    name = data.get("name", "").strip()
    for g in _groups:
        if g["id"] == gid:
            g["name"] = name
            _save_proxy_groups()
            _broadcast_groups()
            return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Не найдено"})


@app.route("/api/servers/select", methods=["POST"])
def api_select():
    global _sel_group, _sel_index, _active_protocol
    data = request.get_json(silent=True) or {}
    gid  = data.get("group_id")
    idx  = data.get("index")
    for g in _groups:
        if g["id"] == gid:
            srvs = g.get("servers", [])
            if idx is not None and 0 <= idx < len(srvs):
                _sel_group = gid
                _sel_index = idx
                _active_protocol = "vless"
                _app_settings["selected_group"]  = gid
                _app_settings["selected_index"]  = idx
                _app_settings["active_protocol"] = "vless"
                _save_settings(_app_settings)
                return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Неверный индекс"})


@app.route("/api/servers/delete", methods=["POST"])
def api_delete_server():
    global _sel_group, _sel_index
    data = request.get_json(silent=True) or {}
    gid  = data.get("group_id")
    idx  = data.get("index")
    for g in _groups:
        if g["id"] == gid:
            srvs = g.get("servers", [])
            if idx is not None and 0 <= idx < len(srvs):
                name = srvs[idx].get("remark", "")
                srvs.pop(idx)
                if _sel_group == gid and _sel_index == idx:
                    _sel_group = None
                    _sel_index = None
                    _app_settings["selected_group"] = None
                    _app_settings["selected_index"] = None
                _save_proxy_groups()
                _save_settings(_app_settings)
                _log(f"Удалён: {name}", "warn")
                _broadcast_groups()
                return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Не найдено"})


@app.route("/api/servers/rename", methods=["POST"])
def api_rename_server():
    data = request.get_json(silent=True) or {}
    gid  = data.get("group_id")
    idx  = data.get("index")
    name = data.get("name", "").strip()
    for g in _groups:
        if g["id"] == gid:
            srvs = g.get("servers", [])
            if idx is not None and 0 <= idx < len(srvs) and name:
                srvs[idx]["remark"] = name
                _save_proxy_groups()
                _broadcast_groups()
                return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Ошибка"})

# ── WireGuard / AmneziaWG серверы ─────────────────────────
@app.route("/api/wg/servers/add", methods=["POST"])
def api_wg_add_server():
    global _sel_wg_group, _sel_wg_index, _active_protocol
    data    = request.get_json(silent=True) or {}
    conf    = data.get("conf", "").strip()
    if not conf:
        return jsonify({"ok": False, "error": "Пустой конфиг"})
    try:
        servers = parse_wg_conf(conf)
        if not servers:
            return jsonify({"ok": False, "error": "Не удалось распарсить конфиг WireGuard"})
        mg = _ensure_wg_manual_group()
        added = 0
        is_awg_warn = False
        for s in servers:
            if s.get("is_awg"):
                is_awg_warn = True
            mg["servers"].append(s)
            added += 1
        _save_wireguard_groups()
        _sel_wg_group = "manual-wg"
        _sel_wg_index = len(mg["servers"]) - 1
        _active_protocol = "wg"
        _app_settings["selected_wg_group"] = _sel_wg_group
        _app_settings["selected_wg_index"] = _sel_wg_index
        _app_settings["active_protocol"]   = "wg"
        _save_settings(_app_settings)
        _log(f"Добавлено WG серверов: {added}", "ok")
        if is_awg_warn:
            _log(
                "⚠ AmneziaWG конфиг: AWG-поля (jc, jmin, jmax, s1, s2, h1-h4) "
                "не поддерживаются sing-box и будут проигнорированы. "
                "Подключение пройдёт как обычный WireGuard без обфускации.",
                "warn"
            )
        _broadcast_wg_groups()
        return jsonify({"ok": True, "added": added, "is_awg": is_awg_warn})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/wg/servers/import", methods=["POST"])
def api_wg_import():
    data = request.get_json(silent=True) or {}
    url  = data.get("url", "").strip()
    name = data.get("name", "").strip() or "WG Подписка"
    if not url.startswith(("http://", "https://")):
        return jsonify({"ok": False, "error": "URL должен начинаться с http:// или https://"})

    def do_import():
        global _wg_groups
        _log(f"Загрузка WG подписки: {url}", "info")
        try:
            servers = fetch_wg_subscription(url)
            if not servers:
                _log("Не найдено ни одного WG/AWG сервера", "warn")
                return
            gid = None
            for g in _wg_groups:
                if g.get("url") == url:
                    g["servers"] = servers
                    g["name"]    = name
                    gid = g["id"]
                    break
            if gid is None:
                gid = "wg-" + str(_uuid_mod.uuid4())[:8]
                _wg_groups.append({"id": gid, "name": name, "url": url, "servers": servers})
            _save_wireguard_groups()
            awg_count = sum(1 for s in servers if s.get("is_awg"))
            _log(f"Импортировано {len(servers)} WG серверов в «{name}»"
                 + (f" (из них {awg_count} AWG — без обфускации)" if awg_count else "") + "!", "ok")
            if awg_count:
                _log(
                    "⚠ AWG-поля (jc, jmin, jmax, s1, s2, h1-h4) не поддерживаются sing-box "
                    "и будут проигнорированы при подключении.",
                    "warn"
                )
            _broadcast_wg_groups()
        except Exception as e:
            _log(f"Ошибка импорта WG: {e}", "err")

    threading.Thread(target=do_import, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/wg/groups/refresh", methods=["POST"])
def api_wg_refresh_group():
    data   = request.get_json(silent=True) or {}
    gid    = data.get("id")
    target = next((g for g in _wg_groups if g["id"] == gid), None)
    if not target or not target.get("url"):
        return jsonify({"ok": False, "error": "Нет URL для обновления"})

    def do_refresh():
        _log(f"Обновление WG подписки «{target['name']}»...", "info")
        try:
            servers = fetch_wg_subscription(target["url"])
            if not servers:
                _log("Серверов не найдено", "warn")
                return
            target["servers"] = servers
            _save_wireguard_groups()
            _log(f"Обновлено {len(servers)} WG серверов!", "ok")
            _broadcast_wg_groups()
        except Exception as e:
            _log(f"Ошибка обновления: {e}", "err")

    threading.Thread(target=do_refresh, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/wg/groups/delete", methods=["POST"])
def api_wg_delete_group():
    global _wg_groups, _sel_wg_group, _sel_wg_index
    data   = request.get_json(silent=True) or {}
    gid    = data.get("id")
    before = len(_wg_groups)
    _wg_groups = [g for g in _wg_groups if g["id"] != gid]
    if len(_wg_groups) == before:
        return jsonify({"ok": False, "error": "Группа не найдена"})
    if _sel_wg_group == gid:
        _sel_wg_group = None
        _sel_wg_index = None
        _app_settings["selected_wg_group"] = None
        _app_settings["selected_wg_index"] = None
    _save_wireguard_groups()
    _save_settings(_app_settings)
    _broadcast_wg_groups()
    return jsonify({"ok": True})


@app.route("/api/wg/groups/rename", methods=["POST"])
def api_wg_rename_group():
    data = request.get_json(silent=True) or {}
    gid  = data.get("id")
    name = data.get("name", "").strip()
    for g in _wg_groups:
        if g["id"] == gid:
            g["name"] = name
            _save_wireguard_groups()
            _broadcast_wg_groups()
            return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Не найдено"})


@app.route("/api/wg/servers/select", methods=["POST"])
def api_wg_select():
    global _sel_wg_group, _sel_wg_index, _active_protocol
    data = request.get_json(silent=True) or {}
    gid  = data.get("group_id")
    idx  = data.get("index")
    for g in _wg_groups:
        if g["id"] == gid:
            srvs = g.get("servers", [])
            if idx is not None and 0 <= idx < len(srvs):
                _sel_wg_group    = gid
                _sel_wg_index    = idx
                _active_protocol = "wg"
                _app_settings["selected_wg_group"] = gid
                _app_settings["selected_wg_index"] = idx
                _app_settings["active_protocol"]   = "wg"
                _save_settings(_app_settings)
                return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Неверный индекс"})


@app.route("/api/wg/servers/delete", methods=["POST"])
def api_wg_delete_server():
    global _sel_wg_group, _sel_wg_index
    data = request.get_json(silent=True) or {}
    gid  = data.get("group_id")
    idx  = data.get("index")
    for g in _wg_groups:
        if g["id"] == gid:
            srvs = g.get("servers", [])
            if idx is not None and 0 <= idx < len(srvs):
                name = srvs[idx].get("remark", "")
                srvs.pop(idx)
                if _sel_wg_group == gid and _sel_wg_index == idx:
                    _sel_wg_group = None
                    _sel_wg_index = None
                    _app_settings["selected_wg_group"] = None
                    _app_settings["selected_wg_index"] = None
                _save_wireguard_groups()
                _save_settings(_app_settings)
                _log(f"Удалён WG: {name}", "warn")
                _broadcast_wg_groups()
                return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Не найдено"})


@app.route("/api/wg/servers/rename", methods=["POST"])
def api_wg_rename_server():
    data = request.get_json(silent=True) or {}
    gid  = data.get("group_id")
    idx  = data.get("index")
    name = data.get("name", "").strip()
    for g in _wg_groups:
        if g["id"] == gid:
            srvs = g.get("servers", [])
            if idx is not None and 0 <= idx < len(srvs) and name:
                srvs[idx]["remark"] = name
                _save_wireguard_groups()
                _broadcast_wg_groups()
                return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Ошибка"})

# ── Ping all ─────────────────────────────────────────
@app.route("/api/ping/all", methods=["POST"])
def api_ping_all():
    generation, stop = _ping_scans.begin()
    results = {}
    groups_snapshot = [
        {"id": g["id"], "servers": list(g.get("servers", []))}
        for g in _groups
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


@app.route("/api/wg/ping/all", methods=["POST"])
def api_wg_ping_all():
    from concurrent.futures import ThreadPoolExecutor
    generation, stop = _wg_ping_scans.begin()
    results = {}
    groups_snapshot = [
        {"id": g["id"], "servers": list(g.get("servers", []))}
        for g in _wg_groups
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

# ── Connect / Disconnect ─────────────────────────────────
@app.route("/api/connect", methods=["POST"])
def api_connect():
    data = request.get_json(silent=True) or {}
    proto = data.get("protocol", _active_protocol)

    if proto == "wg":
        server = _get_selected_wg_server()
        if not server:
            return jsonify({"ok": False, "error": "WG сервер не выбран"})
        mode        = _apps_config.get("mode", "all")
        routed_exes = _get_routed_exes()
        cfg = build_wg_tun_config(
            server,
            socks_port   = _socks_port,
            http_port    = _http_port,
            routing_mode = mode,
            routed_apps  = routed_exes,
            **_tunnel_kwargs(),
        )
        is_awg = server.get("is_awg", False)
        attempt = _connection.begin()
        if attempt is None:
            error = "Уже подключено" if _connection.connected else "Подключение уже выполняется"
            return jsonify({"ok": False, "error": error})

        def do_connect_wg():
            def announce():
                _broadcast({"type": "status", "state": "connecting"})
                proto_label = "AmneziaWG→WG" if is_awg else "WireGuard"
                _log(f"Подключение к {server['remark']} [{proto_label}] ...", "info")
                if is_awg:
                    _log(
                        "⚠ AWG-поля игнорируются — подключение как обычный WireGuard без обфускации.",
                        "warn"
                    )

            if not _connection.run_if_current(attempt, announce):
                return
            _finish_vpn_attempt(attempt, cfg, server.get("remark", ""))

        threading.Thread(target=do_connect_wg, daemon=True).start()
        return jsonify({"ok": True})

    else:  # vless / ss / trojan / hysteria2
        server = _get_selected_server()
        if not server:
            return jsonify({"ok": False, "error": "Сервер не выбран"})
        mode        = _apps_config.get("mode", "all")
        routed_exes = _get_routed_exes()
        cfg = build_xray_config(
            server,
            socks_port   = _socks_port,
            http_port    = _http_port,
            routing_mode = mode,
            routed_apps  = routed_exes,
            **_tunnel_kwargs(),
        )
        proto_label = server.get("protocol", "vless").upper()
        attempt = _connection.begin()
        if attempt is None:
            error = "Уже подключено" if _connection.connected else "Подключение уже выполняется"
            return jsonify({"ok": False, "error": error})

        def do_connect_vless():
            def announce():
                _broadcast({"type": "status", "state": "connecting"})
                _log(f"Подключение к {server['remark']} [{proto_label}] ...", "info")
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
    _cancel_vpn_connection()
    _log("Отключено", "info")
    _broadcast({"type": "status", "state": "off"})
    return jsonify({"ok": True})


@app.route("/api/settings", methods=["POST"])
def api_settings():
    global _socks_port, _http_port
    data        = request.get_json(silent=True) or {}
    try:
        socks_port = _port_number(data.get("socks", _socks_port))
        http_port = _port_number(data.get("http", _http_port))
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)})
    if socks_port == http_port:
        return jsonify({"ok": False, "error": "Порты SOCKS и HTTP должны отличаться"})
    if socks_port in _RESERVED_LOCAL_PORTS or http_port in _RESERVED_LOCAL_PORTS:
        return jsonify({"ok": False, "error": "Этот порт зарезервирован SadnessVPN"})
    previous_ports = (_socks_port, _http_port)
    _socks_port = socks_port
    _http_port = http_port
    _app_settings["socks"] = _socks_port
    _app_settings["http"]  = _http_port
    if not _save_settings(_app_settings):
        _socks_port, _http_port = previous_ports
        _app_settings["socks"] = _socks_port
        _app_settings["http"] = _http_port
        return jsonify({"ok": False, "error": "Не удалось сохранить порты"})
    return jsonify({"ok": True})


@app.route("/api/app-settings", methods=["POST"])
def api_app_settings():
    global _app_settings
    data  = request.get_json(silent=True) or {}
    key   = data.get("key")
    value = data.get("value")
    if key not in _USER_APP_SETTING_KEYS:
        return jsonify({"ok": False, "error": "Неизвестная настройка"})
    try:
        value = _normalize_app_setting(key, value)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)})
    if key == "lan" and value and not (
        _app_settings.get("socks5_auth")
        and _app_settings.get("socks5_user")
        and _app_settings.get("socks5_pass")
    ):
        return jsonify({
            "ok": False,
            "error": "Сначала включите SOCKS5-аутентификацию и задайте логин с паролем",
        })
    previous = _app_settings.get(key)
    _app_settings[key] = value
    if key == "startup":
        _TASK_NAME = "SadnessVPN"
        try:
            if getattr(sys, "frozen", False):
                exe_path = sys.executable
                task_command = f'"{exe_path}"'
            else:
                exe_path = os.path.abspath(
                    os.path.join(os.path.dirname(__file__), "..", "main.py")
                )
                task_command = f'"{sys.executable}" "{exe_path}"'
            if value:
                r = subprocess.run(
                    [
                        "schtasks", "/Create", "/F",
                        "/TN", _TASK_NAME,
                        "/TR", task_command,
                        "/SC", "ONLOGON",
                        "/RL", "HIGHEST",
                    ],
                    capture_output=True, text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                if r.returncode != 0:
                    raise RuntimeError((r.stderr or r.stdout).strip())
                try:
                    import winreg
                    reg = winreg.OpenKey(
                        winreg.HKEY_CURRENT_USER,
                        r"Software\Microsoft\Windows\CurrentVersion\Run",
                        0, winreg.KEY_SET_VALUE,
                    )
                    winreg.DeleteValue(reg, _TASK_NAME)
                    winreg.CloseKey(reg)
                except Exception:
                    pass
                _log(f"Автозапуск включён (планировщик задач): {exe_path}", "ok")
            else:
                subprocess.run(
                    ["schtasks", "/Delete", "/F", "/TN", _TASK_NAME],
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                try:
                    import winreg
                    reg = winreg.OpenKey(
                        winreg.HKEY_CURRENT_USER,
                        r"Software\Microsoft\Windows\CurrentVersion\Run",
                        0, winreg.KEY_SET_VALUE,
                    )
                    winreg.DeleteValue(reg, _TASK_NAME)
                    winreg.CloseKey(reg)
                except Exception:
                    pass
                _log("Автозапуск отключён", "info")
        except Exception as e:
            _app_settings[key] = previous
            return jsonify({"ok": False, "error": str(e)})
    if not _save_settings(_app_settings):
        _app_settings[key] = previous
        return jsonify({"ok": False, "error": "Не удалось сохранить настройку"})
    _broadcast({
        "type": "app_settings_updated",
        "settings": {item: _app_settings.get(item) for item in _USER_APP_SETTING_KEYS},
    })
    return jsonify({"ok": True})

# ── Window state ─────────────────────────────────────
_win_restore = {"x": None, "y": None, "w": 920, "h": 620}

# ── Window API ──────────────────────────────────────
@app.route("/api/window/minimize", methods=["POST"])
def api_win_minimize():
    try:
        hwnd = _get_app_hwnd()
        ctypes.windll.user32.ShowWindow(hwnd, 6)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})
    return jsonify({"ok": True})


@app.route("/api/window/close", methods=["POST"])
def api_win_close():
    if _app_settings.get("mintray"):
        try:
            hwnd = _get_app_hwnd()
            ctypes.windll.user32.ShowWindow(hwnd, 6)
            return jsonify({"ok": True, "minimized": True})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)})

    def _close():
        import time as _t
        # Корректно останавливаем все дочерние процессы перед выходом
        try:
            _cancel_vpn_connection()
        except Exception:
            pass
        try:
            _stop_zapret_engine()
        except Exception:
            pass
        _t.sleep(0.2)
        # Завершаем процесс — используем os._exit для надёжного выхода
        import os as _os
        _os._exit(0)
    threading.Thread(target=_close, daemon=True).start()
    return jsonify({"ok": True})


def _get_app_hwnd():
    hwnd = ctypes.windll.user32.FindWindowW(None, "Sadness VPN")
    if hwnd:
        return hwnd
    return ctypes.windll.user32.GetForegroundWindow()


def _get_monitor_work_area(hwnd):
    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize",    ctypes.c_ulong),
            ("rcMonitor", ctypes.wintypes.RECT),
            ("rcWork",    ctypes.wintypes.RECT),
            ("dwFlags",   ctypes.c_ulong),
        ]

    MONITOR_DEFAULTTONEAREST = 0x00000002
    hmon = ctypes.windll.user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
    return mi.rcWork


@app.route("/api/window/togglemax", methods=["POST"])
def api_win_togglemax():
    global _win_restore
    try:
        user32 = ctypes.windll.user32
        hwnd   = _get_app_hwnd()
        rect   = ctypes.wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        cur_w = rect.right  - rect.left
        cur_h = rect.bottom - rect.top

        wa    = _get_monitor_work_area(hwnd)
        wa_w  = wa.right  - wa.left
        wa_h  = wa.bottom - wa.top

        is_max = (cur_w >= wa_w - 4 and cur_h >= wa_h - 4)
        if is_max:
            rx = _win_restore["x"]
            ry = _win_restore["y"]
            rw = _win_restore["w"]
            rh = _win_restore["h"]
            if rx is None:
                rx = wa.left + (wa_w - rw) // 2
                ry = wa.top  + (wa_h - rh) // 2
            user32.SetWindowPos(hwnd, 0, rx, ry, rw, rh, 0x0004 | 0x0010)
            return jsonify({"ok": True, "maximized": False})
        else:
            _win_restore = {"x": rect.left, "y": rect.top, "w": cur_w, "h": cur_h}
            user32.SetWindowPos(hwnd, 0, wa.left, wa.top, wa_w, wa_h, 0x0004 | 0x0010)
            return jsonify({"ok": True, "maximized": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/window/info", methods=["GET"])
def api_win_info():
    try:
        hwnd = _get_app_hwnd()
        rect = ctypes.wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        return jsonify({"ok": True, "x": rect.left, "y": rect.top,
                        "width": rect.right - rect.left, "height": rect.bottom - rect.top})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/window/resize", methods=["POST"])
def api_win_resize():
    try:
        data      = request.get_json(silent=True) or {}
        x         = int(data.get("x", 0))
        y         = int(data.get("y", 0))
        w         = int(data.get("w", 920))
        h         = int(data.get("h", 620))
        move_only = bool(data.get("move_only", False))
        user32    = ctypes.windll.user32
        hwnd      = _get_app_hwnd()
        if move_only:
            rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            cw = rect.right  - rect.left
            ch = rect.bottom - rect.top
            user32.SetWindowPos(hwnd, 0, x, y, cw, ch, 0x0004 | 0x0010)
        else:
            user32.SetWindowPos(hwnd, 0, x, y, w, h, 0x0004 | 0x0010)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

# ── Statistics API ────────────────────────────────────
@app.route("/api/stats", methods=["GET"])
def api_stats():
    return jsonify(stats_tracker.get_snapshot())


@app.route("/api/stats/reset-today", methods=["POST"])
def api_stats_reset_today():
    stats_tracker.reset_today()
    snapshot = stats_tracker.get_snapshot()
    _broadcast({"type": "stats", **snapshot})
    return jsonify({"ok": True, "stats": snapshot})


@app.route("/api/stats/reset-all", methods=["POST"])
def api_stats_reset_all():
    stats_tracker.reset_all()
    snapshot = stats_tracker.get_snapshot()
    _broadcast({"type": "stats", **snapshot})
    return jsonify({"ok": True, "stats": snapshot})

# ── Advanced settings API ───────────────────────────────
@app.route("/api/tunnel-settings", methods=["GET"])
def api_tunnel_settings_get():
    return jsonify({k: _app_settings.get(k) for k in _TUNNEL_KEYS})


@app.route("/api/tunnel-settings", methods=["POST"])
def api_tunnel_settings_post():
    global _app_settings
    data = request.get_json(silent=True) or {}
    try:
        updates = {
            key: _normalize_tunnel_setting(key, value)
            for key, value in data.items()
            if key in _TUNNEL_KEYS
        }
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)})
    candidate = {**_app_settings, **updates}
    if candidate.get("lan") and not (
        candidate.get("socks5_auth")
        and candidate.get("socks5_user")
        and candidate.get("socks5_pass")
    ):
        return jsonify({
            "ok": False,
            "error": "LAN-прокси требует SOCKS5-аутентификацию, логин и пароль",
        })
    previous = {key: _app_settings.get(key) for key in updates}
    _app_settings.update(updates)
    if not _save_settings(_app_settings):
        _app_settings.update(previous)
        return jsonify({"ok": False, "error": "Не удалось сохранить настройки туннеля"})

    _broadcast({"type": "settings_updated", "settings": {
        k: _app_settings.get(k) for k in _TUNNEL_KEYS
    }})
    return jsonify({"ok": True})


@app.route("/api/socks5/regenerate", methods=["POST"])
def api_socks5_regen():
    import secrets, string
    global _app_settings
    chars = string.ascii_letters + string.digits
    user  = "vpn_" + "".join(secrets.choice(chars) for _ in range(8))
    pwd   = "".join(secrets.choice(chars) for _ in range(16))
    previous = (_app_settings.get("socks5_user", ""), _app_settings.get("socks5_pass", ""))
    _app_settings["socks5_user"] = user
    _app_settings["socks5_pass"] = pwd
    if not _save_settings(_app_settings):
        _app_settings["socks5_user"], _app_settings["socks5_pass"] = previous
        return jsonify({"ok": False, "error": "Не удалось сохранить данные SOCKS5"})
    _broadcast({"type": "socks5_creds", "user": user, "pass": pwd})
    return jsonify({"ok": True, "user": user, "pass": pwd})


@app.route("/api/ping-settings", methods=["POST"])
def api_ping_settings():
    global _app_settings
    data = request.get_json(silent=True) or {}
    try:
        updates = {
            key: _normalize_tunnel_setting(key, data[key])
            for key in ("ping_type", "ping_url", "ping_timeout")
            if key in data
        }
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)})
    previous = {key: _app_settings.get(key) for key in updates}
    _app_settings.update(updates)
    if not _save_settings(_app_settings):
        _app_settings.update(previous)
        return jsonify({"ok": False, "error": "Не удалось сохранить настройки пинга"})
    return jsonify({"ok": True})

# ── Zapret API ──────────────────────────────────────
@app.route("/api/zapret/strategies", methods=["GET"])
def api_zapret_strategies():
    return jsonify({"strategies": zapret_engine.get_strategies()})


@app.route("/api/zapret/start", methods=["POST"])
def api_zapret_start():
    global _zapret_running, _zapret_strategy, _zapret_state, _zapret_generation
    data        = request.get_json(silent=True) or {}
    strategy_id = data.get("strategy_id", "general_alt")
    valid_ids = {item["id"] for item in zapret_engine.get_strategies()}
    if strategy_id not in valid_ids:
        return jsonify({"ok": False, "error": "Неизвестная стратегия"})

    with _zapret_engine_lock:
        if _zapret_state != "off":
            return jsonify({"ok": False, "error": "Zapret уже запускается или работает"})
        _zapret_generation += 1
        generation = _zapret_generation
        _zapret_state = "starting"

    def do_start():
        global _zapret_running, _zapret_strategy, _zapret_state
        _broadcast({"type": "zapret_status", "running": False, "strategy": None, "state": "starting"})
        with _zapret_engine_lock:
            if generation != _zapret_generation:
                return
            ok = zapret_engine.start(strategy_id)
            if generation != _zapret_generation:
                if ok:
                    zapret_engine.stop()
                return
            _zapret_running  = ok
            _zapret_strategy = strategy_id if ok else None
            _zapret_state = "on" if ok else "off"
        _broadcast({
            "type":     "zapret_status",
            "running":  ok,
            "strategy": _zapret_strategy,
            "state":    "on" if ok else "err",
        })

    threading.Thread(target=do_start, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/zapret/stop", methods=["POST"])
def api_zapret_stop():
    _stop_zapret_engine()
    _broadcast({"type": "zapret_status", "running": False, "strategy": None, "state": "off"})
    return jsonify({"ok": True})


@app.route("/api/zapret/status", methods=["GET"])
def api_zapret_status():
    return jsonify({
        "running": _zapret_running,
        "strategy": _zapret_strategy,
        "state": _zapret_state,
    })


def run(host="127.0.0.1", port=45678):
    app.run(host=host, port=port, debug=False, use_reloader=False)
