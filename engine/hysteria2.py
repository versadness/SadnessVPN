"""Hysteria 2 URI normalization and capabilities of the bundled cores."""
import re
from urllib.parse import unquote, urlsplit, parse_qsl


def ports(value):
    value = str(value).strip()
    if not re.fullmatch(r"\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*", value):
        raise ValueError("HY2: неверный порт или диапазон портов")
    for part in value.split(","):
        bounds = [int(x) for x in part.split("-")]
        if not all(1 <= n <= 65535 for n in bounds) or bounds[0] > bounds[-1]:
            raise ValueError("HY2: порт должен быть от 1 до 65535, диапазон — возрастающим")
    return int(value.split(",")[0].split("-")[0]), value


def fingerprint(value):
    normalized = str(value).replace(":", "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", normalized):
        raise ValueError("HY2: отпечаток сертификата должен содержать 64 шестнадцатеричных символа")
    return normalized


def validate(server):
    if server.get("obfs") not in (None, "", "salamander"):
        raise ValueError("HY2: эта сборка поддерживает только obfs=salamander")
    if server.get("obfs") and not server.get("obfs_password"):
        raise ValueError("HY2: для Salamander необходим obfs-password")
    if server.get("ech") or server.get("realm-opts"):
        raise ValueError("HY2: ECH / Realm пока не поддерживаются этой сборкой")
    ports(server.get("port", 443))
    if server.get("ports"):
        ports(server["ports"])
    if server.get("pinned_cert"):
        fingerprint(server["pinned_cert"])


def requires_mihomo(server):
    # sing-box 1.10.7 has neither HY2 hopping nor certificate fingerprint pinning.
    return any(server.get(k) for k in ("ports", "pinned_cert", "up", "down", "hop_interval", "verify_cert_name"))


def parse_uri(link):
    parsed = urlsplit(link.strip())
    if parsed.scheme not in {"hysteria2", "hy2"}:
        raise ValueError("Ожидается hysteria2:// или hy2:// ссылка")
    if parsed.path not in ("", "/"):
        raise ValueError("HY2: после адреса допустим только /, без пути")
    auth, _, address = parsed.netloc.rpartition("@")
    if address.startswith("["):
        end = address.find("]")
        if end < 0 or (address[end + 1:] and not address[end + 1:].startswith(":")):
            raise ValueError("HY2: неверный IPv6-адрес")
        host, port_text = address[1:end], address[end + 2:] or "443"
    else:
        host, sep, port_text = address.partition(":")
        if not sep:
            port_text = "443"
    if not host or any(c.isspace() for c in host):
        raise ValueError("HY2: не указан корректный адрес сервера")
    port, port_text = ports(port_text)
    query = dict(parse_qsl(parsed.query))
    insecure = query.get("insecure", query.get("allowInsecure", "0")).lower()
    if insecure not in {"0", "1", "true", "false"}:
        raise ValueError("HY2: insecure должен быть 0 или 1")
    server = {
        "protocol": "hysteria2", "type": "quic", "security": "tls",
        "remark": unquote(parsed.fragment) or "Hysteria 2", "host": host,
        "port": port, "password": unquote(auth), "sni": query.get("sni", ""),
        "insecure": insecure in {"1", "true"}, "alpn": query.get("alpn", ""),
        "obfs": query.get("obfs", ""), "obfs_password": query.get("obfs-password", ""),
    }
    hopping = query.get("mport") or (port_text if "," in port_text or "-" in port_text else "")
    if hopping:
        _, server["ports"] = ports(hopping)
    if query.get("pinSHA256"):
        server["pinned_cert"] = fingerprint(query["pinSHA256"])
    if query.get("ech"):
        server["ech"] = query["ech"]
    validate(server)
    return server
