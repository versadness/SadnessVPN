"""
engine/config.py — парсинг VLESS ссылок и генерация конфигов sing-box
Новое: kill_switch, block_udp, socks5_auth, dns_preset, fakedns,
       mux (мультиплексирование), preferred_ip, фрагментация

ИСПРАВЛЕНИЯ:
  - dns-xbox-bootstrap: detour изменён с proxy → direct
    (raw IP не требует резолва, proxy создавал петлю UDP/53 через TUN)
  - Все Xbox DNS серверы используют detour: direct вместо proxy
  - dns-proxy в Xbox режиме использует отдельный чистый сервер (tls://8.8.8.8)
  - Добавлен перехват TCP/853 (DoT) в routing rules
  - Xbox DNS не поддерживает AAAA: добавлен блок AAAA→dns-block для xbox/xbox_dot
  - preferred_ip: "auto" теперь принудительно prefer_ipv4 во всех пресетах
"""

import base64
import re
import urllib.parse
import urllib.request


SUPPORTED_SCHEMES = ("vless://", "ss://", "trojan://", "hysteria2://", "hy2://")


# ─── DNS пресеты ──────────────────────────────────────────────────────────────

DNS_PRESETS = {
    "cf_google":  {"remote": ["tls://1.1.1.1",      "tls://8.8.8.8"],          "local": "8.8.8.8"},
    "google":     {"remote": ["tls://8.8.8.8",      "tls://8.8.4.4"],          "local": "8.8.4.4"},
    "cloudflare": {"remote": ["tls://1.1.1.1",      "tls://1.0.0.1"],          "local": "1.0.0.1"},
    "quad9":      {"remote": ["tls://9.9.9.9",      "tls://149.112.112.112"],  "local": "9.9.9.9"},
    # Xbox Smart DNS (xbox-dns.ru) — разблокирует различные сервисы
    # через подмену DNS ответов. Запросы идут НАПРЯМУЮ (не через VPN туннель).
    # ВАЖНО: Xbox DNS отвечает только на A (IPv4), AAAA запросы он не обрабатывает —
    # поэтому в xbox/xbox_dot режиме AAAA принудительно блокируется.
    "xbox":     {"remote": ["udp://111.88.96.50", "udp://111.88.96.51"],       "local": "111.88.96.50"},
    # DoT вариант Xbox DNS (зашифрованный, более надёжный):
    "xbox_dot": {"remote": ["tls://xbox-dns.ru",  "tls://xbox-dns.ru"],        "local": "111.88.96.50"},
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
        "type":          params.get("type", "tcp"),
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
        "encryption":    params.get("encryption", "none"),
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
    link = link.strip()
    if not (link.startswith("hysteria2://") or link.startswith("hy2://")):
        raise ValueError("Ожидается hysteria2:// или hy2:// ссылка")
    scheme = "hysteria2://" if link.startswith("hysteria2://") else "hy2://"
    rest = link[len(scheme):]
    remark = "Hysteria2"
    if "#" in rest:
        rest, remark_enc = rest.rsplit("#", 1)
        remark = urllib.parse.unquote(remark_enc)

    query_str = ""
    if "?" in rest:
        rest, query_str = rest.split("?", 1)

    if "@" in rest:
        auth, hostport = rest.rsplit("@", 1)
        password = urllib.parse.unquote(auth)
    else:
        hostport = rest
        password = ""

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
        "protocol":      "hysteria2",
        "remark":        remark,
        "host":          host,
        "port":          port,
        "password":      password,
        "sni":           params.get("sni", ""),
        "insecure":      params.get("insecure", "0") == "1",
        "obfs":          params.get("obfs", ""),
        "obfs_password": params.get("obfs-password", ""),
    }


# ─── Универсальный парсер ─────────────────────────────────────────────────────

def parse_link(link: str) -> dict:
    link = link.strip()
    if link.startswith("vless://"):
        return parse_vless_link(link)
    elif link.startswith("ss://"):
        return parse_ss_link(link)
    elif link.startswith("trojan://"):
        return parse_trojan_link(link)
    elif link.startswith(("hysteria2://", "hy2://")):
        return parse_hysteria2_link(link)
    else:
        raise ValueError(f"Неподдерживаемый протокол. Ожидается: vless://, ss://, trojan://, hysteria2://")


# ─── Построение sing-box outbound ─────────────────────────────────────────────

