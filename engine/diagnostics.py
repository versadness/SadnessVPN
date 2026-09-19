"""Bounded persistent diagnostics, including failures before the UI exists."""
import logging
import logging.handlers
import os
import re
from engine.paths import data_dir


def redact(text):
    names = r"(?:private[_-]?key|pre[_-]?shared[_-]?key|password|socks5_pass|token|authorization|secret)"
    text = re.sub(r'(?i)([\"\x27]?' + names + r'[\"\x27]?\s*[:=]\s*)(?:\"[^\"]*\"|\x27[^\x27]*\x27|(?:Bearer|Basic)\s+[^\s,;]+|[^\s,;]+)', r'\1[скрыто]', str(text))
    return re.sub(r"(?i)(?:https?|vless|vmess|trojan|ss|hysteria2|hy2)://[^\s<>]+", "[URL скрыт]", text)


class SafeFormatter(logging.Formatter):
    def format(self, record):
        return redact(super().format(record))


journal = logging.getLogger("sadness")
journal.setLevel(logging.INFO)
journal.propagate = False
directory = os.path.join(data_dir(), "diagnostics")
os.makedirs(directory, exist_ok=True)
log_path = os.path.join(directory, "application.log")
handler = logging.handlers.RotatingFileHandler(log_path, maxBytes=1024*1024, backupCount=3, encoding="utf-8")
handler.setFormatter(SafeFormatter("%(asctime)s [%(levelname)s] %(message)s"))
if not journal.handlers:
    journal.addHandler(handler)
logging.getLogger("pywebview").addHandler(handler)


def export_journal():
    handler.acquire()
    try:
        handler.flush()
        chunks = []
        for suffix in (".3", ".2", ".1", ""):
            path = log_path + suffix
            if os.path.isfile(path):
                with open(path, encoding="utf-8", errors="replace") as source:
                    chunks.append(source.read())
        return redact("\n".join(chunks))
    finally:
        handler.release()
