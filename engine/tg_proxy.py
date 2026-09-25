"""Telegram WS Proxy — локальный MTProto-прокси для Telegram Desktop.

Код прокси — вендорная копия Flowseal/tg-ws-proxy (engine/tgws, MIT). Прокси
принимает подключения Telegram на 127.0.0.1 и ведёт их к дата-центрам
Telegram через WebSocket (kws*.web.telegram.org), а при недоступности — через
Cloudflare-фолбэк самого проекта.

Прокси работает в отдельном потоке бэкенда со своим asyncio-циклом, как в
трей-приложении upstream: отдельного процесса нет, и после закрытия
приложения ничего не остаётся висеть. Модули upstream хранят состояние
глобально, поэтому экземпляр прокси всегда один.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import socket
import threading
import time

HOST = "127.0.0.1"
DEFAULT_PORT = 1443
# Порты ниже 1024 — системные, а эти заняты самим приложением.
MIN_PORT = 1024
RESERVED_PORTS = {45678: "интерфейс Sadness VPN"}
DEFAULT_DC_IPS = ["2:149.154.167.220", "4:149.154.167.220"]
_SECRET_RE = re.compile(r"^[0-9a-f]{32}$")
_START_TIMEOUT = 5.0


class TgProxyError(ValueError):
    """Некорректная настройка прокси — показывается пользователю как есть."""


def new_secret() -> str:
    return os.urandom(16).hex()


def normalize(raw, reserved=None) -> dict:
    """Проверенная настройка. Бросает TgProxyError."""
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise TgProxyError("Некорректная настройка Telegram-прокси")
    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise TgProxyError("Некорректная настройка Telegram-прокси")
    port = raw.get("port", DEFAULT_PORT)
    if isinstance(port, bool):
        raise TgProxyError("Порт должен быть числом")
    try:
        port = int(str(port).strip())
    except (TypeError, ValueError):
        raise TgProxyError("Порт должен быть числом") from None
    if not MIN_PORT <= port <= 65535:
        raise TgProxyError(f"Порт должен быть в диапазоне {MIN_PORT}–65535")
    taken = {**RESERVED_PORTS, **(reserved or {})}
    if port in taken:
        raise TgProxyError(f"Порт {port} уже использует {taken[port]}")
    secret = str(raw.get("secret") or "").strip().lower()
    if not _SECRET_RE.match(secret):
        secret = new_secret()
    return {"enabled": enabled, "port": port, "secret": secret}


def normalize_stored(raw) -> dict:
    """Для чтения с диска: битое значение заменяется умолчанием."""
    try:
        return normalize(raw)
    except TgProxyError:
        return normalize(None)


def link(config: dict) -> str:
    """Ссылка tg://proxy для Telegram. Префикс dd — режим с защитой от DPI."""
    return (f"tg://proxy?server={HOST}&port={int(config['port'])}"
            f"&secret=dd{config['secret']}")


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((HOST, port))
        except OSError:
            return False
    return True


class _LogBridge(logging.Handler):
    """Журнал upstream → журнал приложения, без секрета и ссылки с ним."""

    def __init__(self, manager):
        super().__init__(logging.INFO)
        self._manager = manager

    def emit(self, record):
        try:
            message = record.getMessage()
        except Exception:
            return
        secret = self._manager.secret
        if secret and secret in message:
            if "tg://" in message or "Secret" in message:
                return
            message = message.replace(secret, "…")
        if not message.strip() or set(message.strip()) == {"="}:
            return
        # Ежеминутная статистика засоряла бы журнал приложения.
        if message.startswith("stats:"):
            return
        tag = "err" if record.levelno >= logging.ERROR else \
            "warn" if record.levelno >= logging.WARNING else "log"
        self._manager.log_cb(f"[tg-proxy] {message.strip()}", tag)