def _build_singbox_outbound(server: dict, mux: bool = False) -> dict:
    protocol = server.get("protocol", "vless")

    if protocol == "ss":
        outbound = {
            "type":        "shadowsocks",
            "tag":         "proxy",
            "server":      server["host"],
            "server_port": int(server["port"]),
            "method":      server["method"],
            "password":    server["password"],
        }
        if mux:
            outbound["multiplex"] = {
                "enabled": True, "protocol": "smux",
                "max_connections": 4, "min_streams": 4, "padding": False,
            }
        return outbound

    if protocol == "trojan":
        tls_block = {
            "enabled":     True,
            "server_name": server.get("sni", server["host"]) or server["host"],
        }
        if server.get("pinned_cert"):
            tls_block["pinned_peer_certificate_chain_sha256"] = [server["pinned_cert"]]
        else:
            tls_block["insecure"] = server.get("allowInsecure", "0") == "1"

        if server.get("fp"):
            tls_block["utls"] = {"enabled": True, "fingerprint": server["fp"]}
        if server.get("alpn"):
            tls_block["alpn"] = [a.strip() for a in server["alpn"].split(",")]
        outbound = {
            "type":        "trojan",
            "tag":         "proxy",
            "server":      server["host"],
            "server_port": int(server["port"]),
            "password":    server["password"],
            "tls":         tls_block,
        }
        net_type = server.get("type", "tcp")
        if net_type == "ws":
            outbound["transport"] = {
                "type": "ws",
                "path": server.get("path", "/"),
                "headers": {"Host": server.get("host_header") or server.get("sni") or server["host"]},
            }
        elif net_type == "grpc":
            outbound["transport"] = {"type": "grpc", "service_name": server.get("serviceName", "")}
        if mux:
            outbound["multiplex"] = {
                "enabled": True, "protocol": "smux",
                "max_connections": 4, "min_streams": 4, "padding": False,
            }
        return outbound

    if protocol == "hysteria2":
        tls_block = {
            "enabled":     True,
            "server_name": server.get("sni", server["host"]) or server["host"],
        }
        if server.get("pinned_cert"):
            tls_block["pinned_peer_certificate_chain_sha256"] = [server["pinned_cert"]]
        else:
            tls_block["insecure"] = server.get("insecure", False)

        outbound = {
            "type":        "hysteria2",
            "tag":         "proxy",
            "server":      server["host"],
            "server_port": int(server["port"]),
            "password":    server["password"],
            "tls":         tls_block,
        }
        if server.get("obfs") == "salamander":
            outbound["obfs"] = {"type": "salamander", "password": server.get("obfs_password", "")}
        # Hysteria2 has its own multiplexing — skip sing-box mux
        return outbound

    # ── VLESS (default) ───────────────────────────────────────────────────────
    security = server.get("security", "none")
    net_type = server.get("type", "tcp")
    outbound = {
        "type":            "vless",
        "tag":             "proxy",
        "server":          server["host"],
        "server_port":     int(server["port"]),
        "uuid":            server["uuid"],
        "flow":            server.get("flow", ""),
        "packet_encoding": "xudp",
    }
    if security == "reality":
        outbound["tls"] = {
            "enabled":     True,
            "server_name": server.get("sni", server["host"]),
            "utls":    {"enabled": True, "fingerprint": server.get("fp", "chrome")},
            "reality": {"enabled": True, "public_key": server.get("pbk", ""), "short_id": server.get("sid", "")},
        }
    elif security == "tls":
        tls_block = {
            "enabled":     True,
            "server_name": server.get("sni", server["host"]),
        }
        if server.get("pinned_cert"):
            tls_block["pinned_peer_certificate_chain_sha256"] = [server["pinned_cert"]]
        else:
            tls_block["insecure"] = server.get("allowInsecure", "0") == "1"

        if server.get("fp"):
            tls_block["utls"] = {"enabled": True, "fingerprint": server["fp"]}
        if server.get("alpn"):
            tls_block["alpn"] = [a.strip() for a in server["alpn"].split(",")]
        outbound["tls"] = tls_block
    if net_type == "ws":
        outbound["transport"] = {
            "type": "ws",
            "path": server.get("path", "/"),
            "headers": {"Host": server.get("host_header") or server.get("sni") or server["host"]},
        }
    elif net_type == "grpc":
        outbound["transport"] = {"type": "grpc", "service_name": server.get("serviceName", "")}
    elif net_type == "http":
        outbound["transport"] = {
            "type": "http",
            "path": server.get("path", "/"),
            "host": [server.get("host_header") or server["host"]],
        }
    elif net_type == "httpupgrade":
        outbound["transport"] = {
            "type": "httpupgrade",
            "path": server.get("path", "/"),
            "host": server.get("host_header") or server["host"],
        }

    # Мультиплексирование — не совместимо с Reality/flow
    if mux and not server.get("flow") and security != "reality":
        outbound["multiplex"] = {
            "enabled":         True,
            "protocol":        "smux",
            "max_connections": 4,
            "min_streams":     4,
            "padding":         False,
        }

    return outbound


