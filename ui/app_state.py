"""Настройки приложения: путь, значения по умолчанию, загрузка и сохранение.

Словарь app_settings создаётся один раз и никогда не перепривязывается —
все, кто с ним работает, держат ссылку на один и тот же объект. Если его
заменить целиком, блюпринты и ui/server.py разъедутся молча, поэтому
сбрасывать его нужно через reset_for_tests(), а не присваиванием.
"""
import json
import os

from engine import game_filter, tg_proxy
from engine.diagnostics import journal
from engine.json_store import atomic_write_json
from engine.paths import data_dir

DATA_DIR = data_dir()
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")
# Предыдущая валидная версия settings.json — на случай повреждения основного.
SETTINGS_BAK_PATH = SETTINGS_PATH + ".bak"
# Резервная копия делается один раз, перед первой миграцией на новое ядро.
# Имя фиксировано: цель — вернуть прежний профиль вручную, а не вести архив.
SETTINGS_BACKUP_PATH = os.path.join(DATA_DIR, "settings.before-mihomo-migration.json")
PROFILE_DIR = os.path.join(DATA_DIR, "profile")

# Порты, которые приложение занимает само: 45678 — локальный HTTP-бэкенд,
# 9090 — Clash API ядра. Пользователь не может назначить их прокси.
CLASH_PORT_DEFAULT = 9090
RESERVED_LOCAL_PORTS = {45678, CLASH_PORT_DEFAULT}

TUNNEL_KEYS = (
    "kill_switch", "block_udp", "socks5_auth", "socks5_user", "socks5_pass",
    "mux", "fakedns", "preferred_ip", "dns_preset", "custom_dns",
    "ping_type", "ping_url", "ping_timeout", "server_sort", "tls_fingerprint",
)

# Настройки, удалённые вместе с sing-box. Значение выбрасывается при загрузке:
# хранить выбор несуществующего ядра нельзя, а сбрасывать остальной профиль
# из-за него — тем более.
REMOVED_SETTING_KEYS = ("core",)

USER_APP_SETTING_KEYS = {
    "startup", "autoconn", "silent", "lan", "mintray", "reconnect",
    "animations", "favorite_servers", "onboarding_complete", "sub_autoupdate",
    "auto_failover",
    "avatar_file", "wallpaper_file",
}

DEFAULT_SETTINGS = {
    "startup":          False,
    "autoconn":         False,
    # Обновлять подписки при каждом запуске приложения.
    "sub_autoupdate":   True,
    # Автоматическая замена сервера при отказе (резерв в Mihomo).
    "auto_failover":    True,
    "reconnect":        False,
    "silent":           False,
    "lan":              False,
    "mintray":          False,
    "animations":       True,
    "onboarding_complete": False,
    "avatar_file":      "",
    "wallpaper_file":   "",
    "favorite_servers": [],
    "socks":            1080,
    "http":             8080,
    "selected_group":   None,
    "selected_index":   None,
    "selected_wg_group": None,
    "selected_wg_index": None,
    "active_protocol":  "vless",
    "hwid":             "",
    "ping_type":        "tcp",
    "ping_url":         "https://www.gstatic.com/generate_204",
    "ping_timeout":     3000,
    "kill_switch":      False,
    "block_udp":        False,
    "socks5_auth":      False,
    "socks5_user":      "",
    "socks5_pass":      "",
    "mux":              False,
    "fakedns":          False,
    "preferred_ip":     "ipv4",
    "dns_preset":       "cf_google",
    "custom_dns":       "",
    "tls_fingerprint":  "firefox",
    "server_sort":      "default",
    "zapret_strategy":  "flowseal_general",
    # Игровой фильтр Zapret. По умолчанию выключен: включать перехват всего
    # игрового трафика у существующего пользователя без его согласия нельзя.
    "zapret_game_filter": dict(game_filter.DEFAULTS),
    # Telegram WS Proxy: порт и секрет пользователя; секрет создаётся при
    # первой загрузке настроек.
    "tg_proxy": {"enabled": False, "port": tg_proxy.DEFAULT_PORT, "secret": ""},
}


