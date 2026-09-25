"""Изолированная проверка сервера настоящим запросом через outbound Mihomo.

Открытый TCP-порт не означает работающий транспорт: XHTTP может отвечать на
443 и при этом не согласовать сессию. Поэтому здесь поднимается отдельный
экземпляр ядра ровно с одним прокси, без TUN и без обхода локальных сетей, и
через него выполняется настоящий HTTP-запрос.

Изоляция обязательна: проверка не должна случайно пройти через основной
сервер или DIRECT. Поэтому:

* конфигурация содержит единственный прокси и единственное правило MATCH;
* правила обхода локальных сетей не добавляются;
* слушатель поднимается на собственном свободном порту;
* Clash API и TUN выключены, права администратора не нужны.

Наружу отдаётся состояние и короткое объяснение. Пароли, UUID, ключи и ссылки
подписки в результат и в журнал не попадают.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

from engine.core_config import _mihomo_proxy, ensure_supported
from engine.mihomo import _core_errors
from engine.paths import bin_path, data_dir

# Состояния разделены намеренно: «импортирован», «конфигурация проверена»,
# «порт доступен» и «соединение подтверждено» — это разные факты.
IMPORTED = "imported"
UNSUPPORTED = "unsupported"
CONFIG_REJECTED = "config_rejected"
UNREACHABLE = "unreachable"
TLS_ERROR = "tls_error"
TRANSPORT_ERROR = "transport_error"
AUTH_ERROR = "auth_error"
CONNECTED = "connected"

LABELS = {
    UNSUPPORTED: "Конфигурация не поддерживается ядром",
    CONFIG_REJECTED: "Ядро отклонило конфигурацию сервера",
    UNREACHABLE: "Адрес или порт недоступны",
    TLS_ERROR: "Ошибка TLS или REALITY",
    TRANSPORT_ERROR: "Ошибка транспорта",
    AUTH_ERROR: "Сервер отклонил авторизацию",
    CONNECTED: "Соединение через сервер подтверждено",
}

DEFAULT_URL = "http://cp.cloudflare.com/generate_204"
_TIMEOUT = 12


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _tcp_reachable(host: str, port: int, timeout: float = 4.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def classify(log: str) -> str:
    """Определить причину отказа по журналу ядра. Секреты не читаются."""
    text = (log or "").lower()
    if any(word in text for word in ("x509", "certificate", "tls:", "handshake failure",
                                     "reality", "bad record mac")):
        return TLS_ERROR
    if any(word in text for word in ("authentication", "auth failed", "unauthorized",
                                     "invalid user", "wrong password", "rejected by server")):
        return AUTH_ERROR
    if any(word in text for word in ("connection refused", "no route to host", "i/o timeout",
                                     "dial tcp", "no such host", "network is unreachable")):
        return UNREACHABLE
    return TRANSPORT_ERROR


def _has_diagnosis(log: str) -> bool:
    return any(level in (log or "") for level in ("level=error", "level=fatal", "level=warning"))


def _config(server, http_port):
    proxy = _mihomo_proxy(server)
    return {
        # HTTP-прокси, а не SOCKS: имя цели резолвит сам сервер, и проверка
        # обходится без сторонних зависимостей в клиенте.
        "port": http_port,
        "bind-address": "127.0.0.1",
        "allow-lan": False,
        "mode": "rule",
        "log-level": "warning",
        "ipv6": False,
        "geo-auto-update": False,
        "profile": {"store-selected": False, "store-fake-ip": False},
        "dns": {"enable": False},
        "proxies": [proxy],
        # Единственное правило: мимо проверяемого сервера уйти нечему.
        "rules": ["MATCH,proxy"],
    }


def probe(server, url: str = DEFAULT_URL) -> dict:
    """Проверить один сервер. Возвращает {'state', 'label', 'detail'}."""
    def result(state, detail=""):
        return {"state": state, "label": LABELS.get(state, state), "detail": detail}

    try:
        ensure_supported(server)
    except ValueError as exc:
        return result(UNSUPPORTED, str(exc))

    executable = bin_path("mihomo.exe" if os.name == "nt" else "mihomo")
    if not os.path.exists(executable):
        return result(CONFIG_REJECTED, "mihomo.exe не найден в папке bin/")

    try:
        config = _config(server, _free_port())
    except (ValueError, KeyError) as exc:
        return result(UNSUPPORTED, str(exc))

    http_port = config["port"]
    runtime = os.path.join(data_dir(), "runtime", "mihomo")
    os.makedirs(runtime, exist_ok=True)
    creation = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    with tempfile.TemporaryDirectory(prefix="sadness-probe-") as folder:
        path = os.path.join(folder, "probe.yaml")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(config, handle, ensure_ascii=False)

        check = subprocess.run([executable, "-d", runtime, "-f", path, "-t"],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               encoding="utf-8", errors="replace", timeout=20,
                               creationflags=creation)
        if check.returncode:
            return result(CONFIG_REJECTED, _core_errors(check.stdout))

        # Порт проверяется отдельно: «порт доступен» и «соединение работает» —
        # разные состояния, и пользователю полезно видеть именно то, что есть.
        try:
            port = int(server.get("port") or 443)
        except (TypeError, ValueError):
            port = 443
        reachable = _tcp_reachable(str(server.get("host") or ""), port)

        log_path = os.path.join(folder, "core.log")
        with open(log_path, "w", encoding="utf-8") as log:
            process = subprocess.Popen([executable, "-d", runtime, "-f", path],
                                       stdout=log, stderr=log, creationflags=creation)
        try:
            deadline = time.monotonic() + 8
            ready = False
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    break
                try:
                    with socket.create_connection(("127.0.0.1", http_port), timeout=0.3):
                        ready = True
                        break
                except OSError:
                    time.sleep(0.1)
            if not ready:
                return result(CONFIG_REJECTED, "Ядро не приняло проверочную конфигурацию")

            proxy_url = f"http://127.0.0.1:{http_port}"
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url}))
            try:
                with opener.open(url, timeout=_TIMEOUT) as response:
                    if 200 <= response.status < 400:
                        return result(CONNECTED)
                return result(TRANSPORT_ERROR, f"Неожиданный ответ {response.status}")
            except (urllib.error.URLError, OSError, ValueError):
                pass
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as log:
                tail = log.read()[-4000:]
        except OSError:
            tail = ""
        state = classify(tail)
        if state == UNREACHABLE and reachable:
            # Порт отвечает, но транспорт не согласован — это не «сервер лежит».
            state = TRANSPORT_ERROR
        detail = _core_errors(tail)
        if not _has_diagnosis(tail):
            # Ядро молчит: запрос просто не дошёл. Это самый частый вид отказа
            # у REALITY с неверным SNI или устаревшими параметрами подписки.
            detail = ("Сервер не ответил за отведённое время. "
                      + ("Порт отвечает, но транспорт не согласован — проверьте SNI, "
                         "REALITY-параметры и актуальность подписки."
                         if reachable else
                         "Адрес или порт недоступны."))
        return result(state, detail)
