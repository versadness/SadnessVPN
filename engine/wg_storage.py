"""
engine/wg_storage.py — хранение WireGuard/AmneziaWG групп
"""
import json
import os

from engine.paths import data_dir

_DATA_DIR = data_dir()
_WG_PATH  = os.path.join(_DATA_DIR, "wg_servers.json")

# Формат хранения:
# [
#   {
#     "id": "manual-wg",
#     "name": "Вручную",
#     "url": null,
#     "servers": [ {...}, ... ]
#   },
#   ...
# ]


def load_wg_groups() -> list:
    try:
        with open(_WG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_wg_groups(groups: list):
    with open(_WG_PATH, "w", encoding="utf-8") as f:
        json.dump(groups, f, ensure_ascii=False, indent=2)
