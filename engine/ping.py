"""
engine/ping.py — TCP, ICMP, HTTP GET/HEAD пинг серверов
Оптимизировано: Использование пула потоков для предотвращения перегрузки ОС и сети.
"""
import re
import socket
import time
import threading
import subprocess
import platform
import urllib.request
import urllib.error
import http.client
import json
from urllib.parse import urlencode
from concurrent.futures import ThreadPoolExecutor

from engine.core_config import controller_headers

def tcp_ping(host: str, port: int, timeout: float = 3.0):
    try:
        t0 = time.perf_counter()
        s  = socket.create_connection((host, port), timeout=timeout)
        ms = (time.perf_counter() - t0) * 1000
        s.close()
        return round(ms)
    except Exception:
        return None

def _decode_console(raw: bytes) -> str:
    """ping.exe пишет в OEM-кодировке консоли (cp866 на русской Windows)."""
    encoding = "utf-8"
    if platform.system() == "Windows":
        try:
            import ctypes
            encoding = f"cp{ctypes.windll.kernel32.GetOEMCP()}"
        except (AttributeError, OSError):
            pass
    try:
        return raw.decode(encoding, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def icmp_ping(host: str, timeout: float = 3.0):
    try:
        system = platform.system().lower()
        if system == "windows":
            cmd = ["ping", "-n", "1", "-w", str(int(timeout * 1000)), host]
        else:
            cmd = ["ping", "-c", "1", "-W", str(int(timeout)), host]

        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout + 2,
            creationflags=0x08000000 if system == "windows" else 0,
        )
        if result.returncode != 0:
            return None
        output = _decode_console(result.stdout)

        # Подпись поля локализована («время», «time», «Zeit»…), единица — нет.
        # Строка ответа Windows несёт ещё и TTL=: так «узел недоступен» с
        # нулевым кодом возврата не принимается за ответ.
        if system == "windows":
            m = re.search(r'[=<]\s*(\d+)\s*(?:ms|мс)\b.*TTL=', output, re.IGNORECASE)
        else:
            m = re.search(r'time[=<]\s*([\d.]+)', output)

        if m:
            return round(float(m.group(1)))
        return None
    except Exception:
        return None

def http_ping(url: str, method: str = "GET", timeout: float = 3.0):
    """
    HTTP GET или HEAD пинг по URL.
    Возвращает задержку в мс или None при ошибке.
    method: 'GET' | 'HEAD'
    """
    try:
        # Игнорируем системный прокси чтобы тест шёл через VPN-тоннель
        proxy_handler = urllib.request.ProxyHandler({})
        opener        = urllib.request.build_opener(proxy_handler)

        req = urllib.request.Request(url)
        req.get_method = lambda: method.upper()

        t0 = time.perf_counter()   # ВАЖНО: до opener.open(), чтобы t0 всегда был определён
        with opener.open(req, timeout=timeout) as resp:
            _ = resp.read(128)  # читаем минимум для GET
        ms = (time.perf_counter() - t0) * 1000
        return round(ms)
    except urllib.error.HTTPError as e:
        # 204, 301, 302 — сервер ответил, это ОК
        if e.code in (204, 301, 302, 200):
            ms = (time.perf_counter() - t0) * 1000
            return round(ms)
        return None
    except Exception:
        return None


def tunnel_ping(test_url="https://www.gstatic.com/generate_204", timeout=3.0,
                native_awg=False, clash_port=9090):
    """Measure the proxy outbound, not the local TUN TCP accept latency.

    Mihomo exposes a delay test for the owned 'proxy' outbound.
    Native AWG has no Clash API, so use an HTTPS response through its system route.
    Never fall back to a TCP connect, which may only reach a local TUN listener.
    """
    if native_awg:
        return http_ping(test_url, timeout=timeout)
    conn = http.client.HTTPConnection("127.0.0.1", clash_port, timeout=timeout + 1)
    try:
        query = urlencode({"url": test_url, "timeout": int(timeout * 1000)})
        conn.request("GET", "/proxies/proxy/delay?" + query, headers=controller_headers())
        response = conn.getresponse()
        body = response.read(4096)
        if response.status != 200:
            return None
        delay = json.loads(body).get("delay")
        return delay if type(delay) is int and delay >= 0 else None
    except (OSError, ValueError, AttributeError, http.client.HTTPException):
        return None
    finally:
        conn.close()


# Пресеты URL для HTTP-пинга
PING_URL_PRESETS = {
    "google204":  "https://www.gstatic.com/generate_204",
    "cloudflare": "https://cp.cloudflare.com/generate_204",
    "apple":      "https://captive.apple.com/hotspot-detect.html",
}

def ping_server(
    host       : str,
    port       : int,
    ping_type  : str   = "tcp",
    test_url   : str   = "",
    timeout    : float = 3.0,
):
    """Задержка до адреса сервера. HTTP-режимы меряются через ядро (ping_groups)."""
    if ping_type == "icmp":
        ms = icmp_ping(host, timeout)
        if ms is None:
            ms = tcp_ping(host, port, timeout=1.5)
        return ms
    return tcp_ping(host, port, timeout=timeout)

def wg_ping(host: str, port: int, timeout: float = 3.0):
    # WireGuard работает по UDP: TCP-порт у него не слушает, поэтому только ICMP.
    # Это доступность адреса, а не подтверждение handshake.
    return icmp_ping(host, timeout)

def ping_color(ms) -> str:
    if ms is None:
        return "err"
    if ms < 150:
        return "green"
    if ms < 400:
        return "yellow"
    return "red"

def ping_groups(
    groups     : list,
    on_result,
    stop_event = None,
    ping_type  : str = "tcp",
    test_url   : str = "",
    timeout    : float = 3.0,
):
    """
    Пингует все серверы в группах.
    Использует пул потоков для защиты от лавинообразного создания Thread.
    HTTP-режимы — настоящий URL-тест через каждый сервер (engine.url_test).
    """
    if ping_type in ("http_get", "http_head"):
        from engine.url_test import delays
        for g in groups:
            if stop_event and stop_event.is_set():
                return
            gid = g["id"]
            delays(g.get("servers", []), test_url or PING_URL_PRESETS["google204"],
                   timeout=timeout, stop_event=stop_event,
                   on_result=lambda i, ms, gid=gid: on_result(gid, i, ms, ping_color(ms)))
        return

    def _ping(gid, i, host, port):
        if stop_event and stop_event.is_set():
            return
        ms    = ping_server(host, port, ping_type=ping_type,
                            test_url=test_url, timeout=timeout)
        color = ping_color(ms)
        on_result(gid, i, ms, color)

    # Ограничиваем количество одновременных пингов (30 потоков)
    with ThreadPoolExecutor(max_workers=30) as executor:
        for g in groups:
            gid  = g["id"]
            srvs = g.get("servers", [])
            for i, srv in enumerate(srvs):
                if stop_event and stop_event.is_set():
                    return
                host = srv.get("host") or srv.get("address", "") or srv.get("endpoint", "")
                try:
                    port = int(srv.get("port", 443))
                except (ValueError, TypeError):
                    port = 443

                executor.submit(_ping, gid, i, host, port)
