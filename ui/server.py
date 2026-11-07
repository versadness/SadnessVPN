"""
ui/server.py — Sadness VPN Flask backend
"""
import ctypes
import ctypes.wintypes
import ipaddress
import copy
import hashlib
import hmac
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
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, jsonify, request, render_template, send_file
from flask_sock import Sock
from PIL import Image, UnidentifiedImageError

from engine.mihomo import MihomoManager, MIHOMO_VERSION
from engine.core_config import build_proxy_config, controller_headers, ensure_supported
from engine.route_info import observed_app_routes, observed_rule_routes
from engine.connection_health import blocked_message
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
from engine import failover
from engine import platform_info
from ui import profile_state
from ui.zapret_service import ZapretService
from engine.tg_proxy import TgProxyManager
from engine.paths import data_dir
from engine.connection_state import ConnectionCoordinator
from engine.reconnect import Reconnector
from engine.json_store import atomic_write_json
from engine.task_state import BackgroundTaskCoordinator

from engine.diagnostics import journal, export_journal, directory as diagnostics_directory
from engine.session_log import SessionLog
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

# Единственное ядро VPN. Строка показывается в «О программе».
CORE_LABEL = f"Mihomo {MIHOMO_VERSION}"

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
            c.request("GET", "/version", headers=controller_headers())
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

            conn.request("GET", "/connections", headers=controller_headers())
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
                        "Трафик не доходит до сервера — проверьте сервер или выберите другой.",
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


def _start_traffic_monitor(attempt, backend="mihomo"):
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
# Токен локального API. Бэкенд работает от администратора, а проверка адреса
# не отличает оболочку от любой другой программы или другого пользователя
# Windows на этом ПК. Токен создаётся при запуске из Electron (run) и лежит в
# папке данных пользователя; None — запуск без оболочки (разработка, тесты).
_API_TOKEN: str | None = None
_TOKEN_HEADER = "X-Sadness-Token"
_TOKEN_COOKIE = "sadness_token"
# Без токена — только безвредное, что нужно лаунчеру и updater:
# опознать экземпляр, показать окно, узнать статус и закрыть простаивающее
# приложение перед восстановлением. Страница сама по себе данных не содержит.
_TOKEN_EXEMPT = {
    ("GET", "/"), ("GET", "/api/health"), ("GET", "/api/updates/state"),
    ("POST", "/api/shell/show"), ("POST", "/api/updates/close-for-recovery"),
}
_TOKEN_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
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

    if _API_TOKEN and not _token_exempt():
        supplied = request.headers.get(_TOKEN_HEADER) or request.cookies.get(_TOKEN_COOKIE) or ""
        if not hmac.compare_digest(supplied.encode("utf-8", "surrogateescape"), _API_TOKEN.encode("ascii")):
            return jsonify({"ok": False, "error": "Нет доступа к локальному API"}), 401


def _token_exempt() -> bool:
    if (request.method, request.path) in _TOKEN_EXEMPT:
        return True
    return request.method == "GET" and request.path.startswith("/static/")


def _valid_token(value: str) -> bool:
    return 32 <= len(value) <= 128 and set(value) <= _TOKEN_CHARS


def _init_api_token():
    """Включить токен, если оболочка передала путь к его файлу.

    Существующий файл переиспользуется: так переподключившаяся оболочка
    знает токен уже работающего бэкенда. Новый запуск оболочки удаляет файл
    заранее и получает свежий токен.
    """
    global _API_TOKEN
    path = os.environ.get("SADNESS_API_TOKEN_FILE")
    if not path:
        journal.warning("Локальный API работает без токена: бэкенд запущен не из оболочки")
        return
    token = None
    try:
        existing = Path(path).read_text(encoding="ascii").strip()
        if _valid_token(existing):
            token = existing
    except (OSError, UnicodeError):
        pass
    if token is None:
        token = secrets.token_urlsafe(32)
        temporary = path + ".tmp"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="ascii") as stream:
            stream.write(token)
        os.replace(temporary, path)
    _API_TOKEN = token


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


_updates = register_updates(app, lambda: _connection.state == 'off' and zapret_service.state == 'off')


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
    # Выбор сервера во время работы VPN — смена на лету; маршрут сам проверяет
    # состояние подключения (ui/routes/servers.py, _live_switch_state).
    live_switch = request.path == "/api/servers/select"
    if changing_network and not live_switch and (_stopping or _connection.state != "off"):
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
    unmatched = []
    for item in servers:
        pool = identities.get(profile_state.server_fingerprint(item), [])
        if pool:
            item["ui_id"] = pool.pop(0)
        else:
            unmatched.append(item)
    # Провайдер поменял параметр узла (адрес, путь, ключ), но имя и протокол
    # прежние — это тот же сервер. Без этого выбор и маршруты, привязанные к
    # ui_id, терялись при каждой правке на стороне панели. Сопоставляем только
    # однозначные имена: дубликаты не угадываем.
    used = {item.get("ui_id") for item in servers if item.get("ui_id")}
    def remark_key(item):
        return (item.get("protocol", "vless"), item.get("remark", ""))
    old_by_remark = {}
    for item in old:
        if item.get("ui_id") and item.get("ui_id") not in used:
            old_by_remark.setdefault(remark_key(item), []).append(item["ui_id"])
    new_counts = {}
    for item in servers:
        new_counts[remark_key(item)] = new_counts.get(remark_key(item), 0) + 1
    for item in unmatched:
        key = remark_key(item)
        candidates = old_by_remark.get(key, [])
        if key[1] and len(candidates) == 1 and new_counts[key] == 1:
            item["ui_id"] = candidates.pop()
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
# Снимается, когда стартовое обновление подписок закончено (или не нужно).
# Подключение сразу после запуска ждёт его: иначе ядро стартует со старыми
# параметрами сервера (сменённый SNI, flow, убранный транспорт), туннель
# поднимается, но трафик не идёт — до переподключения.
_startup_subscriptions_ready = threading.Event()
_STARTUP_SUBSCRIPTIONS_WAIT = 15.0
_startup_subscriptions_ready.set()  # снимается в run(), пока идёт стартовое обновление


