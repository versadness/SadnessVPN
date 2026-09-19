"""Choose a core from transport capabilities and build its owned configuration."""
from engine.config import build_singbox_config, DNS_PRESETS
from engine.transports import mihomo_xhttp

CORES = ("auto", "singbox", "mihomo")


def choose_core(server, preference="auto"):
    if preference not in CORES:
        raise ValueError("Неизвестное ядро")
    if server.get("protocol") == "hysteria2":
        from engine.hysteria2 import validate, requires_mihomo
        validate(server)
        if preference == "auto":
            return "mihomo" if requires_mihomo(server) else "singbox"
        if preference == "singbox" and requires_mihomo(server):
            raise ValueError("HY2: для этих параметров выберите Авто / Mihomo")
        return preference
    if server.get("type") in {"xhttp", "splithttp"}:
        if preference == "singbox":
            raise ValueError("sing-box не поддерживает XHTTP. Выберите Авто или Mihomo.")
        # Report an unsupported option now, with the link in hand, instead of
        # letting the core fail to start after the TUN is already up.
        mihomo_xhttp(server)
        return "mihomo"
    return "singbox" if preference == "auto" else preference


def _mihomo_proxy(server):
    proto = server.get("protocol", "vless")
    if proto not in {"vless", "ss", "trojan", "hysteria2"}:
        raise ValueError("Этот протокол не поддерживается интеграцией Mihomo")
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
        from engine.hysteria2 import validate
        validate(server)
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
        if proto != "vless":
            raise ValueError("Mihomo поддерживает XHTTP для VLESS")
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
    elif network != "tcp":
        raise ValueError("Неподдерживаемый транспорт Mihomo: " + str(network))
    return proxy


def build_mihomo_config(server, socks_port=1080, http_port=8080, clash_port=9090,
                        routing_mode="all", routed_apps=None, **settings):
    proxy = _mihomo_proxy(server)
    if settings.get("mux") and proxy["type"] != "hysteria2" and proxy.get("network") != "xhttp" and not proxy.get("flow"):
        proxy["smux"] = {"enabled": True, "protocol": "smux", "max-connections": 4}
    preset = settings.get("dns_preset", "cf_google")
    dns = settings.get("custom_dns") if preset == "custom" else DNS_PRESETS.get(preset, DNS_PRESETS["cf_google"])["remote"]
    dns = [x.removeprefix("udp://") for x in (dns or DNS_PRESETS["cf_google"]["remote"])]
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
    ipv6 = settings.get("preferred_ip", "ipv4") != "ipv4" and preset not in {"xbox", "xbox_dot"}
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
        "dns": {"enable": True, "ipv6": ipv6, "enhanced-mode": "fake-ip" if settings.get("fakedns") else "redir-host",
                "fake-ip-range": "198.18.0.1/16" if settings.get("fakedns") else "172.19.0.1/30", "nameserver": dns,
                "proxy-server-nameserver": ["1.1.1.1", "8.8.8.8"],
                "default-nameserver": ["1.1.1.1", "8.8.8.8"]},
        "proxies": [proxy], "rules": rules,
    }
    auth = settings.get("socks5_auth")
    if auth:
        config["authentication"] = [auth["user"] + ":" + auth["pass"]]
        config["skip-auth-prefixes"] = []
    return config


def build_proxy_config(server, preference="auto", **settings):
    if choose_core(server, preference) == "mihomo":
        return build_mihomo_config(server, **settings)
    return build_singbox_config(server, **settings)
