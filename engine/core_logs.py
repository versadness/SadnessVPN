"""Respect the severity emitted by a core, not words in its message body."""
import re
import threading
import time

_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_LEVEL = re.compile(
    r"^(?:(?:[+-]\d{4}\s+)?\d{4}[-/]\d{2}[-/]\d{2}\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?\s+)?"
    r"(?:\[(TRACE|DEBUG|INFO|WARN(?:ING)?|ERROR|FATAL|PANIC)\]|"
    r"(TRACE|DEBUG|INFO|WARN(?:ING)?|ERROR|FATAL|PANIC)\b)", re.I)
_STRUCTURED = re.compile(r'\blevel=(?:"|\x27)?(trace|debug|info|warn(?:ing)?|error|fatal|panic)\b', re.I)


def core_log_tag(line):
    text = _ANSI.sub("", line).strip()
    match = _LEVEL.match(text) or _STRUCTURED.search(text)
    if match:
        level = next(group for group in match.groups() if group).lower()
        if level in {"error", "fatal", "panic"}:
            return "err"
        if level in {"warn", "warning"}:
            return "warn"
        return "log"
    # Unstructured crash output must remain visible; ordinary words or domain
    # names containing 'failed'/'error' are not a severity indicator.
    if re.match(r"^(?:fatal(?: error)?|panic|error|failed)\s*[: ]", text, re.I):
        return "err"
    return "log"


class ErrorNotifications:
    """Bound transient network popups without dropping or reclassifying logs."""

    def __init__(self, clock=time.monotonic, interval=30):
        self._clock = clock
        self._interval = interval
        self._last_network = None
        self._lock = threading.Lock()

    def should_notify(self, message):
        text = _ANSI.sub("", str(message)).lower()
        # A peer closing one established upload is not a whole-VPN failure.
        if "upload: raw-read" in text and (
            "forcibly closed by the remote host" in text or
            "connection reset by peer" in text
        ):
            return False
        if any(marker in text for marker in (
            "no route to internet", "router: missing default interface",
            "while device paused",
        )):
            with self._lock:
                now = self._clock()
                if self._last_network is not None and now - self._last_network < self._interval:
                    return False
                self._last_network = now
        return True
