"""Storage for WireGuard and AmneziaWG server groups."""

import json
import os

from engine.json_store import atomic_write_json
from engine.paths import data_dir


_DATA_DIR = data_dir()
_WG_PATH = os.path.join(_DATA_DIR, "wg_servers.json")


def load_wg_groups() -> list:
    try:
        with open(_WG_PATH, "r", encoding="utf-8") as stream:
            data = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    if not isinstance(data, list) or not all(
        isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and isinstance(item.get("name"), str)
        and isinstance(item.get("servers", []), list)
        and all(isinstance(server, dict) for server in item.get("servers", []))
        for item in data
    ):
        return []
    return data


def save_wg_groups(groups: list):
    atomic_write_json(_WG_PATH, groups)
