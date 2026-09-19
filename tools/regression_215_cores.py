"""Real XHTTP transfers through packaged core binaries, on isolated loopback ports."""
import copy
import http.client
import http.server
import json
import hashlib
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine.core_config import build_proxy_config, build_mihomo_config
from engine.mihomo import MihomoManager
from engine.xhttp import XhttpManager

UUID = "11111111-1111-4111-8111-111111111111"
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def check(executable, config, directory, kind):
    path = Path(directory, kind + "-check.json")
    path.write_text(json.dumps(config), encoding="utf-8")
    flags = ["-t", "-d", directory, "-f", str(path)] if kind == "mihomo" else ["run", "-test", "-c", str(path)] if kind == "xray" else ["check", "-c", str(path)]
    result = subprocess.run([str(executable), *flags], capture_output=True, encoding="utf-8", errors="replace", timeout=20, creationflags=FLAGS)
    assert result.returncode == 0, (result.stdout + result.stderr)[-3000:]


class Target(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    results = []
    with tempfile.TemporaryDirectory(prefix="sadness-xhttp-test-") as temporary:
        target = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Target)
        threading.Thread(target=target.serve_forever, daemon=True).start()
        upstream_port = free_port()
        cert_result = subprocess.run([str(ROOT / "bin/xray.exe"), "tls", "cert", "--domain=localhost", "--expire=1h"], capture_output=True, encoding="utf8", check=True, creationflags=FLAGS)
        certificate = json.loads(cert_result.stdout)
        fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert("\n".join(certificate["certificate"]))).hexdigest()
        upstream = {"log": {"loglevel": "warning"}, "inbounds": [{
            "listen": "127.0.0.1", "port": upstream_port, "protocol": "vless",
            "settings": {"clients": [{"id": UUID}], "decryption": "none"},
            "streamSettings": {"network": "xhttp", "security": "tls", "xhttpSettings": {"path": "/test"},
                               "tlsSettings": {"certificates": [certificate], "alpn": ["h2", "http/1.1"]}}
        }], "outbounds": [{"protocol": "freedom", "tag": "direct"}]}
        upstream_path = Path(temporary, "upstream.json")
        upstream_path.write_text(json.dumps(upstream), encoding="utf8")
        upstream_log = open(Path(temporary, "upstream.log"), "w", encoding="utf8")
        process = subprocess.Popen([str(ROOT / "bin/xray.exe"), "run", "-c", str(upstream_path)], stdout=upstream_log, stderr=subprocess.STDOUT, creationflags=FLAGS)
        try:
            for _ in range(40):
                try:
                    with socket.create_connection(("127.0.0.1", upstream_port), timeout=.2):
                        break
                except OSError:
                    if process.poll() is not None:
                        raise RuntimeError(Path(temporary, "upstream.log").read_text())
                    time.sleep(.1)
            for core in ("xray", "mihomo"):
                for mode in (("packet-up", "stream-up", "stream-one", "auto", "split-download", "extended-extra") if core == "xray" else ("packet-up", "stream-up", "stream-one", "auto")):
                    node = {"host": "127.0.0.1", "port": upstream_port, "uuid": UUID, "type": "xhttp", "security": "tls",
                            "sni": "localhost", "pinned_cert": fingerprint, "alpn": "h2", "xhttp": {"path": "/test", "mode": mode,
                            "extra": {"xPaddingBytes": "100-200", "xmux": {"maxConcurrency": "4-8", "maxConnections": 0}}}}
                    if mode == "split-download":
                        node["xhttp"]["mode"] = "packet-up"
                        node["xhttp"]["extra"]["downloadSettings"] = {
                            "address": "127.0.0.1", "port": upstream_port, "network": "xhttp", "security": "tls",
                            "tlsSettings": {"serverName": "localhost", "pinnedPeerCertSha256": fingerprint, "alpn": ["h2"]},
                            "xhttpSettings": {"path": "/test", "mode": "auto"}}
                    elif mode == "extended-extra":
                        node["xhttp"]["mode"] = "packet-up"
                        node["xhttp"]["extra"].update(scMaxEachPostBytes=1000000, scMinPostsIntervalMs=30,
                                                     scMaxBufferedPosts=30, serverMaxHeaderBytes=8192,
                                                     scStreamUpServerSecs="20-80", noGRPCHeader=False)
                    socks_port, http_port, api = free_port(), free_port(), free_port()
                    config = build_proxy_config(node, preference=core, socks_port=socks_port, http_port=http_port)
                    logs = []
                    if core == "xray":
                        front = config["front_config"]
                        # Loopback test exercises both cores without changing system routes.
                        front["inbounds"] = [ib for ib in front["inbounds"] if ib["type"] != "tun"]
                        front["experimental"]["clash_api"]["external_controller"] = f"127.0.0.1:{api}"
                        front["route"]["rules"] = [{"outbound": "proxy"}]
                        check(ROOT / "bin/sing-box.exe", front, temporary, "singbox")
                        manager = XhttpManager(lambda m, t: logs.append((m, t)))
                    else:
                        config["tun"]["enable"] = False
                        config["external-controller"] = f"127.0.0.1:{api}"
                        config["rules"] = ["MATCH,proxy"]
                        check(ROOT / "bin/mihomo.exe", config, temporary, "mihomo")
                        manager = MihomoManager(lambda m, t: logs.append((m, t)))
                        manager._command = lambda executable, path: [executable, "-d", temporary, "-f", path]
                    try:
                        assert manager.start(config), logs[-10:]
                        assert manager.is_alive(), logs[-10:]
                        payload = ("Sadness XHTTP round trip: " + mode).encode() * 3000
                        conn = http.client.HTTPConnection("127.0.0.1", http_port, timeout=15)
                        conn.request("POST", f"http://127.0.0.1:{target.server_port}/echo", payload)
                        response = conn.getresponse()
                        actual = response.read()
                        conn.close()
                        assert response.status == 200 and actual == payload, (response.status, len(actual), logs[-8:])
                        results.append({"core": core, "mode": mode, "bytes": len(actual), "passed": True})
                        print(json.dumps(results[-1]), flush=True)
                    finally:
                        manager.stop()
                    assert not manager.is_alive()
        finally:
            process.terminate()
            process.wait(timeout=8)
            upstream_log.close()
            target.shutdown()
            target.server_close()
    print(json.dumps({"passed": len(results), "xhttp_transfers": results}))


if __name__ == "__main__":
    main()
