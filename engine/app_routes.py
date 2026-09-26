"""Resolve explicit per-process destinations, never silently substitute servers."""
import copy
import hashlib


def assignments(apps, groups):
    lookup = {s.get("ui_id"): s for g in groups for s in g.get("servers", []) if s.get("ui_id")}
    result = []
    for app in apps:
        destination = app.get("destination", "default")
        if app.get("enabled") is False or destination == "default":
            continue
        exe = app.get("exe", "")
        if not exe or any(c in exe for c in ",()\r\n\\/"):
            raise ValueError("Недопустимое имя процесса в индивидуальном маршруте")
        if destination == "direct":
            result.append({"exe": exe, "tag": "DIRECT", "server": None})
        elif isinstance(destination, str) and destination.startswith("server:"):
            identity = destination[7:]
            if identity not in lookup:
                raise ValueError(f"Сервер правила {exe} больше не найден. Выберите другой сервер в маршрутизации.")
            result.append({"exe": exe, "tag": "app-" + hashlib.sha256(identity.encode()).hexdigest()[:16], "server": copy.deepcopy(lookup[identity])})
        else:
            raise ValueError("Неизвестное назначение индивидуального маршрута")
    return result


def build_multi_route_config(server, routes, **settings):
    from engine.core_config import build_mihomo_config
    return apply_routes(build_mihomo_config(server, **settings), routes)


def apply_routes(config, routes):
    """Добавить правила и индивидуальные серверы к готовой конфигурации Mihomo.

    Основной outbound называется proxy и может быть любым — в том числе
    обычным WireGuard, поэтому правила работают и в режиме WG.
    """
    from engine.core_config import _mihomo_proxy
    if not routes:
        return config
    if any(r.get('match', '').startswith(('GEOSITE,', 'GEOIP,')) for r in routes):
        config['geodata-mode'] = True
    added = {"proxy"}
    rules = []
    for route in routes:
        if route["server"] is not None and route["tag"] not in added:
            proxy = _mihomo_proxy(route["server"])
            proxy["name"] = route["tag"]
            config["proxies"].append(proxy)
            added.add(route["tag"])
        match = route["match"] if "match" in route else f"PROCESS-NAME,{route['exe']}"
        rules.append(f"{match},{route['tag']}")
    # Keep LAN bypass and global UDP block ahead of per-process overrides;
    # explicit routes precede the broad whitelist/blacklist rules and MATCH.
    index = next(i for i, rule in enumerate(config["rules"]) if rule.startswith(("PROCESS-NAME,", "MATCH,")))
    config["rules"][index:index] = rules
    return config
