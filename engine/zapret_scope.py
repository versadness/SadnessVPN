"""Эффективный охват Zapret простыми словами — из самой командной строки.

Пользователю нельзя показывать «работает для всего ПК», если часть трафика в
фильтры не попадает. Поэтому описание строится не из намерения, а из того, что
реально уйдёт в winws: портов ``--wf-tcp``/``--wf-udp`` после подстановки
игровых диапазонов, фильтров секций, списков сайтов и исключений.

Сама командная строка наружу не отдаётся: в интерфейс уходит только описание.
"""
from __future__ import annotations

import os

from engine import game_filter

# Что понимает конкретная секция стратегии. Строится по её фильтрам, а не по
# названию профиля: HTTP/TLS/QUIC-секцию нельзя выдавать за обработчик
# произвольных игровых пакетов.
_L7_LABELS = {
    "http": "HTTP",
    "tls": "TLS (HTTPS)",
    "quic": "QUIC (HTTP/3)",
    "discord": "Discord",
    "stun": "STUN (голос и P2P)",
    "wireguard": "WireGuard",
    "dht": "DHT",
    "unknown": "неопознанный трафик",
    "unknown_udp": "неопознанный UDP",
}

_WELL_KNOWN_PORTS = {
    "80": "HTTP",
    "443": "HTTPS / QUIC",
    "853": "DNS-over-TLS",
}


def _name(path: str) -> str:
    """Имя файла списка без путей и внутренних плейсхолдеров сборки."""
    return os.path.basename(path.replace("%LISTS%", "").replace("%BIN%", ""))


def _ports(values: str) -> list[str]:
    return [part for part in values.split(",") if part]


def _sections(args) -> list[list[str]]:
    sections, current = [], []
    for arg in args:
        if arg == "--new":
            sections.append(current)
            current = []
        else:
            current.append(arg)
    sections.append(current)
    return sections


def _section_protocols(section) -> list[str]:
    """Протоколы, которые секция действительно распознаёт."""
    found = []
    for arg in section:
        if arg.startswith("--filter-l7="):
            for name in _ports(arg.split("=", 1)[1]):
                found.append(_L7_LABELS.get(name, name))
        elif arg.startswith("--dpi-desync-fake-quic"):
            found.append(_L7_LABELS["quic"])
        elif arg.startswith(("--dpi-desync-fake-tls", "--dpi-desync-split-tls")):
            found.append(_L7_LABELS["tls"])
        elif arg.startswith("--dpi-desync-fake-discord"):
            found.append(_L7_LABELS["discord"])
        elif arg.startswith("--dpi-desync-fake-stun"):
            found.append(_L7_LABELS["stun"])
    if not found:
        # Секция без L7-фильтра работает по портам. По известным портам можно
        # честно назвать протокол, по игровым диапазонам — нет.
        for arg in section:
            if arg.startswith(("--filter-tcp=", "--filter-udp=")):
                for port in _ports(arg.split("=", 1)[1]):
                    label = _WELL_KNOWN_PORTS.get(port)
                    if label and label not in found:
                        found.append(label)
    if not found:
        found.append("трафик выбранных портов без разбора протокола")
    result = []
    for item in found:
        if item not in result:
            result.append(item)
    return result


def _limits(section) -> dict:
    hostlists = [arg.split("=", 1)[1] for arg in section if arg.startswith("--hostlist=")]
    domains = [arg.split("=", 1)[1] for arg in section if arg.startswith("--hostlist-domains=")]
    ipsets = [arg.split("=", 1)[1] for arg in section if arg.startswith("--ipset=")]
    excluded_lists = [arg.split("=", 1)[1] for arg in section
                      if arg.startswith(("--hostlist-exclude=", "--ipset-exclude="))]
    return {
        "hostlists": [_name(path) for path in hostlists],
        "domains": domains,
        "ipsets": [_name(path) for path in ipsets],
        "excludes": [_name(path) for path in excluded_lists],
    }