def _subscription_scope(wireguard):
    return ((profile_state.wg_groups, profile_state.save_wireguard_groups, _broadcast_wg_groups)
            if wireguard else
            (profile_state.groups, profile_state.save_proxy_groups, _broadcast_groups))


def _update_one_subscription(target, url, name, is_new, wireguard):
    """Загрузить и атомарно применить одну подписку. Вызывается под _subscription_lock.

    Возвращает итог для интерфейса: result — updated / unchanged / error,
    accepted — число принятых серверов, error — понятная причина без ссылок.
    """
    groups, save, broadcast = _subscription_scope(wireguard)
    label = target.get("name") or name or "подписка"
    _system_log(f"Загрузка подписки «{label}»…", "info")
    if url.lower().startswith("http://"):
        _system_log(f"Подписка «{label}» загружается без шифрования (http://): её содержимое и "
             "ID устройства видны в сети. Попросите у провайдера ссылку https://.", "warn")
    error = ""
    metadata = {}
    servers = None
    not_modified = False
    try:
        fetch = fetch_wg_subscription if wireguard else fetch_subscription
        servers = fetch(url, hwid=_app_settings.get("hwid", ""))
        metadata = getattr(servers, "metadata", {})
        if not servers:
            raise ValueError("Провайдер не передал ни одного поддерживаемого сервера")
    except Exception as exc:
        from engine.subscriptions import SubscriptionError, SubscriptionNotModified
        metadata = getattr(exc, "metadata", {})
        not_modified = isinstance(exc, SubscriptionNotModified) and not is_new
        if not not_modified:
            error = str(exc) if isinstance(exc, SubscriptionError) else "Не удалось прочитать подписку. Проверьте формат ссылки и доступность сервиса."
    previous = copy.deepcopy(target)
    previous_settings = copy.deepcopy(_app_settings)
    previous_indices = (_app_settings["selected_index"], _app_settings["selected_wg_index"])

    def commit():
        if _stopping:
            raise ValueError("VPN отключается; повторите обновление после остановки")
        now = int(time.time())
        if not_modified:
            # 304 — провайдер подтвердил, что список не изменился: это успех,
            # а не пустая подписка.
            target.setdefault("subscription", {}).update(updated_at=now, checked_at=now, error="",
                                                         last_result="unchanged")
        elif error:
            # Последняя рабочая подписка остаётся: меняются только время
            # попытки и причина. updated_at — время последнего успеха.
            target.setdefault("subscription", {}).update({k: v for k, v in metadata.items() if k != "updated_at"})
            target["subscription"].update(error=error, checked_at=now, last_result="error")
        else:
            _replace_group_servers(target, servers, wireguard=wireguard)
            target["subscription"] = {**metadata, "updated_at": now, "checked_at": now, "error": "",
                                      "last_result": "updated"}
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
    outcome = {"id": target.get("id"), "name": target.get("name") or label,
               "wireguard": wireguard, "accepted": 0, "error": ""}
    if error:
        _system_log(f"«{label}»: {error}", "err")
        return {**outcome, "result": "error", "error": error}
    if not_modified:
        _system_log(f"Подписка «{label}» не изменилась", "ok")
        return {**outcome, "result": "unchanged", "accepted": len(target.get("servers") or [])}
    rejected = metadata.get("rejected") or []
    summary = f"Подписка «{target.get('name') or label}» обновлена: принято {len(servers)}"
    if metadata.get("received"):
        summary += f" из {metadata['received']}"
    _system_log(summary, "ok")
    for item in rejected[:10]:
        _system_log(f"«{item.get('name')}» не импортирован: {item.get('reason')}", "warn")
    # Провайдер мог убрать сервер, на который ссылался маршрут.
    _repair_saved_routes("обновление подписки")
    return {**outcome, "result": "updated", "accepted": len(servers)}


def _run_subscription_jobs(jobs, auto=False, done_event=None):
    """Выполнить обновления строго по очереди в одном фоновом потоке.

    Раньше «Обновить подписки» запускал запросы параллельно, бэкенд принимал
    только первый, а остальные получали 409 — обновлялась лишь первая группа.

    Интерфейс получает ход очереди (subscription_progress), итог каждой
    подписки (subscription_result) и общий итог (subscriptions_done) — уже
    после сохранения. Старт задачи — это не успех: сообщение об успехе
    показывается только по итогу.
    """
    if not _subscription_lock.acquire(blocking=False):
        return jsonify(ok=False, error="Подписка уже обновляется"), 409

    def work():
        results = []
        try:
            _broadcast({"type": "subscription_busy", "busy": True})
            for position, job in enumerate(jobs, 1):
                target = job[0]
                _broadcast({"type": "subscription_progress", "id": target.get("id"),
                            "name": target.get("name") or job[2] or "Подписка",
                            "position": position, "total": len(jobs)})
                try:
                    outcome = _update_one_subscription(*job)
                except Exception as exc:
                    reason = str(exc) if isinstance(exc, ValueError) else "ошибка сохранения данных"
                    _system_log("Не удалось применить обновление подписки: " + reason, "err")
                    outcome = {"id": target.get("id"), "name": target.get("name") or job[2] or "Подписка",
                               "wireguard": job[4], "result": "error", "accepted": 0, "error": reason}
                results.append(outcome)
                _broadcast({"type": "subscription_result", **outcome})
        finally:
            _subscription_lock.release()
            if done_event is not None:
                done_event.set()
            _broadcast({"type": "subscription_busy", "busy": False})
            _broadcast({
                "type": "subscriptions_done", "auto": auto, "total": len(jobs),
                "updated": sum(r["result"] == "updated" for r in results),
                "unchanged": sum(r["result"] == "unchanged" for r in results),
                "failed": len(jobs) - sum(r["result"] in ("updated", "unchanged") for r in results),
                "results": results,
            })

    try:
        threading.Thread(target=work, daemon=True).start()
    except Exception:
        _subscription_lock.release()
        raise
    return jsonify(ok=True, queued=len(jobs))


