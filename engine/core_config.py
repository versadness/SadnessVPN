"""Сборка конфигурации Mihomo — единственного сетевого ядра VPN.

Выбора ядра больше нет: sing-box удалён из проекта целиком, вместе с его
генератором конфигурации, бинарником и параметром настроек. Если конкретный
сервер не поддерживается Mihomo, это отказ с объяснением, а не тихий переход
на другое ядро — второго ядра не существует.
"""
from engine.config import DNS_PRESETS, SMART_DNS_BOOTSTRAP
from engine.transports import mihomo_xhttp

# Протоколы, которые реально собираются в outbound Mihomo.
SUPPORTED_PROTOCOLS = ("vless", "vmess", "ss", "trojan", "hysteria2")

# Транспорты, которые ядро умеет для прокси-протоколов поверх TCP.
SUPPORTED_NETWORKS = ("tcp", "ws", "httpupgrade", "grpc", "http", "h2", "xhttp", "splithttp")


def ensure_supported(server):
    """Проверить сервер против возможностей Mihomo до запуска ядра.

    Вызывается перед сборкой конфигурации и перед подключением: пользователь
    должен получить понятный отказ, а не падение ядра с уже поднятым TUN.
    """
    protocol = server.get("protocol", "vless")
    if protocol not in SUPPORTED_PROTOCOLS:
        raise ValueError(
            f"Протокол {protocol} не поддерживается ядром Mihomo. "
            "Другого ядра в приложении нет."
        )
    if protocol == "hysteria2":
        from engine.hysteria2 import validate
        validate(server)
        return server
    network = server.get("type", "tcp")
    if network not in SUPPORTED_NETWORKS:
        raise ValueError(f"Транспорт {network} не поддерживается ядром Mihomo")
    if network in {"xhttp", "splithttp"}:
        if protocol != "vless":
            raise ValueError("Mihomo поддерживает XHTTP только для VLESS")
        # Сообщить о неподдерживаемом параметре сейчас, пока ссылка под рукой,
        # а не после того, как TUN уже поднят.
        mihomo_xhttp(server)
    return server


def _mihomo_proxy(server):
    proto = server.get("protocol", "vless")
    ensure_supported(server)
    proxy = {"name": "proxy", "type": proto, "server": server["host"],
             "port": int(server["port"]), "udp": True}
    if proto == "ss":
        proxy.update(cipher=server["method"], password=server["password"])
        return proxy
    tls = server.get("security") in {"tls", "reality"} or proto in {"trojan", "hysteria2"}
    if proto == "vless":
        proxy.update(uuid=server["uuid"], tls=tls)
        if server.get("flow") not in (None, "", "none"):
            proxy["flow"] = server["flow"]
        if server.get("encryption") not in (None, "", "none"):
            proxy["encryption"] = server["encryption"]
    elif proto == "vmess":
        proxy.update(uuid=server["uuid"], tls=tls,
                     cipher=server.get("method") or "auto",
                     alterId=int(server.get("alter_id") or 0))
    else:
        proxy["password"] = server["password"]
    proxy["sni" if proto in {"trojan", "hysteria2"} else "servername"] = server.get("sni") or server["host"]
    proxy["skip-cert-verify"] = server.get("allowInsecure") == "1" or bool(server.get("insecure"))
    if server.get("fp"):
        proxy["client-fingerprint"] = server["fp"]
    if server.get("pinned_cert"):
        proxy["fingerprint"] = server["pinned_cert"]
    if server.get("verify_cert_name"):
        proxy["name-cert-verify"] = server["verify_cert_name"]
    if server.get("alpn"):
        proxy["alpn"] = [x.strip() for x in server["alpn"].split(",") if x.strip()]
    if server.get("security") == "reality":
        proxy["reality-opts"] = {"public-key": server.get("pbk", ""), "short-id": server.get("sid", "")}
    if proto == "hysteria2":
        from engine.hysteria2 import ech_opts
        if server.get("ech"):
            ech = ech_opts(server["ech"])
            if ech:
                proxy["ech-opts"] = ech
        if server.get("obfs"):
            proxy["obfs"] = server["obfs"]
            proxy["obfs-password"] = server.get("obfs_password", "")
        for source, target in (("ports", "ports"), ("hop_interval", "hop-interval"), ("up", "up"), ("down", "down")):
            if server.get(source):
                proxy[target] = server[source]
        return proxy
    network = server.get("type", "tcp")
    path, host = server.get("path") or "/", server.get("host_header") or server.get("sni") or server["host"]
    if network in {"xhttp", "splithttp"}:
        proxy["network"] = "xhttp"
        proxy["xhttp-opts"] = mihomo_xhttp(server)
        if not tls and not proxy.get("alpn"):
            proxy["alpn"] = ["http/1.1"]
    elif network in {"ws", "httpupgrade"}:
        proxy["network"] = "ws"
        proxy["ws-opts"] = {"path": path, "headers": {"Host": host}}
        if network == "httpupgrade":
            proxy["ws-opts"]["v2ray-http-upgrade"] = True
    elif network == "grpc":
        proxy["network"] = "grpc"
        proxy["grpc-opts"] = {"grpc-service-name": server.get("serviceName", "")}
    elif network in {"http", "h2"}:
        proxy["network"] = "h2"
        proxy["h2-opts"] = {"path": path, "host": [host]}
    return proxy


