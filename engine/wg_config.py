"""
engine/wg_config.py — парсинг WireGuard/AmneziaWG конфигов и построение sing-box outbound
Новое: kill_switch, block_udp, socks5_auth, dns_preset, custom_dns, fakedns, preferred_ip
"""
import base64
import ipaddress
import json
import re
import urllib.request

from engine.app_meta import subscription_headers
from engine.config import DNS_PRESETS


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


def build_wg_tun_config(
    server         : dict,
    socks_port     : int  = 1080,
    http_port      : int  = 8080,
    clash_port     : int  = 9090,
    routing_mode   : str  = "all",
    routed_apps    : list = None,
    # ── Параметры туннеля ──
    kill_switch    : bool = False,
    block_udp      : bool = False,
    socks5_auth    : dict = None,         # {"user": "...", "pass": "..."}
    dns_preset     : str  = "cf_google",  # cf_google | google | cloudflare | quad9 | xbox | custom
    custom_dns     : list = None,
    fakedns        : bool = False,
    preferred_ip   : str  = "ipv4",       # ipv4 | ipv6 | auto
    mux            : bool = False,        # WireGuard не поддерживает mux, игнорируется
    allow_lan      : bool = False,
    **_kwargs,
) -> dict:
    if routed_apps is None:
        routed_apps = []

    local_address = server.get("address", ["10.0.0.2/32"])
    if isinstance(local_address, str):
        local_address = [local_address]
    local_address_clean = [a for a in local_address if a]

    # ── DNS ────────────────────────────────────────────────────────────
    if dns_preset == "custom" and custom_dns:
        primary_remote   = custom_dns[0]
        secondary_remote = custom_dns[1] if len(custom_dns) > 1 else custom_dns[0]
    else:
        preset           = DNS_PRESETS.get(dns_preset, DNS_PRESETS["cf_google"])
        primary_remote   = preset["remote"][0].replace("tls://", "")
        secondary_remote = (
            preset["remote"][1].replace("tls://", "") if len(preset["remote"]) > 1
            else primary_remote
        )

    ip_strategy_map = {"ipv4": "prefer_ipv4", "ipv6": "prefer_ipv6", "auto": "prefer_ipv4"}
    ip_strategy = ip_strategy_map.get(preferred_ip, "prefer_ipv4")

    outbound = {
        "type"            : "wireguard",
        "tag"             : "proxy",
        "server"          : server["endpoint"],
        "server_port"     : int(server.get("port", 51820)),
        "local_address"   : local_address_clean,
        "private_key"     : server["private_key"],
        "peer_public_key" : server["peer_public_key"],
        "mtu"             : int(server.get("mtu", 1280)),
    }
    if server.get("pre_shared_key"):
        outbound["pre_shared_key"] = server["pre_shared_key"]

    # ── DNS серверы ───────────────────────────────────────────────────
    dns_servers = [
        {
            "tag"             : "remote",
            "address"         : primary_remote if "://" in primary_remote else f"tls://{primary_remote}",
            "address_resolver": "bootstrap",
            "detour"          : "proxy",   # основной DNS — через VPN
        },
        {
            "tag"             : "remote2",
            "address"         : secondary_remote if "://" in secondary_remote else f"tls://{secondary_remote}",
            "address_resolver": "bootstrap",
            "detour"          : "proxy",   # резервный DNS — через VPN
        },
        {
            "tag"    : "bootstrap",
            "address": "udp://223.5.5.5",
            "detour" : "direct",           # только для резолва адреса DoH-сервера
        },
    ]

    dns_rules = [
        {"domain_suffix": [".local", ".lan", ".internal"], "server": "bootstrap"},
    ]

    if fakedns:
        dns_servers.insert(0, {"tag": "dns-fake", "address": "fakeip"})
        dns_rules.insert(0, {"query_type": ["A", "AAAA"], "server": "dns-fake"})

    # ── Routing rules ─────────────────────────────────────────────────
    base_rules = [
        {"protocol": ["dns"], "outbound": "dns-out"},
        {"ip_is_private": True, "outbound": "direct"},
    ]

    try:
        endpoint_ip = ipaddress.ip_address(server["endpoint"])
        base_rules.insert(1, {"ip_cidr": [f"{endpoint_ip}/{endpoint_ip.max_prefixlen}"], "outbound": "direct"})
    except ValueError:
        base_rules.insert(1, {"domain": [server["endpoint"]], "outbound": "direct"})

    # Блокировка UDP (кроме DNS)
    if block_udp:
        base_rules.append({"network": "udp", "outbound": "block"})

    if routing_mode == "whitelist" and routed_apps:
        app_rules = [
            {"process_name": routed_apps, "outbound": "proxy"},
            {"outbound": "direct"},
        ]
    elif routing_mode == "whitelist":
        app_rules = [{"outbound": "direct"}]
    elif routing_mode == "blacklist" and routed_apps:
        app_rules = [
            {"process_name": routed_apps, "outbound": "direct"},
            {"outbound": "proxy"},
        ]
    else:
        app_rules = [{"outbound": "proxy"}]

    # ── SOCKS5 / HTTP inbounds ────────────────────────────────────────
    auth_users = []
    if socks5_auth and socks5_auth.get("user") and socks5_auth.get("pass"):
        auth_users = [{"username": socks5_auth["user"], "password": socks5_auth["pass"]}]

    proxy_listen = "0.0.0.0" if allow_lan else "127.0.0.1"
    socks_inbound = {
        "type"       : "socks",
        "tag"        : "socks-in",
        "listen"     : proxy_listen,
        "listen_port": socks_port,
        "sniff"      : True,
    }
    if auth_users:
        socks_inbound["users"] = auth_users

    http_inbound = {
        "type"       : "http",
        "tag"        : "http-in",
        "listen"     : proxy_listen,
        "listen_port": http_port,
        "sniff"      : True,
    }
    if auth_users:
        http_inbound["users"] = auth_users

    cfg = {
        "log": {"level": "info", "timestamp": True},
        "experimental": {
            "clash_api": {
                "external_controller": f"127.0.0.1:{clash_port}",
                "secret": "",
            }
        },
        "dns": {
            "servers"          : dns_servers,
            "rules"            : dns_rules,
            "final"            : "remote",
            "independent_cache": True,
            "strategy"         : ip_strategy,
        },
        "inbounds": [
            {
                "type"                      : "tun",
                "tag"                       : "tun-in",
                "address"                   : ["172.19.0.1/30"],
                "mtu"                       : 9000,
                "auto_route"                : True,
                "strict_route"              : kill_switch,
                "sniff"                     : True,
                "sniff_override_destination": True,
                "stack"                     : "system",
            },
            socks_inbound,
            http_inbound,
        ],
        "outbounds": [
            outbound,
            {"type": "direct", "tag": "direct"},
            {"type": "block",  "tag": "block"},
            {"type": "dns",    "tag": "dns-out"},
        ],
        "route": {
            "rules"                : base_rules + app_rules,
            "final"                : "proxy",
            "auto_detect_interface": True,
        },
    }

    if fakedns:
        cfg["dns"]["fakeip"] = {
            "enabled"    : True,
            "inet4_range": "198.18.0.0/15",
            "inet6_range": "fc00::/18",
        }

    return cfg