# ─── Построение конфига sing-box TUN ─────────────────────────────────────────

def build_xray_tun_config(
    server         : dict,
    socks_port     : int  = 1080,
    http_port      : int  = 8080,
    routing_mode   : str  = "all",
    routed_apps    : list = None,
    # ── Параметры туннеля ──
    kill_switch    : bool = False,
    block_udp      : bool = False,
    socks5_auth    : dict = None,
    dns_preset     : str  = "cf_google",
    custom_dns     : list = None,
    fakedns        : bool = False,
    mux            : bool = False,
    preferred_ip   : str  = "ipv4",
) -> dict:
    routed_apps = routed_apps or []

    need_process_routing = routing_mode in ("whitelist", "blacklist") and bool(routed_apps)

    proxy_outbound = _build_singbox_outbound(server, mux=mux)

    # ── Определяем режим Xbox Smart DNS ──────────────────────────────
    use_xbox_smartdns = dns_preset in ("xbox", "xbox_dot")

    # ── DNS серверы ───────────────────────────────────────────────────
    if dns_preset == "custom" and custom_dns:
        remote_dns = [
            f"tls://{d}" if not d.startswith(("tls://", "https://", "udp://")) else d
            for d in custom_dns
        ]
        local_dns = custom_dns[0] if custom_dns else "8.8.8.8"
    else:
        preset     = DNS_PRESETS.get(dns_preset, DNS_PRESETS["cf_google"])
        remote_dns = preset["remote"]
        local_dns  = preset["local"]

    # IP-стратегия
    # "auto" и "ipv4" оба дают prefer_ipv4 — Xbox DNS не поддерживает AAAA,
    # поэтому IPv6 запросы принудительно блокируются в xbox/xbox_dot режиме ниже.
    ip_strategy_map = {"ipv4": "prefer_ipv4", "ipv6": "prefer_ipv6", "auto": "prefer_ipv4"}
    ip_strategy = ip_strategy_map.get(preferred_ip, "prefer_ipv4")

    # ── DNS блок ─────────────────────────────────────────────────────
    #
    # Архитектура Xbox Smart DNS (Вариант Б):
    #
    # dns-xbox-bootstrap → raw IP (udp://111.88.96.50), detour: direct
    #   Не требует резолва, поэтому безопасен с direct — не создаёт петлю через TUN.
    #
    # dns-direct / dns-direct2 → tls://xbox-dns.ru, через bootstrap, detour: direct
    #   Xbox DNS подменяет IP в ответах для разблокировки сервисов.
    #   ВАЖНО: Xbox DNS не отвечает на AAAA — блокируем их отдельным правилом.

    if use_xbox_smartdns:
        xbox_ip_bootstrap = "udp://111.88.96.50"
        dns_servers = [
            # Бутстрап по raw IP — ТОЛЬКО direct, иначе петля через TUN
            {
                "tag":     "dns-xbox-bootstrap",
                "address": xbox_ip_bootstrap,
                "detour":  "direct",
            },
            # Основной DNS (Xbox Smart DNS) — резолвит через бутстрап напрямую
            {
                "tag":              "dns-direct",
                "address":          remote_dns[0],
                "address_resolver": "dns-xbox-bootstrap",
                "detour":           "direct",
            },
            # Резервный DNS (Xbox Smart DNS)
            {
                "tag":              "dns-direct2",
                "address":          remote_dns[1] if len(remote_dns) > 1 else remote_dns[0],
                "address_resolver": "dns-xbox-bootstrap",
                "detour":           "direct",
            },
            # Локальный DNS
            {
                "tag":              "dns-local",
                "address":          xbox_ip_bootstrap,
                "address_resolver": "dns-xbox-bootstrap",
                "detour":           "direct",
            },
            # Блокировщик AAAA — Xbox DNS не поддерживает IPv6 запросы,
            # они падают с "context canceled". Возвращаем пустой ответ.
            {
                "tag":     "dns-block-aaaa",
                "address": "rcode://success",
            },
        ]
    else:
        dns_servers = [
            {
                "tag":     "dns-direct",
                "address": remote_dns[0],
                "detour":  "direct",
            },
            {
                "tag":     "dns-direct2",
                "address": remote_dns[1] if len(remote_dns) > 1 else remote_dns[0],
                "detour":  "direct",
            },
            {
                "tag":     "dns-local",
                "address": f"udp://{local_dns}",
                "detour":  "direct",
            },
        ]

    dns_rules = []

    if fakedns:
        dns_servers.append({
            "tag":     "dns-fake",
            "address": "fakeip",
        })
        dns_rules.insert(0, {
            "query_type": ["A", "AAAA"],
            "server":     "dns-fake",
        })

    # ── Блокировка AAAA в Xbox DNS режиме ────────────────────────────
    # Xbox DNS (111.88.96.50 / xbox-dns.ru) обрабатывает только A записи.
    # AAAA запросы зависают и падают с "exchange6: context canceled".
    # Решение: перехватываем все AAAA запросы и возвращаем пустой успешный ответ
    # через специальный dns-block-aaaa сервер (rcode://success).
    if use_xbox_smartdns:
        dns_rules.insert(0, {
            "query_type": ["AAAA"],
            "server":     "dns-block-aaaa",
        })

    # Базовое правило: все остальные DNS запросы — напрямую
    dns_rules.append({"outbound": "any", "server": "dns-direct"})

    # ── Правила маршрутизации трафика ────────────────────────────────
    rules = []
    # UDP/53 — стандартный DNS
    rules.append({"network": "udp", "port": 53, "outbound": "dns-out"})
    # TCP/853 — DNS over TLS (DoT), используется cloudflare/google/xbox_dot пресетами
    rules.append({"network": "tcp", "port": 853, "outbound": "dns-out"})
    rules.append({"ip_is_private": True, "outbound": "direct"})

    if block_udp:
        rules.append({"network": "udp", "outbound": "block"})

    if routing_mode == "whitelist" and routed_apps:
        rules.append({"process_name": routed_apps, "outbound": "proxy"})
        rules.append({"outbound": "direct"})
    elif routing_mode == "blacklist" and routed_apps:
        rules.append({"process_name": routed_apps, "outbound": "direct"})

    # ── SOCKS5 / HTTP inbounds ────────────────────────────────────────
    auth_users = []
    if socks5_auth and socks5_auth.get("user") and socks5_auth.get("pass"):
        auth_users = [{"username": socks5_auth["user"], "password": socks5_auth["pass"]}]

    socks_inbound = {
        "type": "socks", "tag": "socks-in",
        "listen": "127.0.0.1", "listen_port": socks_port,
        "sniff": True,
        "sniff_override_destination": True,
    }
    if auth_users:
        socks_inbound["users"] = auth_users

    http_inbound = {
        "type": "http", "tag": "http-in",
        "listen": "127.0.0.1", "listen_port": http_port,
        "sniff": True,
        "sniff_override_destination": True,
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
            "servers":  dns_servers,
            "rules":    dns_rules,
            "final":    "dns-direct",
            "strategy": ip_strategy,
        },
        "inbounds": [
            {
                "type": "tun", "tag": "tun-in",
                "inet4_address": "172.19.0.1/30",
                "auto_route":   True,
                "strict_route": kill_switch,
                "stack":  "system",
                "sniff":  True,
                "sniff_override_destination": True,
            },
            socks_inbound,
            http_inbound,
        ],
        "outbounds": [
            proxy_outbound,
            {"type": "direct", "tag": "direct"},
            {"type": "block",  "tag": "block"},
            {"type": "dns",    "tag": "dns-out"},
        ],
        "route": {
            "rules":                 rules,
            "final":                 "proxy",
            "auto_detect_interface": True,
            "find_process":          need_process_routing,
        },
    }

    if fakedns:
        cfg["dns"]["fakeip"] = {
            "enabled":     True,
            "inet4_range": "198.18.0.0/15",
            "inet6_range": "fc00::/18",
        }

    return cfg


