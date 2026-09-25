"""Сквозная проверка остальных протоколов на loopback через ядро Mihomo.

Смысл тот же, что у tools/test_xhttp_loopback.py: улучшение XHTTP не должно
незаметно сломать обычные подключения. И сервером, и клиентом работает
bin/mihomo.exe, клиентская конфигурация строится самим приложением из ссылки
подписки, цель адресуется именем — чтобы запрос не ушёл мимо туннеля.

Запускать системным Python (нужен cryptography).
"""
import argparse
import base64
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
PASSWORD = "local-test-only"
MARKER = b"sadness-protocol-loopback-ok"
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


# Пара ключей REALITY генерируется ядром при запуске: в исходниках лежать
# ключам незачем, а проверка нужна каждый раз настоящая.
REALITY_SNI = "www.cloudflare.com"
REALITY_SHORT_ID = "0123abcd"


def reality_keypair():
    result = subprocess.run([str(ROOT / "bin" / "mihomo.exe"), "generate", "reality-keypair"],
                            capture_output=True, text=True, creationflags=0x08000000)
    values = {}
    for line in result.stdout.splitlines():
        key, _, value = line.partition(":")
        values[key.strip()] = value.strip()
    if "PrivateKey" not in values or "PublicKey" not in values:
        raise RuntimeError("Ядро не выдало пару ключей REALITY: " + result.stdout + result.stderr)
    return values["PrivateKey"], values["PublicKey"]


def reality_link(port, network, public_key=""):
    return f"vless://{UUID}@127.0.0.1:{port}?" + urlencode({
        "security": "reality", "sni": REALITY_SNI, "pbk": public_key,
        "sid": REALITY_SHORT_ID, "fp": "chrome", "type": "tcp"})


def vless_link(port, network, extra=""):
    query = {"security": "tls", "sni": "localhost", "allowInsecure": "1", "type": network}
    if network == "ws":
        query["path"] = "/ws"
        query["host"] = "localhost"
    if network == "grpc":
        query["serviceName"] = "svc"
    return f"vless://{UUID}@127.0.0.1:{port}?" + urlencode(query) + extra


def vmess_link(port, network):
    node = {"ps": "vmess", "add": "127.0.0.1", "port": str(port), "id": UUID, "aid": "0",
            "scy": "auto", "net": network, "tls": "tls", "sni": "localhost",
            "allowInsecure": "1"}
    if network == "ws":
        node["path"] = "/ws"
        node["host"] = "localhost"
    return "vmess://" + base64.b64encode(json.dumps(node).encode()).decode()


def trojan_link(port):
    return (f"trojan://{PASSWORD}@127.0.0.1:{port}?"
            + urlencode({"sni": "localhost", "allowInsecure": "1"}))


def ss_link(port):
    credentials = base64.b64encode(f"aes-256-gcm:{PASSWORD}".encode()).decode()
    return f"ss://{credentials}@127.0.0.1:{port}"


def listener(kind, port, network, reality_private=""):
    base = {"name": "in", "type": kind, "listen": "127.0.0.1", "port": port}
    if kind == "vless-reality":
        return {**base, "type": "vless",
                "users": [{"username": "test", "uuid": UUID}],
                "reality-config": {"dest": REALITY_SNI + ":443",
                                   "private-key": reality_private,
                                   "short-id": [REALITY_SHORT_ID],
                                   "server-names": [REALITY_SNI]}}
    if kind == "shadowsocks":
        base.update(cipher="aes-256-gcm", password=PASSWORD)
        return base
    base.update(certificate="cert.pem", **{"private-key": "key.pem"})
    if kind == "vless":
        base["users"] = [{"username": "test", "uuid": UUID}]
    elif kind == "vmess":
        base["users"] = [{"username": "test", "uuid": UUID, "alterId": 0}]
    else:
        base["users"] = [{"username": "test", "password": PASSWORD}]
    if network != "tcp":
        base["network"] = [network]
        if network == "ws":
            base["ws-path"] = "/ws"
        if network == "grpc":
            base["grpc-service-name"] = "svc"
    return base


CASES = (
    ("vless-reality-tcp", "vless-reality", "tcp", reality_link),
    ("vless-tls-tcp", "vless", "tcp", vless_link),
    ("vless-tls-ws", "vless", "ws", vless_link),
    ("vless-tls-grpc", "vless", "grpc", vless_link),
    ("vmess-tls-tcp", "vmess", "tcp", vmess_link),
    ("vmess-tls-ws", "vmess", "ws", vmess_link),
    ("trojan-tls-tcp", "trojan", "tcp", lambda port, network: trojan_link(port)),
    ("shadowsocks", "shadowsocks", "tcp", lambda port, network: ss_link(port)),
)


def run_case(work: Path, target_port: int, name, kind, network, make_link):
    server_port, socks_port = free_port(), free_port()
    private_key, public_key = reality_keypair() if kind == "vless-reality" else ("", "")
    server = {"log-level": "error", "hosts": {TARGET_NAME: "127.0.0.1"},
              "listeners": [listener(kind, server_port, network, private_key)],
              "proxies": [], "rules": ["MATCH,DIRECT"]}
    (work / "server.yaml").write_text(json.dumps(server), encoding="utf-8")

    link = (make_link(server_port, network, public_key) if kind == "vless-reality"
            else make_link(server_port, network))
    node = parse_link(link)
    client = build_mihomo_config(node, socks_port=socks_port, http_port=free_port())
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
        success = False
        for attempt in range(8):
            if attempt:
                time.sleep(0.5)
            result = subprocess.run(
                ["curl.exe", "--silent", "--show-error", "--max-time", "8", "--noproxy", "",
                 "--socks5-hostname", f"127.0.0.1:{socks_port}",
                 f"http://{TARGET_NAME}:{target_port}/"],
                capture_output=True, creationflags=0x08000000)
            success = result.returncode == 0 and MARKER in result.stdout
            if success:
                break
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
    if not success:
        raise AssertionError(f"FAIL {name}: соединение не установлено — "
                             + result.stderr.decode(errors="replace").strip())
    print(f"PASS {name}: соединение подтверждено", flush=True)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()

    target = http_server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=target.serve_forever, daemon=True).start()
    report = {}
    try:
        with tempfile.TemporaryDirectory(prefix="sadness-proto-") as folder:
            work = Path(folder)
            write_certificate(work)
            for name, kind, network, make_link in CASES:
                report[name] = run_case(work, target.server_port, name, kind, network, make_link)
    finally:
        target.shutdown()
        target.server_close()
    if args.json:
        args.json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"PASS {len(report)} протоколов подтверждены реальным соединением")


if __name__ == "__main__":
    main()
