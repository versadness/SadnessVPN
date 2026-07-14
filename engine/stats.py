"""
engine/stats.py — постоянная статистика трафика VPN
Хранит: сессии по дням, общее время подключения, суммарный трафик.
Данные читаются/пишутся в data/stats.json.
"""
import json
import os
import time
import threading
from datetime import date, timedelta

from engine.paths import data_dir

_DATA_DIR   = data_dir()
_STATS_PATH = os.path.join(_DATA_DIR, "stats.json")

_lock = threading.Lock()

# Формат stats.json:
# {
#   "total_up":   0,          # байт суммарно
#   "total_down": 0,
#   "total_secs": 0,          # секунд подключения суммарно
#   "total_sessions": 0,      # кол-во подключений суммарно
#   "today": {
#     "date": "2026-04-09",
#     "up": 0, "down": 0, "secs": 0
#   },
#   "weekly": {               # трафик по дням за 7 дней
#     "2026-04-03": {"up": 0, "down": 0},
#     ...
#   }
# }

def _today_str() -> str:
    return date.today().isoformat()


def load_stats() -> dict:
    try:
        with open(_STATS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}

    today = _today_str()
    data.setdefault("total_up",       0)
    data.setdefault("total_down",     0)
    data.setdefault("total_secs",     0)
    data.setdefault("total_sessions", 0)

    # Обнуляем "today" если дата не совпадает
    if data.get("today", {}).get("date") != today:
        data["today"] = {"date": today, "up": 0, "down": 0, "secs": 0}

    data.setdefault("weekly", {})

    # Чистим недельный буфер — оставляем только 7 последних дней
    cutoff = (date.today() - timedelta(days=6)).isoformat()
    data["weekly"] = {
        d: v for d, v in data["weekly"].items() if d >= cutoff
    }

    return data


def _save(data: dict):
    try:
        with open(_STATS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


class StatsTracker:
    """
    Трекер сессии VPN.
    Вызывай start() при подключении, stop() при отключении,
    update(up, down) при обновлении трафика из Clash API.
    """
    def __init__(self):
        self._session_start : float = 0
        self._last_up       : int   = 0
        self._last_down     : int   = 0
        self._running       : bool  = False
        self._timer         : threading.Timer = None
        self._base_data     : dict  = {}  # in-memory cache, avoids disk reads in get_snapshot()

    def start(self):
        with _lock:
            self._session_start = time.time()
            self._last_up       = 0
            self._last_down     = 0
            self._running       = True
            data = load_stats()
            data["total_sessions"] += 1
            _save(data)
            self._base_data = data

    def update(self, up: int, down: int):
        """Вызывать при каждом тике Clash API с cumulative значениями."""
        if not self._running:
            return
        with _lock:
            self._last_up   = up
            self._last_down = down

    def stop(self):
        if not self._running:
            return
        with _lock:
            self._running = False
            elapsed = int(time.time() - self._session_start)
            up      = self._last_up
            down    = self._last_down
            data    = load_stats()
            today   = _today_str()

            # Суммарно
            data["total_up"]   += up
            data["total_down"] += down
            data["total_secs"] += elapsed

            # Сегодня
            if data["today"]["date"] != today:
                data["today"] = {"date": today, "up": 0, "down": 0, "secs": 0}
            data["today"]["up"]   += up
            data["today"]["down"] += down
            data["today"]["secs"] += elapsed

            # Недельный буфер
            data["weekly"].setdefault(today, {"up": 0, "down": 0})
            data["weekly"][today]["up"]   += up
            data["weekly"][today]["down"] += down

            _save(data)
            self._base_data = data

    def reset_today(self):
        with _lock:
            data = load_stats()
            data["today"] = {"date": _today_str(), "up": 0, "down": 0, "secs": 0}
            today = _today_str()
            if today in data["weekly"]:
                data["weekly"][today] = {"up": 0, "down": 0}
            _save(data)
            self._base_data = data

    def reset_all(self):
        with _lock:
            data = {
                "total_up": 0, "total_down": 0,
                "total_secs": 0, "total_sessions": 0,
                "today":  {"date": _today_str(), "up": 0, "down": 0, "secs": 0},
                "weekly": {},
            }
            _save(data)
            self._base_data = data

    def get_snapshot(self) -> dict:
        """Возвращает текущую статистику включая незавершённую сессию."""
        with _lock:
            today = _today_str()
            # Use cached data; reload only if cache is empty or the date rolled over
            if not self._base_data or self._base_data.get("today", {}).get("date") != today:
                self._base_data = load_stats()
            data    = self._base_data
            elapsed = int(time.time() - self._session_start) if self._running else 0
            up      = self._last_up
            down    = self._last_down

            # Временно добавляем текущую сессию
            snap_today_secs = data["today"]["secs"] + elapsed
            snap_today_up   = data["today"]["up"]   + up
            snap_today_down = data["today"]["down"]  + down
            snap_total_secs = data["total_secs"] + elapsed
            snap_total_up   = data["total_up"]   + up
            snap_total_down = data["total_down"] + down

            # Недельный буфер с текущей сессией
            weekly = {}
            for d, v in data["weekly"].items():
                weekly[d] = dict(v)
            today = _today_str()
            weekly.setdefault(today, {"up": 0, "down": 0})
            weekly[today]["up"]   += up
            weekly[today]["down"] += down

            # Строим массив за 7 дней (Mon → Sun)
            week_list = []
            for i in range(6, -1, -1):
                d = (date.today() - timedelta(days=i)).isoformat()
                v = weekly.get(d, {"up": 0, "down": 0})
                week_list.append({
                    "date":  d,
                    "up":    v["up"],
                    "down":  v["down"],
                    "total": v["up"] + v["down"],
                    "label": (date.today() - timedelta(days=i)).strftime("%a").upper(),
                })

            return {
                "today": {
                    "up":   snap_today_up,
                    "down": snap_today_down,
                    "secs": snap_today_secs,
                },
                "total": {
                    "up":       snap_total_up,
                    "down":     snap_total_down,
                    "secs":     snap_total_secs,
                    "sessions": data["total_sessions"],
                },
                "weekly":   week_list,
                "connected": self._running,
            }


# Глобальный трекер
tracker = StatsTracker()
