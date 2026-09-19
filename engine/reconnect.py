"""Bounded, cancellable recovery of an unexpectedly exited VPN engine."""
import threading
import time


class Reconnector:
    def __init__(self, connect, state, enabled, notify, delays=(2, 5, 10)):
        self.connect, self.state, self.enabled, self.notify = connect, state, enabled, notify
        self.delays = delays
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.worker = None

    def cancel(self):
        with self.lock:
            self.stop.set()

    def start(self):
        with self.lock:
            if not self.enabled() or (self.worker and self.worker.is_alive() and not self.stop.is_set()):
                return
            stop = self.stop = threading.Event()
            self.worker = threading.Thread(target=self._run, args=(stop,), daemon=True)
            self.worker.start()

    def _run(self, stop):
        for delay in self.delays:
            if stop.wait(delay): return
            with self.lock:
                if stop.is_set() or not self.enabled() or self.state() != 'off': return
                self.notify('Восстановление VPN после остановки ядра…')
                try: started = self.connect()
                except Exception: started = False
            if started:
                deadline = time.monotonic() + 45
                while not stop.wait(.2):
                    state = self.state()
                    if state == 'on': return
                    if state != 'connecting': break
                    if time.monotonic() >= deadline: return
        if not stop.is_set():
            self.notify('Автовосстановление остановлено после трёх попыток. Проверьте сервер и подключитесь вручную.')
