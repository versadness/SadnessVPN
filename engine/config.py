"""
engine/config.py — разбор ссылок подписки и общие сетевые пресеты.

Генерация конфигурации ядра живёт в engine/core_config.py: sing-box удалён,
единственное ядро — Mihomo. Здесь остались парсеры ссылок, DNS-пресеты и
загрузка подписки — всё, что не зависит от конкретного ядра.
"""

import base64
import json
import re
import urllib.parse
import urllib.request

from engine.app_meta import subscription_headers
from engine.transports import xhttp_from_query
from engine.subscriptions import (download_subscription, decode_subscription,
                                  SubscriptionError, SubscriptionServers, no_servers_error)


SUPPORTED_SCHEMES = ("vless://", "vmess://", "ss://", "trojan://", "hysteria2://", "hy2://")


# ─── DNS пресеты ──────────────────────────────────────────────────────────────

DNS_PRESETS = {
    "cf_google":  {"remote": ["tls://1.1.1.1",      "tls://8.8.8.8"],          "local": "8.8.8.8"},
    "google":     {"remote": ["tls://8.8.8.8",      "tls://8.8.4.4"],          "local": "8.8.4.4"},
    "cloudflare": {"remote": ["tls://1.1.1.1",      "tls://1.0.0.1"],          "local": "1.0.0.1"},
    "adguard":    {"remote": ["tls://94.140.14.14", "tls://94.140.15.15"],    "local": "94.140.14.14"},
    "quad9":      {"remote": ["tls://9.9.9.9",      "tls://149.112.112.112"],  "local": "9.9.9.9"},
    # Xbox Smart DNS (xbox-dns.ru) — разблокирует различные сервисы
    # через подмену DNS ответов. Запросы идут НАПРЯМУЮ (не через VPN туннель).
    # ВАЖНО: Xbox DNS отвечает только на A (IPv4), AAAA запросы он не обрабатывает —
    # поэтому в xbox/xbox_dot режиме AAAA принудительно блокируется.
    "xbox":     {"remote": ["udp://111.88.96.50", "udp://111.88.96.51"],       "local": "111.88.96.50"},
    # DoT вариант Xbox DNS (зашифрованный, более надёжный):
    "xbox_dot": {"remote": ["tls://xbox-dns.ru",  "tls://xbox-dns.ru"],        "local": "111.88.96.50"},
    # Comss.one DNS — второй Smart DNS-провайдер (PowerDNS, бесплатный).
    # Xbox применяет подмену только к заранее зарегистрированным IP клиентов,
    # из-за чего у пользователей с динамическим адресом он молча перестаёт
    # работать. Comss такой регистрации не требует.
    "comss":     {"remote": ["udp://83.220.169.155", "udp://212.109.195.93"],  "local": "83.220.169.155"},
    # DoT вариант Comss (зашифрованный):
    "comss_dot": {"remote": ["tls://dns.comss.one",  "tls://dns.comss.one"],   "local": "83.220.169.155"},
}

# Бутстрап по raw IP для каждого Smart DNS: резолвить имя сервера через него
# самого нельзя — получится петля. Ключи здесь же задают, какие пресеты
# считаются Smart DNS и требуют бутстрапа по своему же raw IP.
SMART_DNS_BOOTSTRAP = {
    "xbox":      "udp://111.88.96.50",
    "xbox_dot":  "udp://111.88.96.50",
    "comss":     "udp://83.220.169.155",
    "comss_dot": "udp://83.220.169.155",
}


# ─── Парсинг VLESS ────────────────────────────────────────────────────────────

def parse_vless_link(link: str) -> dict:
    link = link.strip()
    if not link.startswith("vless://"):
        raise ValueError("Ожидается vless:// ссылка")
    rest = link[len("vless://"):]
    if "#" in rest:
        rest, remark_enc = rest.rsplit("#", 1)
        remark = urllib.parse.unquote(remark_enc)
    else:
        remark = "VLESS"
    if "@" not in rest:
        raise ValueError("Неверный формат vless://")
    user_id, host_part = rest.split("@", 1)
    if "?" in host_part:
        host_port, query_str = host_part.split("?", 1)
    else:
        host_port, query_str = host_part, ""
    if host_port.startswith("["):
        bracket_end = host_port.index("]")
        host = host_port[1:bracket_end]
        port = int(host_port[bracket_end + 2:])
    elif ":" in host_port:
        h, p = host_port.rsplit(":", 1)
        host = h
        port = int(p)
    else:
        host = host_port
        port = 443
    params = dict(urllib.parse.parse_qsl(query_str))
    return {
        "remark":        remark,
        "host":          host,
        "port":          port,
        "uuid":          user_id,
        "security":      params.get("security", "none"),
        "type":          "xhttp" if params.get("type") == "splithttp" else params.get("type", "tcp"),
        **({"xhttp": xhttp_from_query(params)} if params.get("type") in ("xhttp", "splithttp") else {}),
        "sni":           params.get("sni", ""),
        "fp":            params.get("fp", ""),
        "pbk":           params.get("pbk", ""),
        "sid":           params.get("sid", ""),
        "flow":          params.get("flow", ""),
        "path":          params.get("path", ""),
        "host_header":   params.get("host", ""),
        "serviceName":   params.get("serviceName", ""),
        "alpn":          params.get("alpn", ""),
        "allowInsecure": params.get("allowInsecure", "0"),
        "pinned_cert":   params.get("pcs", params.get("pinnedPeerCertSha256", "")),
        "verify_cert_name": params.get("vcn", params.get("verifyPeerCertByName", "")),
        "encryption":    params.get("encryption", "none"),
    }


