"""Storage for proxy server groups and subscriptions."""

import json
import os

from engine.json_store import atomic_write_json
from engine.paths import data_dir


_DATA_DIR = data_dir()
_SERVERS_PATH = os.path.join(_DATA_DIR, "servers.json")


def _load_groups_file(path: str) -> list:
    with open(path, "r", encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise ValueError("Invalid server group data")

    # Migrate the old flat list of servers into the grouped format in memory.
    if data and "uuid" in data[0]:
        return [{
            "id": "manual",
            "name": "Вручную",
            "url": None,
            "servers": data,
        }]
    for group in data:
        if (
            not isinstance(group.get("id"), str)
            or not isinstance(group.get("name"), str)
            or not isinstance(group.get("servers", []), list)
            or not all(isinstance(server, dict) for server in group.get("servers", []))
        ):
            raise ValueError("Invalid server group structure")
    return data


def load_groups() -> list:
    for path in (_SERVERS_PATH, _SERVERS_PATH + ".bak"):
        try:
            return _load_groups_file(path)
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            continue
    return []


def save_groups(groups: list):
    atomic_write_json(_SERVERS_PATH, groups, backup_path=_SERVERS_PATH + ".bak")