def _start_subscription_update(data, refresh=False, wireguard=False):
    groups, _save, _broadcast_fn = _subscription_scope(wireguard)
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
    return _run_subscription_jobs([(target, url, name, is_new, wireguard)])


def _start_subscription_refresh_all(auto=False, done_event=None):
    """Все подписки (VLESS и WireGuard) одной очередью."""
    jobs = [(g, g["url"], "", False, wireguard)
            for wireguard in (False, True)
            for g in _subscription_scope(wireguard)[0]
            if str(g.get("url") or "").startswith(("https://", "http://"))]
    if not jobs:
        return jsonify(ok=False, error="Нет подписок для обновления"), 400
    return _run_subscription_jobs(jobs, auto=auto, done_event=done_event)

def _autoupdate_subscriptions_on_start(delay=1.0):
    """Обновить все подписки при запуске приложения, если это не выключено.

    Подключение, начатое в это время, ждёт окончания обновления
    (_startup_subscriptions_ready) и стартует уже со свежими параметрами.
    """
    try:
        if not _app_settings.get("sub_autoupdate", True):
            return
        has_subscriptions = any(
            str(g.get("url") or "").startswith(("https://", "http://"))
            for wireguard in (False, True) for g in _subscription_scope(wireguard)[0])
        if not has_subscriptions:
            return
        time.sleep(delay)
        _system_log("Автообновление подписок при запуске", "info")
        with app.app_context():
            result = _start_subscription_refresh_all(auto=True, done_event=_startup_subscriptions_ready)
        response = result[0] if isinstance(result, tuple) else result
        if not (response.get_json() or {}).get("ok"):
            _system_log("Автообновление подписок пропущено: " + str((response.get_json() or {}).get("error")), "warn")
            _startup_subscriptions_ready.set()
    except Exception:
        _startup_subscriptions_ready.set()
        raise


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


# Журнал последней сессии подключения — отдельно от системного журнала
# (diagnostics/application.log). Жизненный цикл описан в engine/session_log.py.
session_log = SessionLog(diagnostics_directory)
_connect_request_lock = threading.Lock()


def _emit(msg, tag, session):
    _broadcast({"type": "log", "msg": msg, "tag": tag, "session": session})
    if tag == "err" and _error_notifications.should_notify(msg):
        _broadcast({"type": "operation_error", "message": msg})


def _journal(msg, tag):
    journal.log({"err": 40, "warn": 30}.get(tag, 20), str(msg))


def _log(msg, tag="log"):
    """Запись приложения: во время сессии подключения — в её журнал,
    вне сессии — в системный журнал."""
    in_session = session_log.write(msg, tag)
    if not in_session:
        _journal(msg, tag)
    _emit(msg, tag, in_session)


def _system_log(msg, tag="log"):
    """Событие приложения, не относящееся к подключению (подписки, Zapret,
    Telegram-прокси): только системный журнал, даже во время сессии."""
    _journal(msg, tag)
    _emit(msg, tag, False)


def _session_logger(generation):
    """Запись от имени конкретной сессии. Движки запоминают её при старте,
    поэтому запоздавшая строка прошлой сессии не попадает в новую."""
    def log(msg, tag="log"):
        if session_log.write(msg, tag, generation):
            _emit(msg, tag, True)
        else:
            # Сессия уже закрыта или сменилась: запись остаётся только в
            # системном журнале и в интерфейс текущей сессии не попадает.
            _journal(f"[прошлая сессия] {msg}", tag)
    return log


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


def _repair_saved_routes(reason: str) -> dict:
    """Свести маршруты с актуальными серверами и показать это пользователю.

    Одно уведомление на всю починку, а не по одному на каждое правило.
    """
    report = profile_state.repair_saved_routes()
    if not report["changed"]:
        return report
    _log(f"{report['message']} ({reason})", "info")
    if report.get("saved") is False:
        _log("Восстановленная маршрутизация не записана на диск — правила можно исправить вручную", "warn")
    _broadcast({"type": "apps_config", "config": profile_state.apps_config})
    _broadcast({"type": "routing_repaired", "message": report["notice"], "total": report["total"]})
    return report


