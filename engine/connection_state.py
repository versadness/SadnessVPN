"""Thread-safe coordination for asynchronous VPN connection attempts."""

from __future__ import annotations

import threading
from collections.abc import Callable


StateCallback = Callable[[], None]


class ConnectionCoordinator:
    def __init__(self):
        self._lock = threading.RLock()
        self._generation = 0
        self._state = "off"

    def begin(self) -> int | None:
        """Start one connection attempt, rejecting overlapping attempts."""
        with self._lock:
            if self._state != "off":
                return None
            self._generation += 1
            self._state = "connecting"
            return self._generation

    def is_current(self, attempt: int) -> bool:
        with self._lock:
            return self._state == "connecting" and attempt == self._generation

    def run_if_current(
        self,
        attempt: int,
        callback: StateCallback,
    ) -> bool:
        """Run a transition step only for the active connection attempt."""
        with self._lock:
            if self._state != "connecting" or attempt != self._generation:
                return False
            callback()
            return True

    def run_if_connected(
        self,
        attempt: int,
        callback: StateCallback,
    ) -> bool:
        """Publish background results only for the active VPN session."""
        with self._lock:
            if self._state != "on" or attempt != self._generation:
                return False
            callback()
            return True

    def complete(self, attempt: int, callback: StateCallback | None = None) -> bool:
        """Activate an attempt only if it has not been cancelled or replaced."""
        with self._lock:
            if self._state != "connecting" or attempt != self._generation:
                return False
            self._state = "on"
            if callback:
                callback()
            return True

    def fail(self, attempt: int, callback: StateCallback | None = None) -> bool:
        """Return the current failed attempt to the off state."""
        with self._lock:
            if self._state != "connecting" or attempt != self._generation:
                return False
            self._state = "off"
            if callback:
                callback()
            return True

    def cancel(self, callback: StateCallback | None = None) -> str:
        """Invalidate all outstanding work and return the previous state."""
        with self._lock:
            previous = self._state
            self._generation += 1
            self._state = "off"
            if callback:
                callback()
            return previous

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def connected(self) -> bool:
        return self.state == "on"