def _dns_block(settings, ipv6):
    """DNS-секция Mihomo с честной обработкой Smart DNS.

    Xbox/Comss подменяют ответы по реальному адресу клиента, поэтому их
    запросы обязаны уходить напрямую, а не через прокси; имя DoT-сервера
    резолвится бутстрапом по его же raw IP, иначе получается петля.
    """
    preset = settings.get("dns_preset", "cf_google")
    if preset == "custom":
        raw = settings.get("custom_dns") or []
    else:
        raw = DNS_PRESETS.get(preset, DNS_PRESETS["cf_google"])["remote"]
    nameserver = [x.removeprefix("udp://") for x in (raw or DNS_PRESETS["cf_google"]["remote"])]
    bootstrap = SMART_DNS_BOOTSTRAP.get(preset)
    default_nameserver = [bootstrap.removeprefix("udp://")] if bootstrap else ["1.1.1.1", "8.8.8.8"]
    dns = {
        "enable": True,
        "ipv6": ipv6,
        "enhanced-mode": "fake-ip" if settings.get("fakedns") else "redir-host",
        "fake-ip-range": "198.18.0.1/16" if settings.get("fakedns") else "172.19.0.1/30",
        "nameserver": nameserver,
        # Адрес самого VPN-сервера резолвится обычным публичным DNS в обход
        # туннеля: Smart DNS здесь не нужен, а петля — нужна ещё меньше.
        "proxy-server-nameserver": ["1.1.1.1", "8.8.8.8"],
        # Бутстрап имени DoT-сервера. Для Smart DNS это его же raw IP:
        # резолвить xbox-dns.ru через сам xbox-dns.ru нельзя.
        "default-nameserver": default_nameserver,
        # DNS не идёт через правила маршрутизации: Smart DNS обязан видеть
        # реальный адрес клиента, иначе подмена ответов не срабатывает.
        "respect-rules": False,
    }
    return dns


def build_mihomo_config(server, socks_port=1080, http_port=8080, clash_port=9090,
                        routing_mode="all", routed_apps=None, **settings):
    proxy = _mihomo_proxy(server)
    if settings.get("mux") and proxy["type"] != "hysteria2" and proxy.get("network") != "xhttp" and not proxy.get("flow"):
        proxy["smux"] = {"enabled": True, "protocol": "smux", "max-connections": 4}
    preset = settings.get("dns_preset", "cf_google")
    ipv6 = settings.get("preferred_ip", "ipv4") != "ipv4" and preset not in {"xbox", "xbox_dot"}
    rules = ["IP-CIDR,127.0.0.0/8,DIRECT,no-resolve", "IP-CIDR,10.0.0.0/8,DIRECT,no-resolve",
             "IP-CIDR,172.16.0.0/12,DIRECT,no-resolve", "IP-CIDR,192.168.0.0/16,DIRECT,no-resolve",
             "IP-CIDR6,fc00::/7,DIRECT,no-resolve", "IP-CIDR6,fe80::/10,DIRECT,no-resolve"]
    if settings.get("block_udp"):
        rules.append("NETWORK,UDP,REJECT")
    for exe in routed_apps or []:
        if any(ch in exe for ch in ",()\r\n"):
            raise ValueError("Имя приложения содержит недопустимые символы для правила Mihomo")
        if routing_mode in {"whitelist", "blacklist"}:
            rules.append(f"PROCESS-NAME,{exe}," + ("proxy" if routing_mode == "whitelist" else "DIRECT"))
    rules.append("MATCH," + ("DIRECT" if routing_mode == "whitelist" else "proxy"))
    config = {
        "socks-port": socks_port, "port": http_port, "allow-lan": bool(settings.get("allow_lan")),
        "bind-address": "*" if settings.get("allow_lan") else "127.0.0.1",
        "external-controller": f"127.0.0.1:{clash_port}", "mode": "rule", "log-level": "info",
        "ipv6": ipv6, "find-process-mode": "always", "geo-auto-update": False,
        "profile": {"store-selected": False, "store-fake-ip": False},
        "tun": {"enable": True, "device": "SadnessMihomo", "stack": "system",
                "auto-route": True, "auto-detect-interface": True,
                "strict-route": bool(settings.get("kill_switch")), "mtu": 1500,
                "dns-hijack": ["any:53", "tcp://any:53"]},
        "dns": _dns_block(settings, ipv6),
        "proxies": [proxy], "rules": rules,
    }
    auth = settings.get("socks5_auth")
    if auth:
        config["authentication"] = [auth["user"] + ":" + auth["pass"]]
        config["skip-auth-prefixes"] = []
    return config


def build_proxy_config(server, **settings):
    return build_mihomo_config(server, **settings)