def verify_routing_with_core(candidate) -> tuple:
    """Транзакционная проверка маршрутов средствами самого Mihomo.

    Конфигурация собирается из кандидата и отдаётся ядру на `-t`. Пока ядро не
    приняло её, на диск ничего не пишется: пользователь не должен увидеть
    «сохранено и применено» там, где ядро откажется стартовать.

    Отсутствие выбранного сервера — не ошибка правил: проверять нечего, и
    редактировать маршруты до выбора сервера мы не запрещаем.
    """
    server = _get_selected_server()
    if not server or _app_settings.get("active_protocol") == "wg":
        return True, ""
    from engine.app_routes import assignments, build_multi_route_config
    from engine.routing_rules import resolve_rules
    try:
        ensure_supported(server)
        routes = resolve_rules(candidate.get("rules", []), profile_state.groups) +             assignments(candidate.get("apps", []), profile_state.groups)
        builder = (lambda node, **kwargs: build_multi_route_config(node, routes, **kwargs))             if routes else build_proxy_config
        config = builder(
            server,
            socks_port=_app_settings["socks"],
            http_port=_app_settings["http"],
            clash_port=_CLASH_PORT_DEFAULT,
            routing_mode=candidate.get("mode", "all"),
            routed_apps=[a["exe"] for a in candidate.get("apps", [])
                         if a.get("enabled", True) and a.get("destination", "default") == "default"],
            **_tunnel_kwargs(),
        )
    except ValueError as exc:
        return False, str(exc)
    # TUN и Clash API не поднимаются: проверяется только сама конфигурация.
    config["tun"]["enable"] = False
    config.pop("external-controller", None)
    config.pop("external-controller-cors", None)
    config.pop("secret", None)
    ok, message = vpn_engine.validate(config)
    if ok:
        return True, ""
    return False, "Ядро отклонило конфигурацию маршрутов. " + (message or "")


def _active_vpn_mode():
    """Режим маршрутизации, если VPN действительно работает, иначе None.

    Нужен Zapret: при полном туннеле обход применяется не ко всему ПК, и
    интерфейс обязан сказать это прямо.
    """
    if not (_connection.connected or vpn_engine.running or awg_engine.running):
        return None
    if _app_settings.get("active_protocol") == "wg" or awg_engine.running:
        return "all"
    return (profile_state.apps_config or {}).get("mode", "all")


def _vpn_endpoints() -> list:
    """Серверы, к которым приложение действительно подключается.

    Только выбранный сервер и серверы явных маршрутов: резолвить всю подписку
    ради списка исключений Zapret и долго, и незачем.
    """
    servers = []
    for selected in (_get_selected_server(), _get_selected_wg_server()):
        if selected:
            servers.append(selected)
    lookup = {
        server.get("ui_id"): server
        for group in profile_state.groups or []
        for server in group.get("servers", []) or []
        if isinstance(server, dict) and server.get("ui_id")
    }
    config = profile_state.apps_config or {}
    for item in list(config.get("apps") or []) + list(config.get("rules") or []):
        destination = item.get("destination") if isinstance(item, dict) else None
        if isinstance(destination, str) and destination.startswith("server:"):
            server = lookup.get(destination[len("server:"):])
            if server is not None and server not in servers:
                servers.append(server)
    return servers


def _protect_vpn_from_zapret():
    """Работающий обход не должен обрабатывать соединение с VPN-сервером."""
    try:
        zapret_service.protect_vpn(_vpn_endpoints())
    except Exception:
        journal.exception("Не удалось обновить исключения Zapret перед подключением")
        _log("Zapret: не удалось исключить адрес VPN-сервера из обработки. "
             "Если соединение нестабильно, перезапустите обход.", "warn")


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
    generation = session_log.generation
    previous = _connection.cancel(_reset_connection_state)
    if previous != "off":
        _broadcast({"type": "status", "state": "off"})
    if previous == "on" and not _stopping and _app_settings.get("reconnect") is True:
        # Переподключение продолжает ту же сессию журнала.
        _reconnector.start()
    else:
        session_log.close(generation)


def _reconnect_selected():
    # reconnect: внутреннее переподключение не начинает новую сессию журнала.
    with app.test_request_context('/api/connect', method='POST',
                                  json={'protocol': _app_settings["active_protocol"], 'reconnect': True}):
        result = api_connect()
        if isinstance(result, tuple): result = result[0]
        return result.get_json().get('ok') is True


_reconnector = Reconnector(_reconnect_selected, lambda: _connection.state,
    lambda: _app_settings.get('reconnect') is True and not _stopping,
    lambda message: _log(message, 'warn'))


vpn_engine = MihomoManager(
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


zapret_service = ZapretService(log_callback=_system_log, broadcast=_broadcast)
zapret_engine = zapret_service.engine
tg_proxy_engine = TgProxyManager(log_callback=_system_log,
                                 exit_callback=lambda error: _tg_proxy_routes.handle_exit(error))


def _recover_after_crash():
    """Разобраться с движками, пережившими аварийное завершение прошлого запуска.

    Если порт бэкенда занят, работает другой экземпляр приложения: его
    процессы не трогаем.
    """
    global _vpn_error
    if not vpn_engine._port_free(45678):
        return
    from engine import owned_process
    mihomo_paths = (vpn_engine._core_path(),)
    if os.name != "nt":
        # На Linux ядро работает из пакета или из копии с правами (engine/linux_core.py).
        from engine.linux_core import INSTALLED_CORE
        mihomo_paths += (INSTALLED_CORE,)
    for name, executable, label in (("mihomo", mihomo_paths, "Mihomo"),
                                    ("winws", zapret_engine._winws_path(), "winws")):
        if owned_process.reap(name, executable):
            _log(f"{label} остался от прошлого запуска после сбоя и остановлен", "warn")
    if awg_engine.has_owned_service():
        # Туннель AWG поднят, хотя приложение его не запускало: показываем
        # ошибку, чтобы «Отключить» было доступно и сняло службу.
        _vpn_error = True
        _log("Служба AmneziaWG осталась от прошлого запуска. Нажмите «Отключить», "
             "чтобы остановить туннель.", "warn")


try:
    _recover_after_crash()
except Exception:
    journal.exception("Проверка движков после сбоя не удалась")


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
    backend: str = "mihomo",
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


def _finish_vpn_attempt(attempt: int, config: dict, server_name: str, session=None):
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
        _log("Подключение не установлено", "err")
        session_log.close(session)
        _broadcast({"type": "status", "state": "off"})


def _finish_awg_attempt(attempt: int, server: dict, server_name: str, session=None):
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
        session_log.close(session)
        _broadcast({"type": "status", "state": "off"})


def _reset_connection_state():
    global _ping_value, _ping_color, _conn_server, _vpn_error
    _vpn_error = False
    _live_servers.clear()
    _route_state.update(name=None, backup=False, failover=False)
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
        "coreVersions"   : f"Mihomo {MIHOMO_VERSION}",
        "tunnelSettings" : {k: _app_settings.get(k) for k in _TUNNEL_KEYS},
        "appsConfig"      : profile_state.apps_config,
        "hwid"            : _app_settings.get("hwid", ""),
        "stats"           : stats_tracker.get_snapshot(),
        "zapretRunning"   : zapret_service.running,
        "zapretState"     : zapret_service.state,
        "zapretStrategy"  : zapret_service.strategy,
        "zapretStrategies": zapret_service.strategies(),
        "zapretGameFilter": _app_settings.get("zapret_game_filter"),
        "zapretGameFilterSummary": zapret_service.game_filter_summary(
            _app_settings.get("zapret_game_filter"),
            _app_settings.get("zapret_strategy"),
        ),
        "zapretCoverage"  : zapret_service.coverage(
            _app_settings.get("zapret_game_filter"),
            _app_settings.get("zapret_strategy"),
            _active_vpn_mode(),
        ),
        "zapretSelected"  : _app_settings.get("zapret_strategy"),
        "tgProxy"         : _tg_proxy_routes.status(),
        "appVersion"       : APP_VERSION,
        "platform"         : platform_info.features(),
        "engineVersion"    : MIHOMO_VERSION,
    }))
    try:
        while True:
            ws.receive()
    except Exception:
        pass
    with _ws_lock:
        if ws in _ws_clients:
            _ws_clients.remove(ws)

