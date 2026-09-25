"""Состояние «ядро работает, а сервер соединений не принимает».

Так выглядел «разрыв через 30–50 секунд»: Mihomo жив, TUN поднят, но новые
TCP-соединения к IP:порту VPN-сервера перестают устанавливаться — провайдер
начинает отбрасывать их после первых десятков секунд работы. Журнал сервера в
это время пуст: пакеты до него не доходят. Приложение продолжало показывать
«подключено», а детектор тишины в _traffic_loop этого не видел: неудачные
соединения не попадают в /connections, поэтому «активных соединений без
трафика» не было.

Источник истины — строки ядра: «… using proxy» пишется только после успешного
соединения с сервером, «dial proxy … error» — при неудаче.
"""
import re
import threading
import time
from collections import deque

WINDOW_SECONDS = 20.0
MIN_FAILURES = 6

_SUCCESS = re.compile(r"\] .* match .* using (?!DIRECT)")
_FAILURE = re.compile(r"dial (?!DIRECT)\S+ .*error: (?P<endpoint>\S+?:\d+) (?P<reason>.*?)\"?$")


class DialHealth:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self.reset()

    def reset(self):
        with self._lock:
            self._ok = deque()
            self._fail = deque()
            self._endpoint = ""
            self._reason = ""
            self._reported = False

    def feed(self, line: str):
        """Учесть строку журнала ядра. Строки DIRECT не влияют на здоровье туннеля."""
        if "using" in line and _SUCCESS.search(line):
            with self._lock:
                self._ok.append(self._clock())
            return
        if "dial" in line and "error" in line:
            match = _FAILURE.search(line)
            if match:
                with self._lock:
                    self._fail.append(self._clock())
                    self._endpoint = match.group("endpoint")
                    self._reason = match.group("reason").replace("connect error: ", "").strip()[:120]

    def _trim(self, now):
        for queue in (self._ok, self._fail):
            while queue and now - queue[0] > WINDOW_SECONDS:
                queue.popleft()

    def check(self):
        """None — всё в порядке; dict — сервер перестал принимать соединения.

        Сообщается один раз на эпизод; после первого успешного соединения
        возвращается {"recovered": True}, тоже один раз.
        """
        with self._lock:
            now = self._clock()
            self._trim(now)
            blocked = len(self._fail) >= MIN_FAILURES and not self._ok
            if blocked and not self._reported:
                self._reported = True
                return {"blocked": True, "failures": len(self._fail),
                        "endpoint": self._endpoint, "reason": self._reason}
            if self._reported and self._ok:
                self._reported = False
                return {"recovered": True}
        return None


def blocked_message(server_name: str, info: dict, alternatives: str = "") -> str:
    reason = info.get("reason") or "нет ответа"
    text = (f"Сервер «{server_name}» перестал принимать соединения: за {int(WINDOW_SECONDS)} с "
            f"{info.get('failures')} неудачных попыток к {info.get('endpoint')} ({reason}) и ни одной успешной. "
            "Ядро работает, туннель поднят — соединения не доходят до сервера. Так проявляется "
            "блокировка адреса или протокола на стороне провайдера; переподключение к тому же "
            "серверу обычно не помогает несколько минут.")
    if alternatives:
        text += " Попробуйте другой протокол или сервер: " + alternatives + "."
    return text