# ─── Загрузка подписки ────────────────────────────────────────────────────────

def fetch_subscription(url: str, hwid: str = "") -> list:
    raw = ""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Happ/2.9.1 (Windows; amd64)",
            "Accept":     "*/*",
            "HWID":       hwid,
            "X-HWID":     hwid,
            "Device-Id":  hwid,
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
            raw = data.decode("utf-8", errors="ignore")

        if not any(x in raw[:200] for x in ("vless://", "proxies:", "---", "{")):
            try:
                raw = base64.b64decode(data + b"==").decode("utf-8", errors="ignore")
            except Exception:
                pass

        if "не поддерживается" in raw or "0.0.0.0" in raw:
            raw = ""
    except Exception:
        raw = ""

    if not raw:
        return []

    servers = []

    # Парсим ссылки всех поддерживаемых протоколов
    if any(s in raw for s in SUPPORTED_SCHEMES):
        for line in raw.splitlines():
            line = line.strip()
            if any(line.startswith(s) for s in SUPPORTED_SCHEMES):
                try:
                    servers.append(parse_link(line))
                except Exception:
                    pass

    # Парсим Clash YAML
    elif "proxies:" in raw:
        blocks = re.split(r'\n\s*-\s+', raw)
        for block in blocks:
            try:
                btype = (re.search(r'type:\s*(\S+)', block) or re.search(r'type:(\S+)', block))
                if not btype:
                    continue
                ptype = btype.group(1).lower().strip('"\'')

                name   = re.search(r'name:\s*["\']?(.+?)["\']?\s*$', block, re.M)
                server = re.search(r'server:\s*(\S+)', block)
                port   = re.search(r'port:\s*(\d+)', block)
                if not all([name, server, port]):
                    continue

                remark = name.group(1).strip()
                host   = server.group(1).strip()
                pport  = int(port.group(1))

                if ptype == "vless":
                    uuid    = re.search(r'uuid:\s*(\S+)', block)
                    if not uuid:
                        continue
                    network = re.search(r'network:\s*(\S+)', block)
                    sni     = re.search(r'servername:\s*(\S+)', block)
                    tls     = 'tls: true' in block or "tls:true" in block
                    flow    = re.search(r'flow:\s*(\S+)', block)
                    pbk     = re.search(r'public-key:\s*(\S+)', block)
                    sid     = re.search(r'short-id:\s*(\S+)', block)
                    fp      = re.search(r'fingerprint:\s*(\S+)', block)
                    servers.append({
                        "remark":        remark,
                        "host":          host,
                        "port":          pport,
                        "uuid":          uuid.group(1).strip(),
                        "security":      "reality" if pbk else ("tls" if tls else "none"),
                        "type":          network.group(1).strip() if network else "tcp",
                        "sni":           sni.group(1).strip() if sni else "",
                        "fp":            fp.group(1).strip() if fp else "",
                        "pbk":           pbk.group(1).strip() if pbk else "",
                        "sid":           sid.group(1).strip() if sid else "",
                        "flow":          flow.group(1).strip() if flow else "",
                        "path":          "",
                        "host_header":   "",
                        "serviceName":   "",
                        "alpn":          "",
                        "allowInsecure": "0",
                        "encryption":    "none",
                    })

                elif ptype == "ss":
                    cipher   = re.search(r'cipher:\s*(\S+)', block)
                    password = re.search(r'password:\s*["\']?(.+?)["\']?\s*$', block, re.M)
                    if not cipher or not password:
                        continue
                    servers.append({
                        "protocol": "ss",
                        "remark":   remark,
                        "host":     host,
                        "port":     pport,
                        "method":   cipher.group(1).strip(),
                        "password": password.group(1).strip(),
                    })

                elif ptype == "trojan":
                    password = re.search(r'password:\s*["\']?(.+?)["\']?\s*$', block, re.M)
                    sni      = re.search(r'sni:\s*(\S+)', block)
                    if not password:
                        continue
                    servers.append({
                        "protocol":      "trojan",
                        "remark":        remark,
                        "host":          host,
                        "port":          pport,
                        "password":      password.group(1).strip(),
                        "sni":           sni.group(1).strip() if sni else "",
                        "allowInsecure": "1" if ("skip-cert-verify: true" in block) else "0",
                        "alpn": "", "fp": "", "type": "tcp", "path": "",
                        "host_header": "", "serviceName": "",
                    })

                elif ptype in ("hysteria2", "hy2"):
                    password = re.search(r'password:\s*["\']?(.+?)["\']?\s*$', block, re.M)
                    sni      = re.search(r'sni:\s*(\S+)', block)
                    if not password:
                        continue
                    servers.append({
                        "protocol": "hysteria2",
                        "remark":   remark,
                        "host":     host,
                        "port":     pport,
                        "password": password.group(1).strip(),
                        "sni":      sni.group(1).strip() if sni else "",
                        "insecure": "skip-cert-verify: true" in block,
                        "obfs": "", "obfs_password": "",
                    })

            except Exception:
                pass

    return servers
