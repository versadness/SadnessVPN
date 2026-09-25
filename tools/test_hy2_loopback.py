"""Сквозная проверка Hysteria 2 на loopback: реальное соединение через ядро.

И сервером, и клиентом работает bin/mihomo.exe — единственное ядро проекта.
Клиентская конфигурация собирается самим приложением из обычной ссылки.
Цель адресуется именем: иначе правило обхода локальных сетей увело бы запрос
мимо туннеля и проверка ничего бы не доказывала.

Запускать системным Python (нужен cryptography). Все ключи — временные.
"""
import datetime
import hashlib
import http.server as http_server
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine.config import parse_link
from engine.core_config import _mihomo_proxy
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


# Цель адресуется именем: 127.0.0.1 ушёл бы мимо туннеля по правилу обхода LAN.
TARGET_NAME = "probe.invalid"


def free_port(kind=socket.SOCK_STREAM):
    with socket.socket(type=kind) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Handler(http_server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"sadness-hy2-loopback-ok")

    def log_message(self, *args):
        pass


def main():
    http = http_server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=http.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix="sadness-hy2-test-") as tmp:
            work = Path(tmp)
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
            now = datetime.datetime.now(datetime.timezone.utc)
            cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
                    .public_key(key.public_key()).serial_number(x509.random_serial_number())
                    .not_valid_before(now - datetime.timedelta(minutes=5))
                    .not_valid_after(now + datetime.timedelta(days=1))
                    .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
                    .sign(key, hashes.SHA256()))
            (work / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            (work / "key.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            pin = hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()
            for obfs, use_pin, good_auth in (
                    (False, False, True), (True, False, True),
                    (True, True, True), (True, True, False), (True, "wrong", True)):
                udp_port, socks_port = free_port(socket.SOCK_DGRAM), free_port()
                server = {"log-level": "error", "hosts": {TARGET_NAME: "127.0.0.1"},
                          "listeners": [{"name": "hy2-in", "type": "hysteria2",
                                         "listen": "127.0.0.1", "port": udp_port,
                                         "users": {"test": "local-only"},
                                         "certificate": "cert.pem", "private-key": "key.pem"}],
                          "proxies": [], "rules": ["MATCH,DIRECT"]}
                if obfs:
                    server["listeners"][0]["obfs"] = "salamander"
                    server["listeners"][0]["obfs-password"] = "local-obfs"
                query = "sni=localhost&insecure=" + ("0" if use_pin else "1") + ("&obfs=salamander&obfs-password=local-obfs" if obfs else "")
                if use_pin:
                    query += "&pinSHA256=" + ("00" * 32 if use_pin == "wrong" else pin)
                node = parse_link(f"hy2://{'local-only' if good_auth else 'wrong'}@127.0.0.1:{udp_port}/?{query}")
                client = {"socks-port": socks_port, "bind-address": "127.0.0.1", "allow-lan": False,
                          "log-level": "error", "proxies": [_mihomo_proxy(node)],
                          "rules": ["MATCH,proxy"], "mode": "rule"}
                client_cmd = [str(ROOT / "bin/mihomo.exe"), "-d", str(work), "-f", str(work / "client.yaml")]
                (work / "server.yaml").write_text(json.dumps(server), encoding="utf-8")
                (work / "client.yaml").write_text(json.dumps(client), encoding="utf-8")
                processes = []
                try:
                    for cmd in ([str(ROOT / "bin/mihomo.exe"), "-d", str(work), "-f", str(work / "server.yaml")], client_cmd):
                        processes.append(subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=0x08000000))
                    deadline = time.monotonic() + 8
                    while True:
                        try:
                            with socket.create_connection(("127.0.0.1", socks_port), timeout=.3):
                                break
                        except OSError:
                            if time.monotonic() >= deadline or any(p.poll() is not None for p in processes):
                                raise RuntimeError("Test core failed to start")
                            time.sleep(.1)
                    # QUIC-рукопожатие поднимается позже, чем TCP-слушатель
                    # клиента, поэтому положительный случай получает повторы.
                    expected = good_auth and use_pin != "wrong"
                    success = False
                    for attempt in range(6 if expected else 1):
                        if attempt:
                            time.sleep(1)
                        result = subprocess.run(["curl.exe", "--silent", "--show-error", "--max-time", "8", "--noproxy", "",
                                                 "--socks5-hostname", f"127.0.0.1:{socks_port}", f"http://{TARGET_NAME}:{http.server_port}/"], capture_output=True, creationflags=0x08000000)
                        success = result.returncode == 0 and b"sadness-hy2-loopback-ok" in result.stdout
                        if success:
                            break
                    assert success == expected, (obfs, use_pin, good_auth, result.stderr.decode(errors="replace"))
                    print(f"PASS salamander={obfs} pin={use_pin} auth={'ok' if good_auth else 'bad'} "
                          f"connection={'подтверждено' if success else 'отклонено'}", flush=True)
                finally:
                    for proc in processes:
                        proc.terminate()
                    for proc in processes:
                        proc.wait(timeout=10)
    finally:
        http.shutdown()
        http.server_close()


if __name__ == "__main__":
    main()
