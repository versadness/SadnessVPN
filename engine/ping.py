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
from concurrent.futures import ThreadPoolExecutor

def tcp_ping(host: str, port: int, timeout: float = 3.0):
    try:
        t0 = time.perf_counter()
        s  = socket.create_connection((host, port), timeout=timeout)
        ms = (time.perf_counter() - t0) * 1000
        s.close()
        return round(ms)
    except Exception:
        return None

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
            text=True,
            timeout=timeout + 2,
            creationflags=0x08000000 if system == "windows" else 0,
        )
        output = result.stdout

        if result.returncode != 0:
            return None

        if system == "windows":
            m = re.search(r'[Вв]ремя[<=]\s*(\d+)', output)
            if not m:
                m = re.search(r'[Tt]ime[<=]\s*(\d+)', output)
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
    if ping_type == "icmp":
        ms = icmp_ping(host, timeout)
        if ms is None:
            ms = tcp_ping(host, port, timeout=1.5)
        return ms
    elif ping_type in ("http_get", "http_head"):
        url    = test_url or PING_URL_PRESETS["google204"]
        method = "GET" if ping_type == "http_get" else "HEAD"
        ms     = http_ping(url, method=method, timeout=timeout)
        if ms is None:
            # Fallback на TCP
            ms = tcp_ping(host, port, timeout=1.5)
        return ms
    else:
        return tcp_ping(host, port, timeout=timeout)

def wg_ping(host: str, port: int, timeout: float = 3.0):
    ms = icmp_ping(host, timeout)
    if ms is not None:
        return ms
    for p in [443, 80]:
        ms = tcp_ping(host, p, timeout=1.5)
        if ms is not None:
            return ms
    return tcp_ping(host, port, timeout=1.5)

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
    """
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