# ─── Парсинг VMess ────────────────────────────────────────────────────────────

def parse_vmess_link(link: str) -> dict:
    """Разбор vmess://<base64 JSON> — формат v2rayN, который отдают подписки.

    Раньше VMess молча отбрасывался и парсером, и импортом Clash: sing-box
    выпуска в проекте его не собирал. Mihomo поддерживает VMess нативно,
    поэтому сервер больше не исчезает из подписки без объяснения.
    """
    link = link.strip()
    if not link.startswith("vmess://"):
        raise ValueError("Ожидается vmess:// ссылка")
    payload = link[len("vmess://"):].split("#", 1)[0].strip()
    try:
        raw = base64.b64decode(payload + "=" * (-len(payload) % 4)).decode("utf-8")
        node = json.loads(raw)
    except Exception:
        raise ValueError("VMess: ссылка должна содержать base64 с JSON") from None
    if not isinstance(node, dict):
        raise ValueError("VMess: ожидается JSON-объект")
    host = str(node.get("add", "")).strip()
    if not host:
        raise ValueError("VMess: не указан адрес сервера")
    try:
        port = int(node.get("port", 443))
    except (TypeError, ValueError):
        raise ValueError("VMess: некорректный порт") from None
    if not 1 <= port <= 65535:
        raise ValueError("VMess: порт должен быть от 1 до 65535")
    if not str(node.get("id", "")).strip():
        raise ValueError("VMess: не указан UUID")
    network = str(node.get("net", "tcp") or "tcp").lower()
    if network == "splithttp":
        network = "xhttp"
    tls = str(node.get("tls", "") or "").lower()
    return {
        "protocol":      "vmess",
        "remark":        str(node.get("ps") or "VMess"),
        "host":          host,
        "port":          port,
        "uuid":          str(node["id"]).strip(),
        "alter_id":      int(node.get("aid") or 0),
        "method":        str(node.get("scy") or "auto"),
        "security":      "reality" if tls == "reality" else "tls" if tls == "tls" else "none",
        "type":          network,
        "sni":           str(node.get("sni") or ""),
        "fp":            str(node.get("fp") or ""),
        "pbk":           str(node.get("pbk") or ""),
        "sid":           str(node.get("sid") or ""),
        "path":          str(node.get("path") or ""),
        "host_header":   str(node.get("host") or ""),
        "serviceName":   str(node.get("path") or "") if network == "grpc" else "",
        "alpn":          str(node.get("alpn") or ""),
        "allowInsecure": "1" if str(node.get("allowInsecure", "")) in ("1", "true") else "0",
    }


# ─── Парсинг Shadowsocks ──────────────────────────────────────────────────────

def parse_ss_link(link: str) -> dict:
    link = link.strip()
    if not link.startswith("ss://"):
        raise ValueError("Ожидается ss:// ссылка")
    rest = link[len("ss://"):]
    remark = "Shadowsocks"
    if "#" in rest:
        rest, remark_enc = rest.rsplit("#", 1)
        remark = urllib.parse.unquote(remark_enc)

    if "?" in rest:
        rest = rest.split("?", 1)[0]

    if "@" in rest:
        userinfo, hostport = rest.rsplit("@", 1)
        try:
            padding = (4 - len(userinfo) % 4) % 4
            decoded = base64.b64decode(userinfo + "=" * padding).decode("utf-8")
            method, _, password = decoded.partition(":")
        except Exception:
            method, _, password = urllib.parse.unquote(userinfo).partition(":")
    else:
        try:
            padding = (4 - len(rest) % 4) % 4
            decoded = base64.b64decode(rest + "=" * padding).decode("utf-8")
            if "@" in decoded:
                userinfo, hostport = decoded.rsplit("@", 1)
                method, _, password = userinfo.partition(":")
            else:
                raise ValueError("Неверный формат ss://")
        except Exception:
            raise ValueError("Неверный формат ss://")

    if hostport.startswith("["):
        bracket_end = hostport.index("]")
        host = hostport[1:bracket_end]
        port = int(hostport[bracket_end + 2:])
    elif ":" in hostport:
        h, p = hostport.rsplit(":", 1)
        host = h
        port = int(p)
    else:
        raise ValueError("Нет порта в ss:// ссылке")

    return {
        "protocol": "ss",
        "remark":   remark,
        "host":     host,
        "port":     port,
        "method":   method.strip(),
        "password": password.strip(),
    }


# ─── Парсинг Trojan ───────────────────────────────────────────────────────────

