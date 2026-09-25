"""Живая проверка DNS-секции Mihomo без TUN, интернета и подписки.

Ядро поднимается с той самой DNS-секцией, которую строит приложение, но с
подставленным локальным резолвером. Запрос уходит в mihomo и должен вернуться
с ответом нашего резолвера — это доказывает, что секция не только проходит
валидатор, но и обслуживает запросы, а нейм-сервер действительно используется.
"""
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.config import parse_link
from engine.core_config import build_mihomo_config

ANSWER = "192.0.2.123"
QUERY = bytes.fromhex("123401000001000000000000") + b"\x05probe\x07example\x00\x00\x01\x00\x01"


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    core = ROOT / "bin" / "mihomo.exe"
    if not core.is_file():
        raise SystemExit("bin/mihomo.exe не найден")

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as upstream:
        upstream.bind(("127.0.0.1", 0))
        upstream.settimeout(0.2)
        upstream_port = upstream.getsockname()[1]
        stopping, seen = threading.Event(), []

        def serve():
            while not stopping.is_set():
                try:
                    query, address = upstream.recvfrom(4096)
                except socket.timeout:
                    continue
                seen.append(query)
                reply = (query[:2] + bytes.fromhex("81800001000100000000") + query[12:]
                         + bytes.fromhex("c00c000100010000003c0004")
                         + socket.inet_aton(ANSWER))
                upstream.sendto(reply, address)

        worker = threading.Thread(target=serve)
        worker.start()
        try:
            listen_port = free_port()
            server = parse_link(
                "vless://00000000-0000-0000-0000-000000000001@example.com:443?security=tls")
            config = build_mihomo_config(server, socks_port=free_port(), http_port=free_port())
            # Без TUN и Clash API: проверяем ровно DNS, без прав администратора.
            config["tun"]["enable"] = False
            config.pop("external-controller", None)
            config["dns"]["listen"] = f"127.0.0.1:{listen_port}"
            config["dns"]["nameserver"] = [f"udp://127.0.0.1:{upstream_port}"]
            config["dns"]["default-nameserver"] = [f"127.0.0.1"]

            with tempfile.TemporaryDirectory(prefix="sadness-dns-live-") as folder:
                target = Path(folder) / "config.yaml"
                target.write_text(json.dumps(config), encoding="utf-8")
                with (Path(folder) / "core.log").open("w", encoding="utf-8") as log:
                    process = subprocess.Popen(
                        [str(core), "-d", folder, "-f", str(target)],
                        stdout=log, stderr=log, creationflags=0x08000000)
                    try:
                        answer = None
                        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                            client.settimeout(1.0)
                            for _attempt in range(60):
                                try:
                                    client.sendto(QUERY, ("127.0.0.1", listen_port))
                                    answer = client.recv(4096)
                                    break
                                except (socket.timeout, OSError):
                                    time.sleep(0.1)
                        if answer is None:
                            raise RuntimeError("Mihomo не ответил на DNS-запрос: "
                                               + (Path(folder) / "core.log").read_text(
                                                   encoding="utf-8", errors="replace")[-2000:])
                        if answer[:2] != QUERY[:2] or not answer.endswith(socket.inet_aton(ANSWER)):
                            raise RuntimeError("Неожиданный DNS-ответ: " + answer.hex())
                        if not seen:
                            raise RuntimeError("Запрос не дошёл до заданного нейм-сервера")
                    finally:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
            print("PASS mihomo DNS: запрос обслужен и ушёл в заданный нейм-сервер")
        finally:
            stopping.set()
            worker.join(timeout=2)


if __name__ == "__main__":
    main()
