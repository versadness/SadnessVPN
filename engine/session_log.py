"""Журнал последней сессии подключения — отдельно от системного журнала.

Пользователь видит и копирует только то, что относится к последней попытке
подключения: подготовку конфигурации, запуск ядра, работу туннеля, ошибки и
отключение. Журнал очищается ровно один раз — в момент старта новой попытки,
до её первой записи, — и остаётся доступным после отключения и перезапуска
приложения, пока не начнётся следующая сессия.

Системный журнал (diagnostics/application.log: запуск, сбои, подписки, Zapret)
этот модуль не трогает.

Каждая сессия получает номер. Источники, которые могут писать с опозданием
(поток вывода ядра, монитор службы AmneziaWG), пишут со своим номером; запись с
номером прошлой сессии отбрасывается и не попадает в новую.

Размер ограничен: начало сессии (подготовка и запуск — самое важное для
разбора ошибок) хранится целиком до HEAD_LIMIT, дальше пишется «хвост» с одной
ротацией. При чтении между ними ставится отметка о пропуске.
"""
from __future__ import annotations

import datetime
import os
import threading

from engine.diagnostics import redact

HEAD_LIMIT = 1024 * 1024
TAIL_LIMIT = 1536 * 1024
_LEVELS = {"err": "ERROR", "warn": "WARNING", "ok": "OK", "info": "INFO", "log": "INFO"}


class SessionLog:
    def __init__(self, directory: str, head_limit: int = HEAD_LIMIT, tail_limit: int = TAIL_LIMIT):
        self.directory = directory
        self.head_path = os.path.join(directory, "connection.log")
        self.tail_path = os.path.join(directory, "connection.tail.log")
        self.old_tail_path = self.tail_path + ".1"
        self.head_limit = head_limit
        self.tail_limit = tail_limit
        self._lock = threading.Lock()
        self.generation = 0
        self.open = False

    # ── жизненный цикл ─────────────────────────────────────────────────────

    def start(self, reason: str) -> int:
        """Новая сессия: стереть прошлую и записать заголовок. Возвращает номер."""
        with self._lock:
            self.generation += 1
            os.makedirs(self.directory, exist_ok=True)
            for path in (self.old_tail_path, self.tail_path):
                try:
                    os.remove(path)
                except FileNotFoundError:
                    pass
            stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # Открытие на запись обрезает файл: старый текст исчезает атомарно
            # с первой строкой новой сессии, без промежутка «пусто».
            with open(self.head_path, "w", encoding="utf-8") as handle:
                handle.write(f"=== Сессия подключения · {stamp} · {reason} ===\n")
            self.open = True
            return self.generation

    def close(self, generation: int | None = None) -> None:
        """Сессия завершена: дальнейшие записи в журнал не попадают."""
        with self._lock:
            if generation is None or generation == self.generation:
                self.open = False

    # ── запись и чтение ────────────────────────────────────────────────────

    def write(self, message, tag: str = "log", generation: int | None = None) -> bool:
        """Дописать строку в текущую сессию. False — запись отброшена."""
        with self._lock:
            if not self.open:
                return False
            if generation is not None and generation != self.generation:
                return False
            stamp = datetime.datetime.now().strftime("%H:%M:%S")
            level = _LEVELS.get(tag, "INFO")
            text = redact(str(message)).replace("\r\n", "\n").replace("\n", "\n    ")
            line = f"{stamp} [{level}] {text}\n"
            try:
                target = self.head_path
                if os.path.getsize(self.head_path) >= self.head_limit:
                    target = self.tail_path
                    if os.path.isfile(self.tail_path) and os.path.getsize(self.tail_path) >= self.tail_limit:
                        os.replace(self.tail_path, self.old_tail_path)
                with open(target, "a", encoding="utf-8") as handle:
                    handle.write(line)
            except OSError:
                return False
            return True

    def read(self) -> str:
        """Текст последней сессии; пустая строка — подключений ещё не было."""
        with self._lock:
            parts = []
            for path in (self.head_path, self.old_tail_path, self.tail_path):
                try:
                    with open(path, encoding="utf-8", errors="replace") as handle:
                        parts.append((path, handle.read()))
                except FileNotFoundError:
                    continue
            if not parts:
                return ""
            text = parts[0][1]
            if len(parts) > 1:
                text += "\n… часть записей из середины длинной сессии опущена …\n\n"
                text += "".join(body for _, body in parts[1:])
            return redact(text)