# ── Смена сервера на лету и резерв (engine/failover.py) ──────────────
# Серверы, которые есть в работающем ядре: {имя в ядре: сервер}. Пусто, пока
# VPN не подключён или работает не через Mihomo (AmneziaWG, WireGuard).
_live_servers: dict = {}
# Через какой сервер сейчас реально идёт трафик: (имя в ядре, резерв ли).
_route_state = {"name": None, "backup": False, "failover": False}


def _clash(method, path, body=None, timeout=6.0):
    """Запрос к API работающего ядра. (код, JSON или None)."""
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", _clash_port, timeout=timeout)
    try:
        payload = json.dumps(body).encode() if body is not None else None
        headers = controller_headers()
        if payload:
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=payload, headers=headers)
        response = conn.getresponse()
        raw = response.read(65536)
        try:
            return response.status, json.loads(raw) if raw else None
        except ValueError:
            return response.status, None
    finally:
        conn.close()


def _recheck_route():
    """Немедленная проверка группы: ядро переводит трафик на живой сервер."""
    query = urllib.parse.urlencode({"url": "https://www.gstatic.com/generate_204", "timeout": 5000})
    try:
        _clash("GET", f"/group/{failover.MAIN_GROUP}/delay?{query}", timeout=8.0)
    except OSError:
        pass


def _current_route():
    """(имя в ядре, резерв ли) — сервер, через который сейчас идёт трафик."""
    _, main = _clash("GET", f"/proxies/{failover.MAIN_GROUP}")
    _, manual = _clash("GET", f"/proxies/{failover.MANUAL_GROUP}")
    if not main or not manual:
        return None
    if main.get("now") == failover.BACKUP_GROUP:
        _, backup = _clash("GET", f"/proxies/{failover.BACKUP_GROUP}")
        return ((backup or {}).get("now"), True)
    return (manual.get("now"), False)


def _route_label(name):
    server = _live_servers.get(name) or {}
    return stripped_remark(server.get("remark", "")) or "сервер"


def _publish_route(route):
    """Сообщить о смене фактического сервера: журнал сессии и интерфейс."""
    name, backup = route
    previous = _route_state["name"]
    _route_state.update(name=name, backup=backup)
    if previous is None and not backup:
        return
    selected = _get_selected_server()
    selected_label = stripped_remark((selected or {}).get("remark", "")) or "выбранный"
    if backup:
        message = f"Сервер «{selected_label}» не отвечает — трафик переведён на запасной «{_route_label(name)}»"
        _log(message, "warn")
        # Старые соединения висят на мёртвом сервере до таймаута — закрываем,
        # чтобы приложения (стрим, браузер) сразу переподключились через запасной.
        try:
            _clash("DELETE", "/connections")
        except OSError:
            pass
    else:
        message = f"Трафик снова идёт через выбранный сервер «{_route_label(name)}»"
        _log(message, "ok")
    _broadcast({"type": "active_server", "name": _route_label(name), "backup": backup,
                "selected": selected_label, "message": message})


def _switch_live_server(server):
    """Сменить сервер без переподключения. (ok, ошибка)."""
    name = failover.proxy_name(server)
    if name not in _live_servers:
        return False, ("Этот сервер появился после подключения или не поддерживается ядром — "
                       "переподключитесь, чтобы выбрать его")
    try:
        status, _ = _clash("PUT", f"/proxies/{failover.MANUAL_GROUP}", {"name": name})
        if status not in (200, 204):
            return False, f"Ядро не переключило сервер (код {status})"
    except OSError as exc:
        return False, f"Ядро не отвечает: {exc}"
    # PUT already committed the switch. A cleanup timeout cannot turn that
    # success into a rejection: selection and UI must follow the actual core.
    try:
        _clash("DELETE", "/connections")
    except OSError:
        _log("Сервер переключён, но закрыть прежние соединения не удалось", "warn")
    global _conn_server
    _conn_server = server.get("remark", "")
    _route_state.update(name=name, backup=False)
    vpn_engine.health.reset()
    _log(f"Сервер переключён без переподключения: «{stripped_remark(server.get('remark', ''))}»", "ok")
    threading.Thread(target=_recheck_route, daemon=True).start()
    _broadcast({"type": "status", "state": "on", "server": _conn_server, "core": vpn_engine.name})
    return True, None


