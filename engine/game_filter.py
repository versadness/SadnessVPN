"""Игровой фильтр Zapret: режим, диапазоны портов и режим IPSet.

Профили Flowseal держат игровые секции за плейсхолдерами ``%GameFilterTCP%``
и ``%GameFilterUDP%``. В upstream их подставляет service.bat: ``12`` — это
служебный «выключено» (порт, на котором игр не бывает), ``1024-65535`` —
включённый фильтр. Раньше tools/sync_flowseal_profiles.py зашивал ``12`` прямо
в сгенерированные профили, поэтому игровой фильтр не работал никогда.

Здесь живёт нормализация пользовательской настройки и рендер диапазонов.
Наружу уходят только проверенные числа: команда winws собирается списком
аргументов, никакой конкатенации пользовательского ввода в shell.
"""
from __future__ import annotations

# Порт-заглушка upstream: секция остаётся в команде, но трафика не ловит.
DISABLED_PORTS = "12"
DEFAULT_TCP_RANGE = (1024, 65535)
DEFAULT_UDP_RANGE = (1024, 65535)

MODES = ("off", "udp", "tcp", "both")
IPSET_MODES = ("list", "all")

# Охват обхода. Это не то же самое, что режим протокола: охват отвечает на
# вопрос «какой трафик вообще попадает в winws», а режим — «какой протокол
# внутри этого охвата».
#
#   standard — ровно то, что описывает сама стратегия Flowseal;
#   extended — системный охват: игровые диапазоны портов целиком;
#   custom   — пользовательские диапазоны.
SCOPES = ("standard", "extended", "custom")

SCOPE_LABELS = {
    "standard": "Стандартный охват стратегии",
    "extended": "Расширенный системный охват",
    "custom": "Пользовательские фильтры",
}
SCOPE_NOTES = {
    "standard": (
        "Обрабатывается только тот трафик, который описывает сама стратегия: "
        "браузерные порты и служебные диапазоны Discord."
    ),
    "extended": (
        "Дополнительно обрабатываются игровые диапазоны портов, поэтому под "
        "обход попадают игры и другие приложения, а не только браузеры."
    ),
    "custom": (
        "Диапазоны портов заданы вручную. Обход применяется ровно к ним — "
        "проверьте, что игра действительно использует эти порты."
    ),
}

MODE_LABELS = {
    "off": "Выключен",
    "udp": "Только UDP",
    "tcp": "Только TCP",
    "both": "TCP + UDP",
}
IPSET_LABELS = {
    "list": "Только адреса из списка",
    "all": "Все адреса",
}

# Миграция старых конфигураций: поля просто отсутствуют, и молча включать
# перехват всего игрового трафика у существующего пользователя нельзя.
DEFAULTS = {
    "scope": "standard",
    "mode": "off",
    "tcp_start": DEFAULT_TCP_RANGE[0],
    "tcp_end": DEFAULT_TCP_RANGE[1],
    "udp_start": DEFAULT_UDP_RANGE[0],
    "udp_end": DEFAULT_UDP_RANGE[1],
    "ipset": "list",
}


class GameFilterError(ValueError):
    """Некорректная пользовательская настройка игрового фильтра."""


def _port(value, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise GameFilterError(f"{field}: порт должен быть числом")
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError):
        raise GameFilterError(f"{field}: порт должен быть числом") from None
    if not 1 <= port <= 65535:
        raise GameFilterError(f"{field}: порт должен быть в диапазоне 1–65535")
    return port


