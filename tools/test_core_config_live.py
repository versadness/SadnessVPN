"""Проверка сгенерированных конфигураций валидатором самого Mihomo.

Покрывает каждый протокол и каждый вариант XHTTP, который приложение умеет
импортировать. Это ровно тот уровень доказательства, который в отчёте
называется «проверен валидатором ядра»: ядро приняло конфигурацию, но
соединение здесь не устанавливается — для этого нужен живой сервер.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.config import parse_link
from engine.core_config import build_mihomo_config
from engine.transports import parse_clash_nodes

UUID = "11111111-1111-4111-8111-111111111111"
MIHOMO = ROOT / "bin" / "mihomo.exe"


def xhttp_link(mode, extra=None):
    query = {"type": "xhttp", "security": "tls", "sni": "example.com",
             "path": "/probe", "host": "example.com", "mode": mode}
    if extra:
        query["extra"] = json.dumps(extra)
    return f"vless://{UUID}@example.com:443?" + urlencode(query)


CASES = [
    ("vless-reality-tcp",
     f"vless://{UUID}@example.com:443?security=reality&pbk=iEVMFcKsJc_z9XMBGQ0bkQ3zJHYjLCLTBRnUJHUuLWQ"
     f"&sid=0123abcd&fp=chrome&flow=xtls-rprx-vision&sni=example.com"),
    ("vless-tls-ws",
     f"vless://{UUID}@example.com:443?security=tls&type=ws&path=%2Fws&host=example.com&sni=example.com"),
    ("vless-tls-grpc",
     f"vless://{UUID}@example.com:443?security=tls&type=grpc&serviceName=svc&sni=example.com"),
    ("vless-tls-httpupgrade",
     f"vless://{UUID}@example.com:443?security=tls&type=httpupgrade&path=%2Fhu&sni=example.com"),
    ("trojan-tls-tcp", "trojan://pass@example.com:443?sni=example.com"),
    ("shadowsocks", "ss://YWVzLTI1Ni1nY206cGFzc3dvcmQ=@example.com:8388#ss"),
    ("hysteria2-salamander",
     "hysteria2://pass@example.com:443?sni=example.com&obfs=salamander&obfs-password=secret"),
    ("hysteria2-hopping", "hy2://pass@example.com:443,5000-5010/?sni=example.com"),
    ("xhttp-auto", xhttp_link("auto")),
    ("xhttp-packet-up", xhttp_link("packet-up")),
    ("xhttp-stream-up", xhttp_link("stream-up")),
    ("xhttp-stream-one", xhttp_link("stream-one")),
    ("xhttp-padding-and-xmux", xhttp_link("auto", {
        "xPaddingBytes": "100-1000", "scMaxEachPostBytes": "1000000",
        "scMinPostsIntervalMs": "30", "xmux": {"maxConcurrency": "16-32",
                                               "maxConnections": 0,
                                               "hMaxRequestTimes": "600-900",
                                               "hMaxReusableSecs": "1800-3000"}})),
]

CLASH_CASES = [
    ("clash-vmess-ws", """proxies:
  - name: vmess
    type: vmess
    server: example.com
    port: 443
    uuid: 11111111-1111-4111-8111-111111111111
    alterId: 0
    cipher: auto
    tls: true
    servername: example.com
    network: ws
    ws-opts: {path: /vm, headers: {Host: example.com}}
"""),
    ("clash-vless-xhttp-reality", """proxies:
  - name: xh
    type: vless
    server: example.com
    port: 443
    uuid: 11111111-1111-4111-8111-111111111111
    tls: true
    servername: example.com
    client-fingerprint: chrome
    network: xhttp
    reality-opts: {public-key: iEVMFcKsJc_z9XMBGQ0bkQ3zJHYjLCLTBRnUJHUuLWQ, short-id: "0123abcd"}
    xhttp-opts:
      path: /exact
      host: example.com
      mode: stream-one
      reuse-settings: {max-concurrency: "16-32"}
"""),
]


def check(name, server):
    config = build_mihomo_config(server, socks_port=1080, http_port=8080)
    # TUN и Clash API не нужны для проверки самой конфигурации и потребовали бы
    # прав администратора.
    config["tun"]["enable"] = False
    config.pop("external-controller", None)
    with tempfile.TemporaryDirectory(prefix="sadness-core-check-") as folder:
        target = Path(folder) / "config.yaml"
        target.write_text(json.dumps(config), encoding="utf-8")
        result = subprocess.run([str(MIHOMO), "-d", folder, "-f", str(target), "-t"],
                                capture_output=True, text=True, timeout=30,
                                creationflags=0x08000000)
    if result.returncode:
        raise RuntimeError(f"{name}: {result.stdout}{result.stderr}")
    print("PASS core validator: " + name)


def main():
    if not MIHOMO.is_file():
        raise SystemExit("bin/mihomo.exe не найден")
    for name, link in CASES:
        check(name, parse_link(link))
    for name, document in CLASH_CASES:
        nodes = parse_clash_nodes(document)
        if not nodes:
            raise RuntimeError(name + ": подписка не дала ни одного сервера")
        check(name, nodes[0])
    print(f"PASS {len(CASES) + len(CLASH_CASES)} конфигураций приняты ядром Mihomo")


if __name__ == "__main__":
    main()
