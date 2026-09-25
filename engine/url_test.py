"""HTTP-задержка через каждый сервер — настоящий URL-тест, а не пинг сайта.

Прежний HTTP-пинг запрашивал один и тот же адрес напрямую и показывал одну и
ту же цифру у всех серверов. Здесь поднимается отдельный экземпляр Mihomo без
TUN и без слушателей прокси: в нём все проверяемые серверы, а задержку каждого
меряет само ядро через Clash API (/proxies/<имя>/delay).

Пока VPN подключён, трафик этого экземпляра ушёл бы в TUN основного ядра и
измерение шло бы через основной сервер, поэтому такой режим тогда запрещён
вызывающей стороной.
"""
from __future__ import annotations

import http.client
import json
import os
import secrets
import socket
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urlencode

from engine.core_config import _mihomo_proxy, ensure_supported
from engine.paths import bin_path

_STARTUP_SECONDS = 10.0


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _proxies(servers):
    """(имя в ядре, индекс) для серверов, которые ядро способно собрать."""
    proxies, names = [], {}
    for index, server in enumerate(servers):
        try:
            ensure_supported(server)
            proxy = _mihomo_proxy(server)
        except (ValueError, KeyError, TypeError):
            continue
        proxy["name"] = f"s{index}"
        proxies.append(proxy)
        names[proxy["name"]] = index
    return proxies, names


def _config(proxies, port, secret):
    return {
        "external-controller": f"127.0.0.1:{port}",
        "secret": secret,
        "mode": "rule",
        "log-level": "warning",
        "ipv6": False,
        "geo-auto-update": False,
        "profile": {"store-selected": False, "store-fake-ip": False},
        "dns": {"enable": False},
        "proxies": proxies,
        "rules": ["MATCH,DIRECT"],
    }


def _request(port, secret, path, timeout):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        connection.request("GET", path, headers={"Authorization": f"Bearer {secret}"})
        response = connection.getresponse()
        return response.status, response.read(4096)
    finally:
        connection.close()


def _wait_ready(process, port, secret):
    deadline = time.monotonic() + _STARTUP_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            if _request(port, secret, "/version", 1.0)[0] == 200:
                return True
        except OSError:
            pass
        time.sleep(0.15)
    return False


def delays(servers, url, timeout=3.0, stop_event=None, on_result=None):
    """Задержка в мс (или None) для каждого сервера, по индексу в списке.

    on_result(index, ms) вызывается по мере готовности, чтобы интерфейс не ждал
    окончания всей проверки.
    """
    results = {index: None for index in range(len(servers))}
    proxies, names = _proxies(servers)

    def report(index, value):
        results[index] = value
        if on_result:
            on_result(index, value)

    unsupported = [index for index in results if index not in names.values()]
    for index in unsupported:
        report(index, None)
    executable = bin_path("mihomo.exe" if os.name == "nt" else "mihomo")
    if not proxies or not os.path.exists(executable):
        for index in names.values():
            report(index, None)
        return results

    port, secret = _free_port(), secrets.token_urlsafe(18)
    creation = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    timeout_ms = int(max(0.2, float(timeout)) * 1000)
    with tempfile.TemporaryDirectory(prefix="sadness-urltest-") as folder:
        path = os.path.join(folder, "urltest.yaml")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(_config(proxies, port, secret), handle, ensure_ascii=False)
        process = subprocess.Popen([executable, "-d", folder, "-f", path],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=creation)
        try:
            if not _wait_ready(process, port, secret):
                for index in names.values():
                    report(index, None)
                return results

            def measure(name):
                if stop_event is not None and stop_event.is_set():
                    return
                query = urlencode({"url": url, "timeout": timeout_ms})
                value = None
                try:
                    status, body = _request(port, secret,
                                            f"/proxies/{quote(name)}/delay?{query}",
                                            timeout + 2)
                    if status == 200:
                        delay = json.loads(body).get("delay")
                        value = delay if type(delay) is int and delay > 0 else None
                except (OSError, ValueError, http.client.HTTPException):
                    value = None
                report(names[name], value)

            with ThreadPoolExecutor(max_workers=16) as executor:
                list(executor.map(measure, names))
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
    return results