def normalize(raw) -> dict:
    """Привести настройку к проверенному виду. Бросает GameFilterError."""
    if raw is None:
        return dict(DEFAULTS)
    if not isinstance(raw, dict):
        raise GameFilterError("Некорректная настройка игрового фильтра")

    mode = raw.get("mode", DEFAULTS["mode"])
    if mode is True:
        mode = "both"
    elif mode is False:
        mode = "off"
    if mode not in MODES:
        raise GameFilterError("Неизвестный режим игрового фильтра")

    ipset = raw.get("ipset", DEFAULTS["ipset"])
    if ipset not in IPSET_MODES:
        raise GameFilterError("Неизвестный режим IPSet")

    ports = {}
    for proto in ("tcp", "udp"):
        start = _port(raw.get(f"{proto}_start", DEFAULTS[f"{proto}_start"]), f"{proto.upper()}: начало")
        end = _port(raw.get(f"{proto}_end", DEFAULTS[f"{proto}_end"]), f"{proto.upper()}: конец")
        if start > end:
            raise GameFilterError(
                f"{proto.upper()}: начало диапазона не может быть больше конца"
            )
        ports[f"{proto}_start"] = start
        ports[f"{proto}_end"] = end

    scope = raw.get("scope")
    if scope is None:
        # Конфигурация прежних версий: охват выводится из того, что уже есть,
        # и ничего у пользователя не включается молча.
        default_ranges = all(ports[key] == DEFAULTS[key] for key in ports)
        scope = "standard" if mode == "off" else "extended" if default_ranges else "custom"
    if scope not in SCOPES:
        raise GameFilterError("Неизвестный охват обхода")

    if scope == "standard":
        # Стандартный охват — это ровно стратегия: никаких добавочных портов.
        mode, ipset = "off", "list"
        ports = {key: DEFAULTS[key] for key in ports}
    elif scope == "extended":
        if mode == "off":
            mode = "both"
        # Системный охват использует проверенные игровые диапазоны целиком;
        # произвольные границы — это уже пользовательские фильтры.
        ports = {key: DEFAULTS[key] for key in ports}

    return {"scope": scope, "mode": mode, "ipset": ipset, **ports}


def normalize_stored(raw) -> dict:
    """То же, но для чтения с диска: битое значение откатывается к умолчанию."""
    try:
        return normalize(raw)
    except GameFilterError:
        return dict(DEFAULTS)


def _range(start: int, end: int) -> str:
    return str(start) if start == end else f"{start}-{end}"


def tcp_ports(config: dict) -> str:
    config = normalize(config)
    if config["mode"] in ("tcp", "both"):
        return _range(config["tcp_start"], config["tcp_end"])
    return DISABLED_PORTS


def udp_ports(config: dict) -> str:
    config = normalize(config)
    if config["mode"] in ("udp", "both"):
        return _range(config["udp_start"], config["udp_end"])
    return DISABLED_PORTS


def substitutions(config: dict) -> dict:
    """Плейсхолдер → проверенная строка диапазона. Только цифры и дефис."""
    config = normalize(config)
    tcp, udp = tcp_ports(config), udp_ports(config)
    return {
        "%GameFilterTCP%": tcp,
        "%GameFilterUDP%": udp,
        # Upstream использует общий %GameFilter% в части стратегий.
        "%GameFilter%": DISABLED_PORTS if config["mode"] == "off" else _range(
            min(config["tcp_start"], config["udp_start"]),
            max(config["tcp_end"], config["udp_end"]),
        ),
    }


def enabled(config: dict) -> bool:
    return normalize(config)["mode"] != "off"


def summary(config: dict, strategy_name: str = "") -> dict:
    """Итоговая эффективная настройка для интерфейса. Без командной строки."""
    config = normalize(config)
    on = config["mode"] != "off"
    return {
        **config,
        "enabled": on,
        "scope_label": SCOPE_LABELS[config["scope"]],
        "scope_note": SCOPE_NOTES[config["scope"]],
        "mode_label": MODE_LABELS[config["mode"]],
        "ipset_label": IPSET_LABELS[config["ipset"]],
        "tcp_label": _range(config["tcp_start"], config["tcp_end"])
        if config["mode"] in ("tcp", "both") else "не перехватывается",
        "udp_label": _range(config["udp_start"], config["udp_end"])
        if config["mode"] in ("udp", "both") else "не перехватывается",
        "strategy": strategy_name,
        "note": (
            "Игровой фильтр Zapret работает системно по портам и IP. "
            "Это не то же самое, что правило VPN для отдельного приложения."
        ),
    }