class TgProxyManager:
    def __init__(self, log_callback=None, exit_callback=None):
        self.log_cb = log_callback or (lambda msg, tag: None)
        self.exit_cb = exit_callback or (lambda error: None)
        self._lock = threading.Lock()
        self._thread = None
        self._loop = None
        self._stop_event = None
        self._stopping = False
        self._error = None
        self.port = None
        self.secret = None
        self._bridge = _LogBridge(self)
        logger = logging.getLogger("tg-mtproto-proxy")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        # Экземпляр прокси один на процесс, поэтому журнал получает последний менеджер.
        for handler in [h for h in logger.handlers if isinstance(h, _LogBridge)]:
            logger.removeHandler(handler)
        logger.addHandler(self._bridge)

    @property
    def running(self) -> bool:
        thread = self._thread
        return bool(thread and thread.is_alive())

    def start(self, config: dict) -> tuple[bool, str | None]:
        """Запустить прокси. Возвращает (успех, текст ошибки)."""
        from engine.tgws import config as upstream_config
        from engine.tgws import tg_ws_proxy as upstream

        with self._lock:
            if self.running:
                return True, None
            port = int(config["port"])
            if not port_free(port):
                return False, f"Порт {port} занят другим приложением — выберите другой"

            pc = upstream_config.proxy_config
            pc.host = HOST
            pc.port = port
            pc.secret = config["secret"]
            pc.dc_redirects = upstream_config.parse_dc_ip_list(DEFAULT_DC_IPS)
            pc.fallback_cfproxy = True
            pc.cfproxy_user_domains = []
            pc.cfproxy_worker_domains = []
            pc.fake_tls_domain = ""
            pc.proxy_protocol = False
            pc.force_test_dc = False
            pc.disable_secure = False
            self.port, self.secret = port, config["secret"]
            self._error = None
            self._stopping = False
            upstream._server_instance = None

            ready = threading.Event()
            thread = threading.Thread(target=self._run, args=(upstream, ready),
                                      daemon=True, name="tg-ws-proxy")
            self._thread = thread
            thread.start()

        deadline = time.monotonic() + _START_TIMEOUT
        while time.monotonic() < deadline and thread.is_alive():
            if upstream._server_instance is not None:
                self.log_cb(f"Telegram-прокси запущен на {HOST}:{port}", "ok")
                return True, None
            ready.wait(0.05)
        if thread.is_alive():
            # Сервер так и не поднялся — не оставляем полуживой поток.
            self.stop(quiet=True)
            return False, "Прокси не успел запуститься"
        return False, self._error or "Прокси завершился сразу после запуска"

    def _run(self, upstream, ready):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        stop_event = asyncio.Event()
        self._loop, self._stop_event = loop, stop_event
        try:
            loop.run_until_complete(upstream._run(stop_event=stop_event))
        except OSError as exc:
            self._error = (f"Порт {self.port} занят другим приложением"
                           if getattr(exc, "winerror", None) in (10048, 10013)
                           else f"Сетевая ошибка прокси: {exc}")
        except Exception as exc:
            self._error = f"Сбой прокси: {exc!r}"
        finally:
            pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            finally:
                loop.close()
            self._loop = self._stop_event = None
            ready.set()
            unexpected = not self._stopping and upstream._server_instance is not None
            upstream._server_instance = None
            # Ошибку до подъёма сервера возвращает start(); здесь — только
            # падение уже работавшего прокси.
            if unexpected:
                self.log_cb("Telegram-прокси неожиданно остановился"
                            + (f": {self._error}" if self._error else ""), "err")
                try:
                    self.exit_cb(self._error)
                except Exception:
                    pass

    def stop(self, quiet=False):
        with self._lock:
            thread, loop, stop_event = self._thread, self._loop, self._stop_event
            self._stopping = True
            if loop is not None and stop_event is not None:
                try:
                    loop.call_soon_threadsafe(stop_event.set)
                except RuntimeError:
                    pass  # цикл уже закрыт
            if thread is not None:
                thread.join(timeout=5)
                if thread.is_alive():
                    self.log_cb("Telegram-прокси не остановился за 5 секунд", "warn")
            self._thread = None
        if thread is not None and not quiet:
            self.log_cb("Telegram-прокси остановлен", "info")
