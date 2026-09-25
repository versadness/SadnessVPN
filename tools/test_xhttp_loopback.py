"""Сквозная проверка XHTTP на loopback: реальное соединение, а не только валидатор.

Сервером работает тот же bin/mihomo.exe (VLESS-inbound с транспортом XHTTP и
самоподписанным TLS), клиентом — конфигурация, которую строит само приложение
из обычной ссылки подписки. Успех означает, что параметры ссылки дошли до
провода: трафик прошёл через XHTTP-туннель.

Ни подписки, ни TUN, ни внешней сети. Все ключи — временные тестовые.
Запускать системным Python: нужен пакет cryptography.
"""
import argparse
import datetime
import http.server as http_server
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.config import parse_link
from engine.core_config import build_mihomo_config

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

UUID = "11111111-1111-4111-8111-111111111111"
MARKER = b"sadness-xhttp-loopback-ok"
MODES = ("auto", "packet-up", "stream-up", "stream-one")

# Цель адресуется ИМЕНЕМ, а не 127.0.0.1. Иначе клиентское правило обхода
# локальных сетей (IP-CIDR,127.0.0.0/8,DIRECT) увело бы запрос мимо туннеля,
# и «успех» ничего не доказывал бы. Имя резолвит только сервер — через hosts.
TARGET_NAME = "probe.invalid"


class Handler(http_server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(MARKER)

    def log_message(self, *args):
        pass


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def write_certificate(folder: Path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
                   .public_key(key.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(now - datetime.timedelta(minutes=5))
                   .not_valid_after(now + datetime.timedelta(days=1))
                   .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]),
                                  critical=False)
                   .sign(key, hashes.SHA256()))
    (folder / "cert.pem").write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    (folder / "key.pem").write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))


def server_config(port, mode, extra, target_port):
    xhttp = {"path": "/probe", "host": "localhost", "mode": mode}
    xhttp.update(extra.get("server", {}))
    return {
        "log-level": "error",
        # Имя цели известно только серверу: клиент обязан довезти его по туннелю.
        "hosts": {TARGET_NAME: "127.0.0.1"},
        "listeners": [{
            "name": "xhttp-in", "type": "vless", "listen": "127.0.0.1", "port": port,
            "users": [{"username": "test", "uuid": UUID}],
            "network": ["xhttp"], "xhttp-config": xhttp,
            "certificate": "cert.pem", "private-key": "key.pem",
        }],
        "proxies": [], "rules": ["MATCH,DIRECT"],
    }


def client_link(port, mode, uuid, extra):
    query = {"type": "xhttp", "security": "tls", "sni": "localhost", "path": "/probe",
             "host": "localhost", "mode": mode, "allowInsecure": "1"}
    if extra.get("client"):
        query["extra"] = json.dumps(extra["client"])
    return f"vless://{uuid}@127.0.0.1:{port}?" + urlencode(query)


def wait_for(port, processes, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return True
        except OSError:
            if any(process.poll() is not None for process in processes):
                return False
            time.sleep(0.1)
    return False


def run_case(work: Path, target_port: int, name, mode, uuid, extra, expect_success):
    server_port, socks_port = free_port(), free_port()
    (work / "server.yaml").write_text(
        json.dumps(server_config(server_port, mode, extra, target_port)), encoding="utf-8")
    server = parse_link(client_link(server_port, mode, uuid, extra))
    client = build_mihomo_config(server, socks_port=socks_port, http_port=free_port())
    client["tun"]["enable"] = False
    client["dns"]["enable"] = False
    client.pop("external-controller", None)
    (work / "client.yaml").write_text(json.dumps(client), encoding="utf-8")

    core = str(ROOT / "bin" / "mihomo.exe")
    processes = []
    try:
        for config in ("server.yaml", "client.yaml"):
            processes.append(subprocess.Popen(
                [core, "-d", str(work), "-f", str(work / config)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=0x08000000))
        if not wait_for(socks_port, processes):
            raise RuntimeError(name + ": клиент не поднял SOCKS-порт")
        # --socks5-hostname: имя уходит в туннель нерезолвленным.
        result = subprocess.run(
            ["curl.exe", "--silent", "--show-error", "--max-time", "10", "--noproxy", "",
             "--socks5-hostname", f"127.0.0.1:{socks_port}",
             f"http://{TARGET_NAME}:{target_port}/"],
            capture_output=True, creationflags=0x08000000)
        success = result.returncode == 0 and MARKER in result.stdout
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    verdict = "соединение подтверждено" if success else "соединения нет"
    if success != expect_success:
        raise AssertionError(f"FAIL {name}: ожидалось "
                             f"{'соединение' if expect_success else 'отказ'}, получено {verdict}")
    print(f"PASS {name}: {verdict}", flush=True)
    return success


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path, help="куда записать машинный отчёт")
    args = parser.parse_args()

    target = http_server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=target.serve_forever, daemon=True).start()
    report = {}
    try:
        with tempfile.TemporaryDirectory(prefix="sadness-xhttp-") as folder:
            work = Path(folder)
            write_certificate(work)
            for mode in MODES:
                report[mode] = run_case(work, target.server_port, "mode=" + mode,
                                        mode, UUID, {}, True)
            report["padding+xmux"] = run_case(
                work, target.server_port, "mode=auto + padding + xmux", "auto", UUID,
                {"server": {"x-padding-bytes": "100-1000"},
                 "client": {"xPaddingBytes": "100-1000",
                            "xmux": {"maxConcurrency": "16-32", "maxConnections": 0}}},
                True)
            # Отрицательный контроль: без него «успех» ничего не доказывает —
            # он мог бы приходить мимо туннеля.
            report["wrong-uuid-rejected"] = not run_case(
                work, target.server_port, "неверный UUID", "auto",
                "22222222-2222-4222-8222-222222222222", {}, False)
    finally:
        target.shutdown()
        target.server_close()

    if args.json:
        args.json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("PASS XHTTP: все варианты подтверждены реальным соединением")


if __name__ == "__main__":
    main()
