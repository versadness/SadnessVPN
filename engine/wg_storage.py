"""Storage for WireGuard and AmneziaWG server groups."""

import json
import os

from engine.json_store import atomic_write_json
from engine.paths import data_dir


_DATA_DIR = data_dir()
_WG_PATH = os.path.join(_DATA_DIR, "wg_servers.json")


def _load_wg_file(path: str) -> list:
    with open(path, "r", encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, list) or not all(
        isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and isinstance(item.get("name"), str)
        and isinstance(item.get("servers", []), list)
        and all(isinstance(server, dict) for server in item.get("servers", []))
        for item in data
    ):
        raise ValueError("Invalid WireGuard group data")
    return data


def load_wg_groups() -> list:
    # Повреждённый основной файл не должен молча превращаться в пустой список,
    # который следующее сохранение запишет поверх: берём резервную копию.
    for path in (_WG_PATH, _WG_PATH + ".bak"):
        try:
            return _load_wg_file(path)
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            continue
    return []


def save_wg_groups(groups: list):
    atomic_write_json(_WG_PATH, groups, backup_path=_WG_PATH + ".bak")