def _read_settings_file(path):
    """Словарь настроек из файла; None — файла нет; ValueError — файл повреждён."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(str(exc)) from None
    if not isinstance(loaded, dict):
        raise ValueError("settings.json не содержит объект настроек")
    return loaded


def _read_stored_settings():
    """Основной файл, а при его повреждении — резервная копия.

    Повреждённый файл откладывается рядом, а не перезаписывается: иначе при
    следующем сохранении пропал бы и HWID, и провайдер подписки увидел бы
    новое устройство.
    """
    try:
        return _read_settings_file(SETTINGS_PATH)
    except ValueError as exc:
        journal.warning("settings.json повреждён (%s); используется резервная копия", exc)
        try:
            os.replace(SETTINGS_PATH, SETTINGS_PATH + ".corrupt")
        except OSError:
            pass
    try:
        return _read_settings_file(SETTINGS_BAK_PATH)
    except ValueError:
        journal.warning("Резервная копия настроек тоже повреждена; загружены значения по умолчанию")
        return None


def load_settings() -> dict:
    loaded = _read_stored_settings()
    if loaded is None:
        return dict(DEFAULT_SETTINGS)
    try:
        settings = {**DEFAULT_SETTINGS, **loaded}
        for key in (
            "startup", "autoconn", "silent", "lan", "mintray", "animations", "reconnect",
            "onboarding_complete", "kill_switch", "sub_autoupdate", "auto_failover",
            "block_udp", "socks5_auth", "mux", "fakedns",
        ):
            if not isinstance(settings.get(key), bool):
                settings[key] = DEFAULT_SETTINGS[key]
        for key in (
            "socks5_user", "socks5_pass", "custom_dns", "ping_url",
            "avatar_file", "wallpaper_file",
        ):
            if not isinstance(settings.get(key), str):
                settings[key] = DEFAULT_SETTINGS[key]
        if settings.get("lan") and not (
            settings.get("socks5_auth")
            and settings.get("socks5_user")
            and settings.get("socks5_pass")
        ):
            settings["lan"] = False
        if settings.get("preferred_ip") not in ("ipv4", "ipv6", "auto"):
            settings["preferred_ip"] = "ipv4"
        if settings.get("dns_preset") not in (
            "cf_google", "google", "cloudflare", "adguard", "quad9",
            "xbox", "xbox_dot", "comss", "comss_dot", "custom",
        ):
            settings["dns_preset"] = "cf_google"
        if settings.get("ping_type") not in ("tcp", "icmp", "http_get", "http_head"):
            settings["ping_type"] = "tcp"
        if settings.get("tls_fingerprint") not in ("firefox", "edge", "chrome", "provider"):
            settings["tls_fingerprint"] = "firefox"
        favorites = settings.get("favorite_servers")
        if not isinstance(favorites, list):
            settings["favorite_servers"] = []
        else:
            settings["favorite_servers"] = [
                item for item in favorites
                if isinstance(item, str) and 0 < len(item) <= 128
            ][:10000]
        if settings.get("server_sort") not in ("default", "ping", "name"):
            settings["server_sort"] = "default"
        for key in ("selected_index", "selected_wg_index"):
            if settings.get(key) is not None and not isinstance(settings.get(key), int):
                settings[key] = None
        for key in ("selected_group", "selected_wg_group"):
            if settings.get(key) is not None and not isinstance(settings.get(key), str):
                settings[key] = None
        if settings.get("active_protocol") not in ("vless", "wg"):
            settings["active_protocol"] = "vless"
        # Миграция на единственное ядро: сохранённый выбор sing-box/auto
        # просто исчезает, всё остальное в профиле остаётся как было.
        # Перед первым изменением делается локальная копия — повторный запуск
        # миграции безопасен и копию не перезаписывает.
        migrated = any(key in loaded for key in REMOVED_SETTING_KEYS)
        if migrated:
            backup_settings(loaded)
        for key in REMOVED_SETTING_KEYS:
            settings.pop(key, None)
        # Миграция старых настроек: поля игрового фильтра могли не сохраняться
        # вовсе, а битое значение не должно мешать приложению запуститься.
        settings["zapret_game_filter"] = game_filter.normalize_stored(
            settings.get("zapret_game_filter")
        )
        settings["tg_proxy"] = tg_proxy.normalize_stored(settings.get("tg_proxy"))
        if not isinstance(settings.get("zapret_strategy"), str) or not settings["zapret_strategy"]:
            settings["zapret_strategy"] = DEFAULT_SETTINGS["zapret_strategy"]
        if migrated:
            # Миграция доводится до диска целиком и после всех нормализаций:
            # иначе резервная копия ссылалась бы на состояние, которое так и
            # не изменилось. Отказ записи запуску не мешает.
            save_settings(settings)
        return settings
    except Exception:
        # Сбой нормализации не должен стоить пользователю идентификатора
        # устройства: без него провайдер регистрирует новое устройство.
        journal.exception("Не удалось разобрать настройки; загружены значения по умолчанию")
        settings = dict(DEFAULT_SETTINGS)
        if isinstance(loaded.get("hwid"), str):
            settings["hwid"] = loaded["hwid"]
        return settings


def backup_settings(raw: dict) -> bool:
    """Один раз сохранить прежние настройки рядом с профилем.

    Существующая копия не перезаписывается: повторный запуск миграции не
    должен затереть исходное состояние уже мигрированным.
    """
    if os.path.exists(SETTINGS_BACKUP_PATH):
        return False
    try:
        atomic_write_json(SETTINGS_BACKUP_PATH, raw)
        journal.info("Создана резервная копия настроек перед миграцией: %s",
                     os.path.basename(SETTINGS_BACKUP_PATH))
        return True
    except Exception as exc:
        # Отказ записи не должен мешать приложению запуститься.
        journal.warning("Не удалось создать резервную копию настроек: %s", exc)
        return False


def normalize_zapret_game_filter(value):
    """Пользовательский ввод: GameFilterError поднимается наружу как 400."""
    return game_filter.normalize(value)


def save_settings(cfg: dict) -> bool:
    try:
        atomic_write_json(SETTINGS_PATH, cfg, backup_path=SETTINGS_BAK_PATH)
        return True
    except Exception as exc:
        # В собранном приложении stdout никуда не ведёт: пишем в журнал,
        # иначе отказ записи настроек остаётся невидимым.
        journal.warning("Не удалось сохранить настройки: %s", exc)
        return False


def port_number(value, default=None) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        if default is not None:
            return default
        raise ValueError("Порт должен быть числом")
    if not 1 <= port <= 65535:
        if default is not None:
            return default
        raise ValueError("Порт должен быть в диапазоне от 1 до 65535")
    return port


_DNS_SCHEMES = ("udp://", "tcp://", "tls://", "https://", "quic://")


def normalize_custom_dns(value: str) -> str:
    """Список адресов DNS через запятую: IP или scheme://хост[:порт][/путь]."""
    import ipaddress
    import re
    items = [item.strip() for item in value.split(",") if item.strip()]
    for item in items:
        scheme = next((prefix for prefix in _DNS_SCHEMES if item.lower().startswith(prefix)), "")
        rest = item[len(scheme):]
        if not scheme:
            try:
                ipaddress.ip_address(rest)
                continue
            except ValueError:
                raise ValueError(f"DNS «{item}»: без схемы нужен IP-адрес; для имени "
                                 "укажите tls://, https:// или quic://") from None
        if not re.fullmatch(r"[A-Za-z0-9.\-]+(?::\d{1,5})?(?:/[^\s,]*)?|\[[0-9A-Fa-f:.]+\](?::\d{1,5})?", rest):
            raise ValueError(f"Некорректный адрес DNS: {item}")
    return ", ".join(items)


