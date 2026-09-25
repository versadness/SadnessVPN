"""
engine/wg_config.py — парсинг WireGuard/AmneziaWG конфигов и outbound Mihomo для WireGuard.

Обычный WireGuard подключается через Mihomo (TUN), AmneziaWG — нативной службой
(engine/amneziawg.py).
"""
import base64
import ipaddress
import json
import re
import urllib.request


# AmneziaWG-поля. Классические Jc..H4 нужны конфигам AWG 1.x/2.x,
# остальные используются новым форматом AWG 3.x.
AWG_INTERFACE_FIELDS = {
    "jc": "Jc",
    "jmin": "Jmin",
    "jmax": "Jmax",
    "s1": "S1",
    "s2": "S2",
    "s3": "S3",
    "s4": "S4",
    "h1": "H1",
    "h2": "H2",
    "h3": "H3",
    "h4": "H4",
    "i1": "I1",
    "i2": "I2",
    "i3": "I3",
    "i4": "I4",
    "i5": "I5",
    "headerprotectionkey": "HeaderProtectionKey",
    "contentpaddingaddition": "ContentPaddingAddition",
    "rekeyaftertime": "RekeyAfterTime",
    "rekeytimeout": "RekeyTimeout",
    "rejectaftertime": "RejectAfterTime",
    "keepalivetimeout": "KeepaliveTimeout",
    "maxhandshakeattempts": "MaxHandshakeAttempts",
    "randomtrailers": "RandomTrailers",
    "disablecookies": "DisableCookies",
}
AWG_PEER_FIELDS = {"advancedsecurity": "AdvancedSecurity"}
AWG_FIELDS = set(AWG_INTERFACE_FIELDS) | set(AWG_PEER_FIELDS)


def _parse_conf_text(text: str) -> dict:
    result = {
        "type"             : "wireguard",
        "private_key"      : "",
        "address"          : [],
        "dns"              : [],
        "peer_public_key"  : "",
        "pre_shared_key"   : "",
        "endpoint"         : "",
        "port"             : 51820,
        "allowed_ips"      : ["0.0.0.0/0", "::/0"],
        "source_allowed_ips": [],
        "persistent_keepalive": 0,
        "mtu"              : 1280,
        "awg_fields"       : {},
        "is_awg"           : False,
        "remark"           : "",
        "force_full_route" : False,
    }

    section = None
    peer_count = 0
    raw_allowed_ips = []

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            section = line.strip("[]").lower()
            if section == "peer":
                peer_count += 1
                if peer_count > 1:
                    raise ValueError("Несколько Peer пока не поддерживаются. Импортируйте отдельные конфиги.")
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip().lower()
        val = val.strip()

        if section == "interface":
            if key == "privatekey":
                result["private_key"] = val
            elif key == "address":
                result["address"] = [a.strip() for a in val.split(",")]
            elif key == "dns":
                result["dns"] = [d.strip() for d in val.split(",")]
            elif key == "mtu":
                try:
                    result["mtu"] = int(val)
                except ValueError:
                    pass
            elif key in AWG_FIELDS:
                result["awg_fields"][key] = val
                result["is_awg"] = True

        elif section == "peer":
            if key == "publickey":
                result["peer_public_key"] = val
            elif key == "presharedkey":
                result["pre_shared_key"] = val
            elif key == "endpoint":
                if ":" in val:
                    host, _, port = val.rpartition(":")
                    result["endpoint"] = host.strip("[]")
                    try:
                        result["port"] = int(port)
                    except ValueError:
                        raise ValueError("Неверный порт Endpoint")
                else:
                    raise ValueError("Endpoint должен содержать адрес и порт")
            elif key == "allowedips":
                raw_allowed_ips = [a.strip() for a in val.split(",")]
            elif key == "persistentkeepalive":
                try:
                    result["persistent_keepalive"] = max(0, min(65535, int(val)))
                except ValueError:
                    pass
            elif key in AWG_FIELDS:
                result["awg_fields"][key] = val
                result["is_awg"] = True

    result["source_allowed_ips"] = list(raw_allowed_ips)
    has_full_ipv4 = any(ip in ("0.0.0.0/0", "0.0.0.0/1") for ip in raw_allowed_ips)

    if raw_allowed_ips and not has_full_ipv4:
        result["allowed_ips"]      = ["0.0.0.0/0", "::/0"]
        result["force_full_route"] = True
    else:
        result["allowed_ips"] = raw_allowed_ips if raw_allowed_ips else ["0.0.0.0/0", "::/0"]

    dns_clean = [d for d in result["dns"] if d]
    if not dns_clean:
        dns_clean = ["1.1.1.1"]
    result["dns"] = dns_clean

    if not result["remark"]:
        result["remark"] = (
            f"{result['endpoint']}:{result['port']}"
            if result["endpoint"] else "WireGuard"
        )
    if result["is_awg"]:
        result["remark"] = "[AWG] " + result["remark"]

    validate_wg_server(result)
    return result