# Что происходит с охватом, когда одновременно работает VPN. Показывать
# «работает для всего ПК» при полном туннеле нельзя: обход применяется к
# остатку трафика вне туннеля.
VPN_NOTES = {
    "all": (
        "VPN включён в режиме «весь компьютер»: почти весь трафик уже идёт в "
        "туннеле и Zapret его не видит. Обход применяется к тому, что осталось "
        "снаружи — правилам DIRECT и локальной сети."
    ),
    "whitelist": (
        "VPN включён только для выбранных приложений: весь остальной трафик "
        "идёт напрямую и попадает под обход."
    ),
    "blacklist": (
        "VPN включён кроме выбранных приложений: под обход попадает трафик "
        "тех приложений, которые идут напрямую."
    ),
}


def describe(profile, config, vpn_mode=None) -> dict:
    """Описание охвата для интерфейса. profile — запись FLOWSEAL_PROFILES."""
    settings = game_filter.normalize(config)
    substitutions = game_filter.substitutions(settings)
    disabled = game_filter.DISABLED_PORTS

    args = []
    for arg in profile["args"]:
        for placeholder, value in substitutions.items():
            arg = arg.replace(placeholder, value)
        args.append(arg)

    tcp_ports, udp_ports = [], []
    for arg in args:
        if arg.startswith("--wf-tcp="):
            tcp_ports += _ports(arg.split("=", 1)[1])
        elif arg.startswith("--wf-udp="):
            udp_ports += _ports(arg.split("=", 1)[1])

    # Порт-заглушка upstream означает «секция есть, трафика не ловит».
    tcp_ports = [port for port in tcp_ports if port != disabled]
    udp_ports = [port for port in udp_ports if port != disabled]

    protocols, hostlists, ipsets, excludes, domains = [], [], [], [], []
    for section in _sections(args):
        if not section:
            continue
        for item in _section_protocols(section):
            if item not in protocols:
                protocols.append(item)
        limits = _limits(section)
        for source, target in ((limits["hostlists"], hostlists), (limits["ipsets"], ipsets),
                               (limits["excludes"], excludes), (limits["domains"], domains)):
            for item in source:
                if item not in target:
                    target.append(item)

    ipset_relaxed = settings["ipset"] == "all" and game_filter.enabled(settings)

    covered = []
    if tcp_ports:
        covered.append("TCP " + ", ".join(tcp_ports))
    if udp_ports:
        covered.append("UDP " + ", ".join(udp_ports))

    notes = [game_filter.SCOPE_NOTES[settings["scope"]]]
    if hostlists or domains:
        notes.append(
            "Часть секций ограничена списками сайтов: за их пределами трафик "
            "идёт без обработки."
        )
    if ipsets and not ipset_relaxed:
        notes.append(
            "Игровые секции ограничены списком адресов ipset-all.txt. "
            "Выберите «Все адреса», чтобы снять это ограничение."
        )
    if ipset_relaxed:
        notes.append(
            "Игровые секции обрабатывают любые адреса; исключения для "
            "локальной сети остаются в силе."
        )
    notes.append(
        "Zapret не влияет на трафик внутри VPN-туннеля: он зашифрован и "
        "выглядит как соединение с VPN-сервером."
    )
    if vpn_mode in VPN_NOTES:
        notes.append(VPN_NOTES[vpn_mode])

    return {
        "strategy": profile["name"],
        "scope": settings["scope"],
        "scope_label": game_filter.SCOPE_LABELS[settings["scope"]],
        "protocols": protocols,
        "tcp_ports": tcp_ports,
        "udp_ports": udp_ports,
        "ports_label": " · ".join(covered) if covered else "порты не выбраны",
        "hostlists": hostlists,
        "domains": domains,
        "ipsets": [] if ipset_relaxed else ipsets,
        "excludes": excludes,
        "restart_required": True,
        "vpn_mode": vpn_mode,
        "notes": notes,
    }


def describe_by_id(strategy_id, config, vpn_mode=None):
    from engine.flowseal_profiles import PROFILE_BY_ID
    from engine.zapret import ZapretManager

    profile = PROFILE_BY_ID.get(ZapretManager.canonical_strategy_id(strategy_id))
    if profile is None:
        return None
    return describe(profile, config, vpn_mode)
