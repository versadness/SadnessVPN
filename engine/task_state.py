"""Generation-based cancellation for replaceable background tasks."""

from __future__ import annotations

import threading
from collections.abc import Callable


class BackgroundTaskCoordinator:
    def __init__(self):
        self._lock = threading.RLock()
        self._generation = 0
        self._stop_event = threading.Event()

    def begin(self) -> tuple[int, threading.Event]:
        with self._lock:
            self._stop_event.set()
            self._generation += 1
            self._stop_event = threading.Event()
            return self._generation, self._stop_event

    def run_if_current(
        self,
        generation: int,
        stop_event: threading.Event,
        callback: Callable[[], None],
    ) -> bool:
        with self._lock:
            if (
                generation != self._generation
                or stop_event is not self._stop_event
                or stop_event.is_set()
            ):
                return False
            callback()
            return True

    def cancel(self) -> None:
        with self._lock:
            self._stop_event.set()
            self._generation += 1