def _live_switch_state():
    """Можно ли сейчас менять сервер: 'off' — VPN выключен (обычный выбор),
    'live' — работает через Mihomo (смена на лету), иначе — текст отказа."""
    state = "stopping" if _stopping else _connection.state
    if state == "off":
        return "off"
    if state != "on":
        return "Дождитесь завершения подключения или отключения"
    if _app_settings["active_protocol"] == "wg" or not _live_servers:
        return "Сейчас подключён WireGuard: сменить сервер на лету можно только в режиме TUN"
    return "live"


def stripped_remark(text):
    return " ".join(str(text or "").split())


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

        health = None if _app_settings["active_protocol"] == "wg" else vpn_engine.health.check()
        route = None
        if _live_servers:
            if health and health.get("blocked") and _route_state.get("failover"):
                # Не ждать интервала проверки ядра: перевести трафик сразу.
                _recheck_route()
            try:
                route = _current_route()
            except OSError:
                route = None

        def publish():
            global _ping_value, _ping_color
            _ping_value = value
            _ping_color = color
            _broadcast({"type": "ping", "value": value, "color": color})
            if health and health.get("blocked"):
                if _route_state.get("failover"):
                    # Резерв подхватит трафик; отдельное уведомление придёт
                    # при фактическом переключении.
                    _log(blocked_message(_conn_server or "выбранный", health)
                         + " Включён резерв: трафик переводится на запасной сервер.", "warn")
                else:
                    message = blocked_message(_conn_server or "выбранный", health, _alternative_servers())
                    _log(message, "err")
                    _broadcast({"type": "connection_health", "state": "blocked", "message": message})
                    _broadcast({"type": "operation_error", "message": message})
            elif health and health.get("recovered"):
                _log("Сервер снова принимает соединения", "ok")
                _broadcast({"type": "connection_health", "state": "ok"})
            if route and route[0] and (route[0], route[1]) != (_route_state["name"], _route_state["backup"]):
                _publish_route(route)

        if stop_event.is_set() or not _connection.run_if_connected(
            attempt,
            publish,
        ):
            break
        stop_event.wait(timeout=5.0)


def _alternative_servers(limit=3):
    """Серверы той же подписки на другом транспорте: при блокировке одного
    протокола (TCP/XHTTP) другой (QUIC/HY2) часто продолжает работать."""
    selected = _get_selected_server()
    if not selected:
        return ""
    transport = lambda item: "quic" if item.get("protocol") == "hysteria2" else item.get("type", "tcp")
    group = next((g for g in profile_state.groups if g["id"] == _app_settings["selected_group"]), None)
    names = [item.get("remark", "") for item in (group or {}).get("servers", [])
             if item is not selected and transport(item) != transport(selected) and item.get("remark")]
    return ", ".join(names[:limit])


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
    if _app_settings.get("ping_type") in ("http_get", "http_head") and (_stopping or _connection.state != "off"):
        # Проверочное ядро без TUN при активном VPN ушло бы в туннель основного
        # сервера, и все серверы показали бы его задержку.
        return jsonify(ok=False, error="HTTP-проверка через серверы доступна при отключённом VPN. "
                                       "TCP- и ICMP-пинг работают всегда."), 409
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
    """Новая попытка подключения.

    Нажатие «Подключить» и автоподключение начинают новую сессию журнала;
    внутреннее переподключение ядра (reconnect) продолжает текущую. Повторный
    запрос во время подключения отклоняется до очистки журнала.
    """
    if _stopping:
        return jsonify(ok=False, error="Дождитесь завершения отключения"), 409
    if _connection.state != "off":
        return jsonify(ok=False, error="Подключение уже активно или выполняется"), 409
    data = request.get_json(silent=True) or {}
    if not _startup_subscriptions_ready.is_set() and data.get("reconnect") is not True:
        _broadcast({"type": "status", "state": "connecting"})
        _system_log("Ждём обновления подписок, чтобы подключиться со свежими настройками сервера", "info")
        if not _startup_subscriptions_ready.wait(_STARTUP_SUBSCRIPTIONS_WAIT):
            _system_log("Подписки обновляются слишком долго — подключаемся с сохранёнными", "warn")
        if _stopping or _connection.state != "off":
            return jsonify(ok=False, error="Подключение уже активно или выполняется"), 409
    if not _connect_request_lock.acquire(blocking=False):
        return jsonify(ok=False, error="Подключение уже выполняется"), 409
    try:
        # Повторная проверка под замком: два почти одновременных нажатия не
        # должны очистить журнал дважды.
        if _stopping or _connection.state != "off":
            return jsonify(ok=False, error="Подключение уже активно или выполняется"), 409
        generation = _begin_connection_session(data)
        try:
            return _connect_attempt(data, generation)
        except Exception as exc:
            # Внутренний сбой подготовки: причина остаётся в журнале сессии,
            # а сама сессия закрывается, чтобы в неё не попадали посторонние записи.
            _log(f"Внутренняя ошибка подготовки подключения: {exc}", "err")
            session_log.close(generation)
            raise
    finally:
        _connect_request_lock.release()