def parse_trojan_link(link: str) -> dict:
    link = link.strip()
    if not link.startswith("trojan://"):
        raise ValueError("Ожидается trojan:// ссылка")
    rest = link[len("trojan://"):]
    remark = "Trojan"
    if "#" in rest:
        rest, remark_enc = rest.rsplit("#", 1)
        remark = urllib.parse.unquote(remark_enc)

    query_str = ""
    if "?" in rest:
        rest, query_str = rest.split("?", 1)

    if "@" not in rest:
        raise ValueError("Неверный формат trojan://")
    password, hostport = rest.rsplit("@", 1)

    if hostport.startswith("["):
        bracket_end = hostport.index("]")
        host = hostport[1:bracket_end]
        port = int(hostport[bracket_end + 2:])
    elif ":" in hostport:
        h, p = hostport.rsplit(":", 1)
        host = h
        port = int(p)
    else:
        host = hostport
        port = 443

    params = dict(urllib.parse.parse_qsl(query_str))
    return {
        "protocol":      "trojan",
        "remark":        remark,
        "host":          host,
        "port":          port,
        "password":      urllib.parse.unquote(password),
        "sni":           params.get("sni", params.get("peer", "")),
        "allowInsecure": params.get("allowInsecure", params.get("skip-cert-verify", "0")),
        "alpn":          params.get("alpn", ""),
        "fp":            params.get("fp", ""),
        "type":          params.get("type", "tcp"),
        "path":          params.get("path", ""),
        "host_header":   params.get("host", ""),
        "serviceName":   params.get("serviceName", ""),
    }


# ─── Парсинг Hysteria2 ────────────────────────────────────────────────────────

def parse_hysteria2_link(link: str) -> dict:
    from engine.hysteria2 import parse_uri
    return parse_uri(link)


# ─── Универсальный парсер ─────────────────────────────────────────────────────

def parse_link(link: str) -> dict:
    link = link.strip()
    if link.startswith("vless://"):
        return parse_vless_link(link)
    elif link.startswith("vmess://"):
        return parse_vmess_link(link)
    elif link.startswith("ss://"):
        return parse_ss_link(link)
    elif link.startswith("trojan://"):
        return parse_trojan_link(link)
    elif link.startswith(("hysteria2://", "hy2://")):
        return parse_hysteria2_link(link)
    else:
        raise ValueError(f"Неподдерживаемый протокол. Ожидается: vless://, vmess://, ss://, trojan://, hysteria2://")


# ─── Загрузка подписки ────────────────────────────────────────────────────────

_LINK_SCHEME = re.compile(r"^([a-z][a-z0-9+.-]{1,20})://", re.I)
_MAX_REJECTED = 50


def _link_label(line: str) -> str:
    """Имя узла из #фрагмента — без UUID, паролей и адреса."""
    name = urllib.parse.unquote(line.rsplit("#", 1)[1]) if "#" in line else ""
    name = "".join(c for c in name if c.isprintable()).strip()[:80]
    return name or line.split("://", 1)[0] + "-узел"


def parse_share_links(raw: str):
    """Разобрать список ссылок. Возвращает (серверы, отклонённые, получено).

    Раньше ошибка разбора одной ссылки глоталась молча, и сервер пропадал из
    подписки без объяснения. Теперь каждый отказ записывается с причиной, а
    остальные серверы импортируются как обычно.
    """
    servers, rejected, received = [], [], 0
    for line in raw.splitlines():
        line = line.strip()
        match = _LINK_SCHEME.match(line)
        if not match:
            continue
        received += 1
        if not line.startswith(SUPPORTED_SCHEMES):
            rejected.append({"name": _link_label(line),
                             "reason": f"протокол {match.group(1).lower()} не поддерживается ядром Mihomo"})
            continue
        try:
            server = parse_link(line)
            from engine.core_config import ensure_supported
            ensure_supported(server)
            servers.append(server)
        except Exception as exc:
            reason = str(exc) if isinstance(exc, ValueError) else "ссылка повреждена"
            rejected.append({"name": _link_label(line), "reason": reason[:200]})
    return servers, rejected, received


def fetch_subscription(url: str, hwid: str = "") -> list:
    data, metadata = download_subscription(url, hwid)
    raw = decode_subscription(data)

    servers, rejected, received = [], [], 0
    if _LINK_SCHEME.search(raw.lstrip()) or any(s in raw for s in SUPPORTED_SCHEMES):
        servers, rejected, received = parse_share_links(raw)
    elif "proxies:" in raw or raw.lstrip().startswith("{"):
        from engine.transports import parse_clash_nodes
        servers = parse_clash_nodes(raw, rejected=rejected)
        received = len(servers) + len(rejected)
    metadata = {**metadata, "received": received, "accepted": len(servers),
                "rejected": rejected[:_MAX_REJECTED]}
    if not servers:
        error = no_servers_error(raw) if not rejected else SubscriptionError(
            "Ни один сервер подписки не поддерживается: " + "; ".join(
                f"{item['name']} — {item['reason']}" for item in rejected[:3]
            ) + ". Текущие серверы сохранены.")
        error.metadata = metadata
        raise error
    return SubscriptionServers(servers, metadata)