def normalize_tunnel_setting(key, value):
    if key in REMOVED_SETTING_KEYS:
        raise ValueError("Выбора ядра больше нет: VPN работает на Mihomo")
    if key in ("kill_switch", "block_udp", "socks5_auth", "mux", "fakedns"):
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be true or false")
        return value
    if key in ("socks5_user", "socks5_pass", "custom_dns"):
        if not isinstance(value, str) or len(value) > 2048:
            raise ValueError(f"Invalid {key}")
        if key == "custom_dns":
            return normalize_custom_dns(value)
        return value
    if key == "preferred_ip":
        if value not in ("ipv4", "ipv6", "auto"):
            raise ValueError("Invalid IP preference")
        return value
    if key == "dns_preset":
        if value not in (
            "cf_google", "google", "cloudflare", "adguard", "quad9",
            "xbox", "xbox_dot", "comss", "comss_dot", "custom",
        ):
            raise ValueError("Invalid DNS preset")
        return value
    if key == "tls_fingerprint":
        if value not in ("firefox", "edge", "chrome", "provider"):
            raise ValueError("Invalid TLS fingerprint")
        return value
    if key == "ping_type":
        if value not in ("tcp", "icmp", "http_get", "http_head"):
            raise ValueError("Invalid ping type")
        return value
    if key == "ping_url":
        if not isinstance(value, str) or len(value) > 2048 or not value.startswith(("http://", "https://")):
            raise ValueError("Invalid ping URL")
        return value
    if key == "ping_timeout":
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            raise ValueError("Invalid ping timeout") from None
        if not 200 <= numeric <= 30000:
            raise ValueError("Invalid ping timeout")
        return value
    if key == "server_sort":
        if value not in ("default", "ping", "name"):
            raise ValueError("Invalid server sorting mode")
        return value
    raise ValueError("Unknown tunnel setting")


def normalize_app_setting(key, value):
    if key in {
        "startup", "autoconn", "silent", "lan", "mintray", "animations", "reconnect",
        "onboarding_complete", "sub_autoupdate", "auto_failover",
    }:
        if not isinstance(value, bool):
            raise ValueError("Значение настройки должно быть true или false")
        return value
    if key in {"avatar_file", "wallpaper_file"}:
        if not isinstance(value, str) or len(value) > 128:
            raise ValueError("Некорректное имя файла оформления")
        return value
    if key == "favorite_servers":
        if not isinstance(value, list):
            raise ValueError("Некорректный список избранных серверов")
        cleaned = []
        for item in value:
            if not isinstance(item, str) or not 0 < len(item) <= 128:
                raise ValueError("Некорректный идентификатор сервера")
            if item not in cleaned:
                cleaned.append(item)
        if len(cleaned) > 10000:
            raise ValueError("Слишком много избранных серверов")
        return cleaned
    raise ValueError("Неизвестная настройка")



app_settings = load_settings()


def reset_for_tests(values=None):
    """Заменить содержимое, сохранив тот же объект (см. примечание выше)."""
    app_settings.clear()
    app_settings.update(DEFAULT_SETTINGS if values is None else values)
    return app_settings