def _begin_connection_session(data):
    """Начать (или продолжить при переподключении) сессию журнала до первой её записи."""
    if data.get("reconnect") is True and session_log.open:
        generation = session_log.generation
    else:
        reason = ("автоподключение" if data.get("auto") is True
                  else "автоматическое переподключение" if data.get("reconnect") is True
                  else "подключение вручную")
        generation = session_log.start(reason)
        _broadcast({"type": "session_log_reset", "session": generation})
    logger = _session_logger(generation)
    for engine in (vpn_engine, awg_engine):
        # set_log_sink сохраняет служебную обёртку движка (готовность TUN,
        # здоровье соединения); у AmneziaWG её нет — там приёмник меняется прямо.
        if hasattr(engine, "set_log_sink"):
            engine.set_log_sink(logger)
        else:
            engine.log_cb = logger
    return generation


def _fail_before_attempt(generation, message, status=None):
    """Попытка не началась: причина остаётся в журнале до следующего подключения."""
    _log(message, "err")
    session_log.close(generation)
    response = jsonify(ok=False, error=message)
    return (response, status) if status else response


def _connect_attempt(data, generation):
    proto = data.get("protocol", _app_settings["active_protocol"])

    if proto == "wg":
        server = _get_selected_wg_server()
        if not server:
            return _fail_before_attempt(generation, "WG сервер не выбран")
        mode        = profile_state.apps_config.get("mode", "all")
        routed_exes = _get_routed_exes()
        is_awg = server.get("is_awg", False)
        cfg = None
        # Обычный WireGuard идёт через Mihomo, поэтому правила и индивидуальные
        # серверы работают так же, как в TUN. AmneziaWG — системная служба на
        # весь компьютер: правила к ней не применить, но и мешать подключению
        # они не должны — пользователь об этом предупреждается.
        has_custom_routes = any(r.get("enabled", True) for r in profile_state.apps_config.get("rules", [])) or any(
            a.get("enabled") is not False and a.get("destination", "default") != "default"
            for a in profile_state.apps_config.get("apps", []))
        if not is_awg:
            from engine.app_routes import apply_routes, assignments
            from engine.routing_rules import resolve_rules
            _repair_saved_routes("подготовка подключения")
            try:
                _ensure_local_proxy_ports()
                explicit_routes = resolve_rules(profile_state.apps_config.get("rules", []), profile_state.groups) + \
                    assignments(profile_state.apps_config.get("apps", []), profile_state.groups)
                cfg = apply_routes(build_wg_tun_config(
                    server,
                    socks_port   = _app_settings["socks"],
                    http_port    = _app_settings["http"],
                    clash_port   = _ensure_clash_port(),
                    routing_mode = mode,
                    routed_apps  = routed_exes,
                    **_tunnel_kwargs(),
                ), explicit_routes)
            except ValueError as exc:
                _log("Не удалось подготовить подключение: " + str(exc), "err")
                session_log.close(generation)
                return jsonify(ok=False, error=str(exc)), 422
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
                    if has_custom_routes:
                        _log("Правила маршрутизации не применяются к AmneziaWG: весь трафик "
                             "идёт через туннель AWG. Они снова заработают в TUN и обычном WireGuard.",
                             "warn")

            if not _connection.run_if_current(attempt, announce):
                return
            _protect_vpn_from_zapret()
            if is_awg:
                _finish_awg_attempt(attempt, server, server.get("remark", ""), session=generation)
            else:
                _finish_vpn_attempt(attempt, cfg, server.get("remark", ""), session=generation)

        threading.Thread(target=do_connect_wg, daemon=True).start()
        if is_awg and has_custom_routes:
            return jsonify(ok=True, warning="Правила маршрутизации не применяются к AmneziaWG — весь трафик пойдёт через AWG")
        return jsonify({"ok": True})

    else:  # vless / ss / trojan / hysteria2
        server = _get_selected_server()
        if not server:
            return _fail_before_attempt(generation, "Сервер не выбран")
        # Последняя защита перед сборкой: подписка могла потерять сервер уже
        # после того, как маршрут был сохранён. Чиним и продолжаем — повторно
        # жать «Подключить» пользователь не должен.
        _repair_saved_routes("подготовка подключения")
        mode        = profile_state.apps_config.get("mode", "all")
        routed_exes = _get_routed_exes()
        from engine.app_routes import assignments, build_multi_route_config
        from engine.routing_rules import resolve_rules
        try:
            _ensure_local_proxy_ports()
            explicit_routes = resolve_rules(profile_state.apps_config.get("rules", []), profile_state.groups) + \
                assignments(profile_state.apps_config.get("apps", []), profile_state.groups)
            ensure_supported(server)
            config_builder = (lambda server, **kwargs: build_multi_route_config(server, explicit_routes, **kwargs)) if explicit_routes else build_proxy_config
            cfg = config_builder(
                server,
                socks_port   = _app_settings["socks"],
                http_port    = _app_settings["http"],
                clash_port   = _ensure_clash_port(),
                routing_mode = mode,
                routed_apps  = routed_exes,
                **_tunnel_kwargs(),
            )
            # Все серверы подписок попадают в ядро: сервер меняется на лету,
            # а при отказе выбранного трафик уходит на запасной (engine/failover.py).
            live = failover.apply_server_groups(
                cfg, server, profile_state.groups,
                failover=_app_settings.get("auto_failover", True) is True,
                mux=_app_settings.get("mux") is True,
            )
            from engine.core_config import apply_tls_fingerprint
            apply_tls_fingerprint(cfg, _app_settings.get("tls_fingerprint", "firefox"))
            backups = next((g["proxies"] for g in cfg["proxy-groups"]
                            if g["name"] == failover.BACKUP_GROUP), [])
        except ValueError as exc:
            # Отказ пользовательской конфигурации, а не сбой сервиса: раньше
            # он уходил безымянным HTTP 500 и не попадал в журнал вовсе.
            _log("Не удалось подготовить подключение: " + str(exc), "err")
            session_log.close(generation)
            return jsonify(ok=False, error=str(exc)), 422
        proto_label = server.get("protocol", "vless").upper()
        attempt = _connection.begin()
        if attempt is None:
            error = "Уже подключено" if _connection.connected else "Подключение уже выполняется"
            return jsonify({"ok": False, "error": error})

        def do_connect_vless():
            def announce():
                _broadcast({"type": "status", "state": "connecting"})
                _log(f"Подключение к {server['remark']} [{proto_label}] ...", "info")
                routes_note = " (индивидуальные маршруты)" if explicit_routes else ""
                _log(f"Ядро: Mihomo {MIHOMO_VERSION}{routes_note} | транспорт: {server.get('type', 'tcp')} | Reality: {'да' if server.get('security') == 'reality' else 'нет'}", "info")
                _log(f"Режим: TUN | маршрутизация: {mode} ({len(routed_exes)} приложений)", "info")
                _live_servers.clear()
                _live_servers.update(live)
                _route_state.update(name=None, backup=False, failover=bool(backups))
                if backups:
                    names = ", ".join(f"«{stripped_remark(live[name].get('remark', ''))}»" for name in backups)
                    _log(f"Резерв включён: при отказе сервера трафик перейдёт на запасной — {names}", "info")
                else:
                    _log("Резерв выключен или запасных серверов нет", "info")
                if not zapret_service.running and zapret_engine._foreign_winws_running():
                    # Исключения адресов VPN-серверов пишутся только в списки
                    # собственного winws; сторонний экземпляр (служба zapret)
                    # их не читает и может обрабатывать соединения с сервером.
                    _log("Запущен сторонний winws (например, служба zapret): Sadness VPN не может исключить "
                         "из его обработки адрес VPN-сервера. Если соединение нестабильно, добавьте адрес "
                         "сервера в ipset-exclude этой сборки zapret или остановите её.", "warn")
                if mode == "whitelist" and routed_exes:
                    shown = ", ".join(routed_exes[:5]) + ("..." if len(routed_exes) > 5 else "")
                    _log(f"Через VPN: {shown}", "info")
                    _log("⚠ Браузеры и другие приложения работают НАПРЯМУЮ — без VPN", "warn")

            if not _connection.run_if_current(attempt, announce):
                return
            _protect_vpn_from_zapret()
            _finish_vpn_attempt(attempt, cfg, server.get("remark", ""), session=generation)

        threading.Thread(target=do_connect_vless, daemon=True).start()
        return jsonify({"ok": True})


