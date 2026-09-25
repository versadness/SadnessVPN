"""Состояние Zapret в одном месте.

Раньше это были четыре глобала ui/server.py (_zapret_running, _zapret_strategy,
_zapret_state, _zapret_generation), лок и два хелпера, к которым обращались из
пяти разных мест. Держать их вместе с движком безопаснее: счётчик поколений
существует только чтобы отменять запуск, начатый до stop(), и разъезжаться с
остальным состоянием он не должен.
"""
import threading

from engine import game_filter
from engine.zapret import ZapretManager
from engine.zapret_scope import describe_by_id


class ZapretService:
    def __init__(self, log_callback, broadcast):
        self._lock = threading.RLock()
        self._broadcast = broadcast
        self.running = False
        self.strategy = None
        self.state = "off"
        self._generation = 0
        self.engine = ZapretManager(log_callback=log_callback,
                                    exit_callback=self._handle_exit)

    def _reset(self):
        self._generation += 1
        self.running = False
        self.strategy = None
        self.state = "off"

    def _handle_exit(self, _return_code):
        with self._lock:
            self._reset()
        self._broadcast({"type": "zapret_status", "running": False,
                         "strategy": None, "state": "off"})

    def strategies(self):
        return self.engine.get_strategies()

    def canonical_strategy_id(self, raw):
        return self.engine.canonical_strategy_id(raw)

    def status(self):
        return {"running": self.running, "strategy": self.strategy, "state": self.state}

    def game_filter_summary(self, config, strategy_id=None):
        """Эффективная настройка для интерфейса — без сырой командной строки."""
        names = {item["id"]: item["name"] for item in self.strategies()}
        chosen = self.canonical_strategy_id(strategy_id or self.strategy or "")
        return game_filter.summary(config, names.get(chosen, ""))

    def coverage(self, config, strategy_id=None, vpn_mode=None):
        """Эффективный охват выбранной стратегии простыми словами.

        Считается по фактической команде winws, поэтому «работает для всего
        ПК» не показывается там, где часть трафика в фильтры не попадает.
        """
        chosen = self.canonical_strategy_id(strategy_id or self.strategy or "")
        try:
            return describe_by_id(chosen, config, vpn_mode)
        except game_filter.GameFilterError:
            # Сохранённое значение может быть битым: интерфейс не должен
            # падать из-за описания охвата.
            return None

    def begin_start(self):
        """Занимает движок под запуск и возвращает номер поколения, либо None."""
        with self._lock:
            if self.state != "off":
                return None
            self._generation += 1
            self.state = "starting"
            return self._generation

    def finish_start(self, strategy_id, generation, game_filter_config=None,
                     vpn_servers=None):
        """Запускает движок, если начатую попытку ещё не отменили."""
        with self._lock:
            if generation != self._generation:
                return None
            started = self.engine.start(strategy_id, game_filter_config, vpn_servers)
            if generation != self._generation:
                if started:
                    self.engine.stop()
                return None
            self.running = started
            self.strategy = self.engine._strategy if started else None
            self.state = "on" if started else "off"
            return started

    def begin_stop(self):
        """Немедленно отменяет запуск, не дожидаясь лока движка в HTTP-потоке."""
        if self.state == "stopping":
            return False
        self._generation += 1
        self.state = "stopping"
        return True

    def stop(self):
        with self._lock:
            self.engine.stop()
            self._reset()