def validate_wg_server(server):
    for key in ("private_key", "peer_public_key", "pre_shared_key"):
        value = server.get(key, "")
        if key == "pre_shared_key" and not value:
            continue
        try:
            if len(base64.b64decode(value, validate=True)) != 32:
                raise ValueError()
        except Exception:
            raise ValueError(f"Некорректный {key}: нужен ключ WireGuard из 32 байт") from None
    addresses = server.get("address") or []
    if isinstance(addresses, str):
        addresses = [addresses]
    if not addresses:
        raise ValueError("Address не задан")
    for address in addresses:
        ipaddress.ip_interface(address)
    endpoint = server.get("endpoint", "")
    if not isinstance(endpoint, str) or not endpoint or any(c.isspace() for c in endpoint):
        raise ValueError("Endpoint не задан или некорректен")
    if not 1 <= int(server.get("port", 0)) <= 65535:
        raise ValueError("Порт Endpoint должен быть от 1 до 65535")
    return server


def parse_wg_conf(text: str) -> list:
    chunks = re.split(r'(?=\[Interface\])', text, flags=re.IGNORECASE)
    results = []
    last_error = None
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk or "[INTERFACE]" not in chunk.upper():
            continue
        try:
            parsed = _parse_conf_text(chunk)
            if parsed["private_key"]:
                results.append(parsed)
            else:
                last_error = "PrivateKey не найден в конфиге"
        except Exception as e:
            last_error = str(e)
    if last_error:
        raise ValueError(f"Ошибка парсинга: {last_error}")
    return results


def fetch_wg_subscription(url: str, hwid: str = "") -> list:
    from engine.subscriptions import download_subscription, SubscriptionServers, SubscriptionError
    url = url.strip()
    raw, metadata = download_subscription(url, hwid)

    text = None

    try:
        b64 = raw.strip().replace(b"\n", b"").replace(b"\r", b"")
        padding = (4 - len(b64) % 4) % 4
        b64 += b"=" * padding
        decoded = base64.b64decode(b64).decode("utf-8", errors="ignore")
        if "[INTERFACE]" in decoded.upper():
            text = decoded
    except Exception:
        pass

    if not text:
        plain = raw.decode("utf-8", errors="ignore")
        if "[INTERFACE]" in plain.upper():
            text = plain

    if not text:
        try:
            data = json.loads(raw.decode("utf-8", errors="ignore"))
            servers = []
            items = data if isinstance(data, list) else data.get("configs", [])
            for item in items:
                if isinstance(item, str) and "[INTERFACE]" in item.upper():
                    servers.extend(parse_wg_conf(item))
                elif isinstance(item, dict):
                    servers.append(validate_wg_server(item))
            if servers:
                return SubscriptionServers(servers, metadata)
        except Exception:
            pass

    if not text:
        raise SubscriptionError("В подписке нет WG/AWG-конфигураций. Попробуйте импорт как VLESS / Clash в разделе Подписки.")

    return SubscriptionServers(parse_wg_conf(text), metadata)


def _split_addresses(addresses):
    """Первый IPv4 и первый IPv6 из Address — ровно то, что принимает Mihomo."""
    ipv4 = ipv6 = ""
    for raw in addresses:
        interface = ipaddress.ip_interface(raw)
        if interface.version == 4 and not ipv4:
            ipv4 = str(interface.ip)
        elif interface.version == 6 and not ipv6:
            ipv6 = str(interface.ip)
    if not ipv4 and not ipv6:
        raise ValueError("В WireGuard-конфиге нет адреса интерфейса (Address)")
    return ipv4, ipv6


def mihomo_wireguard_proxy(server: dict) -> dict:
    """Outbound Mihomo для обычного WireGuard. AWG сюда не попадает: он нативный."""
    if server.get("is_awg"):
        raise ValueError("AmneziaWG подключается нативной службой, а не через Mihomo")
    validate_wg_server(server)
    addresses = server.get("address") or []
    if isinstance(addresses, str):
        addresses = [addresses]
    ipv4, ipv6 = _split_addresses([a for a in addresses if a])
    proxy = {
        "name": "proxy",
        "type": "wireguard",
        "server": server["endpoint"],
        "port": int(server.get("port", 51820)),
        "private-key": server["private_key"],
        "public-key": server["peer_public_key"],
        # Приложение всегда ведёт весь трафик через туннель (см. force_full_route).
        "allowed-ips": ["0.0.0.0/0", "::/0"],
        "udp": True,
        "mtu": int(server.get("mtu") or 1280),
    }
    if ipv4:
        proxy["ip"] = ipv4
    if ipv6:
        proxy["ipv6"] = ipv6
    if server.get("pre_shared_key"):
        proxy["pre-shared-key"] = server["pre_shared_key"]
    if server.get("persistent_keepalive"):
        proxy["persistent-keepalive"] = int(server["persistent_keepalive"])
    return proxy


def build_wg_tun_config(server: dict, **settings) -> dict:
    """Конфигурация Mihomo с TUN для обычного WireGuard.

    Та же сборка, что у прокси-протоколов: DNS-пресеты, kill switch, блокировка
    UDP, режимы маршрутизации и локальные SOCKS/HTTP работают одинаково.
    """
    from engine.core_config import assemble_config
    return assemble_config(mihomo_wireguard_proxy(server), **settings)
