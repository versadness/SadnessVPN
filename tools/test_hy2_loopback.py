"""Exercise actual bundled HY2 cores on loopback only; no TUN or personal profile.

Run with the system Python (cryptography required). All credentials are generated
test fixtures; temporary server/client processes are terminated in finally.
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
from engine.config import parse_link, _build_singbox_outbound
from engine.core_config import _mihomo_proxy
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


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
            for core, obfs, use_pin, good_auth in (
                    ("singbox", False, False, True), ("singbox", True, False, True),
                    ("mihomo", True, False, True), ("mihomo", True, True, True),
                    ("mihomo", True, True, False), ("mihomo", True, "wrong", True)):
                udp_port, socks_port = free_port(socket.SOCK_DGRAM), free_port()
                server = {"log": {"level": "error"}, "inbounds": [{"type": "hysteria2", "listen": "127.0.0.1", "listen_port": udp_port,
                          "users": [{"name": "test", "password": "local-only"}],
                          "tls": {"enabled": True, "certificate_path": str(work / "cert.pem"), "key_path": str(work / "key.pem")}}],
                          "outbounds": [{"type": "direct"}]}
                if obfs:
                    server["inbounds"][0]["obfs"] = {"type": "salamander", "password": "local-obfs"}
                query = "sni=localhost&insecure=" + ("0" if use_pin else "1") + ("&obfs=salamander&obfs-password=local-obfs" if obfs else "")
                if use_pin:
                    query += "&pinSHA256=" + ("00" * 32 if use_pin == "wrong" else pin)
                node = parse_link(f"hy2://{'local-only' if good_auth else 'wrong'}@127.0.0.1:{udp_port}/?{query}")
                if core == "singbox":
                    client = {"log": {"level": "error"}, "inbounds": [{"type": "socks", "listen": "127.0.0.1", "listen_port": socks_port}],
                              "outbounds": [_build_singbox_outbound(node)]}
                    client_cmd = [str(ROOT / "bin/sing-box.exe"), "run", "-c", str(work / "client.json")]
                else:
                    client = {"socks-port": socks_port, "bind-address": "127.0.0.1", "allow-lan": False,
                              "log-level": "error", "proxies": [_mihomo_proxy(node)], "rules": ["MATCH,proxy"], "mode": "rule"}
                    client_cmd = [str(ROOT / "bin/mihomo.exe"), "-d", str(work), "-f", str(work / "client.json")]
                (work / "server.json").write_text(json.dumps(server), encoding="utf-8")
                (work / "client.json").write_text(json.dumps(client), encoding="utf-8")
                processes = []
                try:
                    for cmd in ([str(ROOT / "bin/sing-box.exe"), "run", "-c", str(work / "server.json")], client_cmd):
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
                    result = subprocess.run(["curl.exe", "--silent", "--show-error", "--max-time", "8", "--noproxy", "",
                                             "--socks5-hostname", f"127.0.0.1:{socks_port}", f"http://127.0.0.1:{http.server_port}/"], capture_output=True)
                    success = result.returncode == 0 and b"sadness-hy2-loopback-ok" in result.stdout
                    assert success == (good_auth and use_pin != "wrong"), (core, obfs, use_pin, result.stderr.decode(errors="replace"))
                    print(f"PASS core={core} salamander={obfs} pin={use_pin} connection={'accepted' if success else 'rejected'}", flush=True)
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
