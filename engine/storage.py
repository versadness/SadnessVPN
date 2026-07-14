"""
engine/storage.py — хранение серверов с группировкой по подпискам
"""
import json
import os

from engine.paths import data_dir

_DATA_DIR     = data_dir()
_SERVERS_PATH = os.path.join(_DATA_DIR, "servers.json")

# Формат хранения:
# [
#   {
#     "id": "manual",          # или uuid подписки
#     "name": "Вручную",       # название группы
#     "url": null,             # URL подписки или null
#     "servers": [ {...}, ... ]
#   },
#   ...
# ]

def load_groups() -> list:
    try:
        with open(_SERVERS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Старый формат (плоский список) — мигрируем
            if isinstance(data, list) and data and isinstance(data[0], dict) and "uuid" in data[0]:
                return [{
                    "id": "manual",
                    "name": "Вручную",
                    "url": None,
                    "servers": data
                }]
            return data
    except Exception:
        return []

def save_groups(groups: list):
    with open(_SERVERS_PATH, "w", encoding="utf-8") as f:
        json.dump(groups, f, ensure_ascii=False, indent=2)

