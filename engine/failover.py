"""Смена сервера на лету и автоматический резерв — средствами Mihomo.

Конфигурация ядра содержит не один сервер, а все поддерживаемые серверы из
подписок и три группы:

  manual  (select)    — сервер, выбранный пользователем. Переключается через
                        API ядра без перезапуска: TUN, маршруты и DNS остаются.
  backup  (url-test)  — до BACKUP_LIMIT запасных из подписки выбранного сервера,
                        на том же транспорте и на других машинах (pick_backups);
                        ядро само держит в ней сервер с наименьшей задержкой.
  proxy   (fallback)  — [manual, backup]: пока выбранный сервер отвечает, трафик
                        идёт через него; перестал — через лучший запасной; ожил —
                        снова через выбранный.

Все правила маршрутизации уже ссылаются на «proxy», поэтому остаются без
изменений. Без резерва «proxy» — это просто [manual].
"""
from __future__ import annotations

import hashlib
import ipaddress
import socket

from engine.core_config import _mihomo_proxy, ensure_supported

MANUAL_GROUP = "manual"
BACKUP_GROUP = "backup"
MAIN_GROUP = "proxy"
BACKUP_LIMIT = 4
HEALTH_URL = "https://www.gstatic.com/generate_204"


def proxy_name(server: dict) -> str:
    """Стабильное имя сервера в ядре. Адрес и ключи в имя не попадают."""
    ident = server.get("ui_id")
    if not ident:
        raw = f"{server.get('host')}:{server.get('port')}:{server.get('remark')}"
        ident = hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()[:12]
    return "srv-" + str(ident)


def country(server: dict) -> str:
    """Код страны по флагу в названии сервера (🇩🇪 → DE) или пустая строка."""
    letters = [chr(ord(ch) - 0x1F1E6 + ord("A")) for ch in str(server.get("remark", ""))
               if 0x1F1E6 <= ord(ch) <= 0x1F1FF]
    return "".join(letters[:2]) if len(letters) >= 2 else ""


def transport(server: dict) -> str:
    return "quic" if server.get("protocol") == "hysteria2" else server.get("type", "tcp")


def _supported(server) -> bool:
    try:
        ensure_supported(server)
        _mihomo_proxy(server)
        return True
    except (ValueError, KeyError, TypeError):
        return False


def machine(server: dict, resolve=None) -> frozenset:
    """Адреса машины, на которой работает сервер.

    Серверы одной подписки часто стоят на одной машине на разных портах
    («Finland» и «Finland 2») и падают вместе — такой сервер запасным быть не
    может. Домен превращается в адреса; если имя не разрешилось, сравнивается
    само имя.
    """
    host = str(server.get("host") or "").strip().lower().strip("[]")
    try:
        return frozenset({str(ipaddress.ip_address(host))})
    except ValueError:
        pass
    resolve = resolve or _resolve
    return frozenset(resolve(host)) or frozenset({host})


def _resolve(host: str) -> set:
    try:
        return {item[4][0] for item in socket.getaddrinfo(host, None)}
    except (OSError, UnicodeError):
        return set()


def pick_backups(selected: dict, groups: list, limit: int = BACKUP_LIMIT, resolve=None) -> list:
    """Запасные серверы по порядку предпочтения.

    Только подписка выбранного сервера и только тот же транспорт (HY2 → HY2,
    XHTTP → XHTTP). Серверы на той же машине, что и выбранный, не берутся —
    они откажут вместе с ним; среди запасных — не больше одного на машину,
    чтобы все они не зависели от одного железа. Сначала та же страна. Пинг
    среди отобранных ядро меряет само (группа url-test).
    """
    home = next((g for g in groups if any(s is selected for s in g.get("servers", []))), None)
    if home is None:
        return []
    home_country = country(selected)
    used = set(machine(selected, resolve))
    candidates = []
    for server in home.get("servers", []):
        if server is selected or proxy_name(server) == proxy_name(selected):
            continue
        if transport(server) != transport(selected) or not _supported(server):
            continue
        same_country = bool(home_country) and country(server) == home_country
        candidates.append((not same_country, len(candidates), server))
    backups = []
    for _, _, server in sorted(candidates, key=lambda item: (item[0], item[1])):
        addresses = machine(server, resolve)
        if addresses & used:
            continue
        used |= addresses
        backups.append(server)
        if len(backups) == limit:
            break
    return backups


def _with_mux(proxy: dict, mux: bool) -> dict:
    # То же условие, что в core_config.assemble_config для основного сервера.
    if mux and proxy["type"] not in {"hysteria2", "wireguard"} and proxy.get("network") != "xhttp" \
            and not proxy.get("flow"):
        proxy["smux"] = {"enabled": True, "protocol": "smux", "max-connections": 4}
    return proxy


def apply_server_groups(config: dict, selected: dict, groups: list, failover: bool = True,
                        mux: bool = False) -> dict:
    """Превратить одиночный «proxy» в группы manual/backup/proxy.

    Возвращает {имя в ядре: сервер} — по нему приложение переключает сервер
    на лету и показывает, через какой сервер идёт трафик.
    """
    proxies = config["proxies"]
    main = next(p for p in proxies if p.get("name") == MAIN_GROUP)
    main_name = proxy_name(selected)
    main["name"] = main_name
    live = {main_name: selected}
    for group in groups:
        for server in group.get("servers", []):
            name = proxy_name(server)
            if name in live or not _supported(server):
                continue
            proxy = _with_mux(_mihomo_proxy(server), mux)
            proxy["name"] = name
            proxies.append(proxy)
            live[name] = server

    manual = [main_name] + [name for name in live if name != main_name]
    groups_config = [{"name": MANUAL_GROUP, "type": "select", "proxies": manual}]
    backups = [proxy_name(server) for server in pick_backups(selected, groups)] if failover else []
    if backups:
        groups_config.append({
            "name": BACKUP_GROUP, "type": "url-test", "proxies": backups,
            "url": HEALTH_URL, "interval": 60, "tolerance": 50, "timeout": 5000, "lazy": False,
        })
        groups_config.append({
            "name": MAIN_GROUP, "type": "fallback", "proxies": [MANUAL_GROUP, BACKUP_GROUP],
            "url": HEALTH_URL, "interval": 30, "timeout": 5000, "lazy": False,
            # Несколько неудачных соединений подряд — немедленная перепроверка,
            # не дожидаясь интервала.
            "max-failed-times": 3,
        })
    else:
        groups_config.append({"name": MAIN_GROUP, "type": "select", "proxies": [MANUAL_GROUP]})
    config["proxy-groups"] = groups_config
    return live
