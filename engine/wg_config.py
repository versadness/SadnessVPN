"""
engine/wg_config.py — парсинг WireGuard/AmneziaWG конфигов и построение sing-box outbound
Новое: kill_switch, block_udp, socks5_auth, dns_preset, custom_dns, fakedns, preferred_ip
"""
import base64
import json
import re
import urllib.request

from engine.config import DNS_PRESETS


# AWG-специфичные поля которые не поддерживает sing-box
AWG_FIELDS = {"jc", "jmin", "jmax", "s1", "s2", "h1", "h2", "h3", "h4"}


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
        "mtu"              : 1280,
        "awg_fields"       : {},
        "is_awg"           : False,
        "remark"           : "",
        "force_full_route" : False,
    }

    section = None
    raw_allowed_ips = []

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            section = line.strip("[]").lower()
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
                        pass
                else:
                    result["endpoint"] = val
            elif key == "allowedips":
                raw_allowed_ips = [a.strip() for a in val.split(",")]
            elif key in AWG_FIELDS:
                result["awg_fields"][key] = val
                result["is_awg"] = True

    has_full_ipv4 = any(ip in ("0.0.0.0/0", "0.0.0.0/1") for ip in raw_allowed_ips)

    if raw_allowed_ips and not has_full_ipv4:
        result["allowed_ips"]      = ["0.0.0.0/0", "::/0"]
        result["force_full_route"] = True
    else:
        result["allowed_ips"] = raw_allowed_ips if raw_allowed_ips else ["0.0.0.0/0", "::/0"]

    dns_clean = [d for d in result["dns"] if ":" not in d]
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

    return result


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
    if not results and last_error:
        raise ValueError(f"Ошибка парсинга: {last_error}")
    return results


def fetch_wg_subscription(url: str) -> list:
    url = url.strip()
    req = urllib.request.Request(
        url, headers={"User-Agent": "SadnessVPN/1.0", "Accept": "*/*"}
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read()

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
                    servers.append(item)
            return servers
        except Exception:
            pass

    if not text:
        return []

    return parse_wg_conf(text)


def build_wg_tun_config(
    server         : dict,
    socks_port     : int  = 1080,
    http_port      : int  = 8080,
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
            "address"         : f"https://{primary_remote}/dns-query",
            "address_resolver": "bootstrap",
            "detour"          : "proxy",   # основной DNS — через VPN
        },
        {
            "tag"             : "remote2",
            "address"         : f"https://{secondary_remote}/dns-query",
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
        {"ip_cidr": [f"{server['endpoint']}/32"], "outbound": "direct"},
        {"ip_is_private": True, "outbound": "direct"},
    ]

    # Блокировка UDP (кроме DNS)
    if block_udp:
        base_rules.append({"network": "udp", "outbound": "block"})

    if routing_mode == "whitelist" and routed_apps:
        app_rules = [
            {"process_name": routed_apps, "outbound": "proxy"},
            {"outbound": "direct"},
        ]
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

    socks_inbound = {
        "type"       : "socks",
        "tag"        : "socks-in",
        "listen"     : "127.0.0.1",
        "listen_port": socks_port,
        "sniff"      : True,
    }
    if auth_users:
        socks_inbound["users"] = auth_users

    http_inbound = {
        "type"       : "http",
        "tag"        : "http-in",
        "listen"     : "127.0.0.1",
        "listen_port": http_port,
        "sniff"      : True,
    }
    if auth_users:
        http_inbound["users"] = auth_users

    cfg = {
        "log": {"level": "info", "timestamp": True},
        "experimental": {
            "clash_api": {
                "external_controller": "127.0.0.1:9090",
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
                "inet4_address"             : "172.19.0.1/30",
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