@app.route("/api/disconnect", methods=["POST"])
def api_disconnect():
    global _stopping
    _reconnector.cancel()
    if not _disconnect_lock.acquire(blocking=False):
        return jsonify(ok=True)
    _stopping = True
    generation = session_log.generation
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
            # Отключение записано — сессия завершена; журнал остаётся для
            # просмотра и копирования до следующего подключения.
            session_log.close(generation)
            _stopping = False
            _disconnect_lock.release()
    threading.Thread(target=finish, daemon=True).start()
    return jsonify(ok=True)






# Роуты статистики и диагностики живут в ui/routes/system.py.
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
    try:
        tg_proxy_engine.stop(quiet=True)
    except Exception:
        journal.exception("Не удалось завершить Telegram-прокси")


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
from ui.routes import tg_proxy as _tg_proxy_routes  # noqa: E402

_system_routes.init(broadcast=_broadcast, session_log=session_log)
app.register_blueprint(_system_routes.bp)

_zapret_routes.init(service=zapret_service, broadcast=_broadcast, log=_system_log,
                    vpn_servers=_vpn_endpoints, vpn_mode=_active_vpn_mode)
app.register_blueprint(_zapret_routes.bp)

_tg_proxy_routes.init(manager=tg_proxy_engine, broadcast=_broadcast, log=_system_log,
                      reserved_ports=lambda: {
                          _app_settings["socks"]: "SOCKS5-прокси Sadness VPN",
                          _app_settings["http"]: "HTTP-прокси Sadness VPN",
                          _clash_port: "API ядра Mihomo",
                      })
app.register_blueprint(_tg_proxy_routes.bp)

_appearance_routes.init(broadcast=_broadcast)
app.register_blueprint(_appearance_routes.bp)

_settings_routes.init(broadcast=_broadcast, log=_log,
                      tunnel_busy=lambda: _stopping or _connection.state != "off")
app.register_blueprint(_settings_routes.bp)

_servers_routes.init(_log=_Late("_log"), _broadcast_groups=_Late("_broadcast_groups"),
                     _groups_for_ui=_Late("_groups_for_ui"),
                     _ensure_manual_group=_Late("_ensure_manual_group"),
                     _start_subscription_update=_Late("_start_subscription_update"),
                     _start_subscription_refresh_all=_Late("_start_subscription_refresh_all"),
                     _repair_saved_routes=_Late("_repair_saved_routes"),
                     _save_settings=_Late("_save_settings"),
                     _live_switch_state=_Late("_live_switch_state"),
                     _switch_live_server=_Late("_switch_live_server"))
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
                  _connection=_Late("_connection"), save_apps=_Late("save_apps"),
                  verify_with_core=_Late("verify_routing_with_core"))
app.register_blueprint(_apps_routes.bp)


def run(host="127.0.0.1", port=45678):
    _init_api_token()
    threading.Thread(target=_tg_proxy_routes.autostart, daemon=True,
                     name="tg-proxy-autostart").start()
    _startup_subscriptions_ready.clear()
    threading.Thread(target=_autoupdate_subscriptions_on_start, daemon=True,
                     name="subscriptions-autoupdate").start()
    app.run(host=host, port=port, debug=False, use_reloader=False)
