"""Subscription transport and metadata. Never expose response bodies or URLs in errors."""
import base64
import gzip
import io
import re
import zlib
import socket
import time
import urllib.error
import urllib.request

from engine.app_meta import subscription_headers

MAX_BYTES = 8 * 1024 * 1024
GZIP_MAGIC = bytes((0x1F, 0x8B))


class SubscriptionError(ValueError):
    pass


class SubscriptionNotModified(SubscriptionError):
    """HTTP 304: у провайдера ничего не изменилось. Это не пустая подписка."""


class SubscriptionServers(list):
    def __init__(self, servers=(), metadata=None):
        super().__init__(servers)
        self.metadata = metadata or {}


def parse_metadata(headers):
    h = {str(k).lower(): str(v) for k, v in headers.items()}
    result = {"updated_at": int(time.time())}
    title = h.get("profile-title", "")
    if title.lower().startswith("base64:"):
        try:
            title = base64.b64decode(title[7:] + "===").decode("utf-8")
        except (ValueError, UnicodeError):
            title = ""
    title = "".join(c for c in title if c.isprintable()).strip()[:160]
    if title:
        result["provider_name"] = title
    for part in h.get("subscription-userinfo", "").split(";"):
        key, sep, value = part.strip().partition("=")
        if sep and key.lower() in {"upload", "download", "total", "expire"} and re.fullmatch(r"\d{1,16}", value.strip()):
            number = int(value.strip())
            if key.lower() != "expire" or number <= 253402300799:
                result[key.lower()] = number
    result["hwid_active"] = h.get("x-hwid-active", "").lower() == "true"
    return result


def check_device_headers(headers):
    h = {str(k).lower(): str(v).lower() for k, v in headers.items()}
    if h.get("x-hwid-max-devices-reached") == "true" or h.get("x-hwid-limit") == "true":
        raise SubscriptionError("Достигнут лимит устройств подписки. Удалите ненужное устройство в боте провайдера; сбрасывать HWID не нужно.")
    if h.get("x-hwid-not-supported") == "true":
        raise SubscriptionError("Провайдер не принял HWID клиента. Проверьте поддержку Sadness VPN у провайдера.")


def download_subscription(url, hwid=""):
    if hwid and not re.fullmatch(r"[a-zA-Z0-9=-]{10,64}", hwid):
        raise SubscriptionError("Сохранённый HWID несовместим с форматом подписок. В настройках можно создать новый ID; это зарегистрирует новое устройство у провайдера.")
    req = urllib.request.Request(url, headers=subscription_headers(hwid))
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            check_device_headers(resp.headers)
            metadata = parse_metadata(resp.headers)
            body = resp.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise SubscriptionError("Подписка превышает допустимый размер 8 МБ.")
            return _decompress(body, resp.headers.get("Content-Encoding", "")), metadata
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            raise SubscriptionNotModified("Подписка не изменилась с прошлого обновления.") from None
        check_device_headers(exc.headers)
        raise SubscriptionError(f"Провайдер вернул HTTP {exc.code}. Проверьте доступность и срок действия подписки.") from None
    except (TimeoutError, socket.timeout):
        raise SubscriptionError("Сервер подписки не ответил за 25 секунд. Проверьте сеть и повторите обновление.") from None
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            raise SubscriptionError("Сервер подписки не ответил за 25 секунд. Проверьте сеть и повторите обновление.") from None
        raise SubscriptionError("Не удалось загрузить подписку: ошибка сети, DNS или TLS. Проверьте доступность сервиса.") from None


def _decompress(body, encoding):
    """Некоторые панели сжимают ответ, даже если клиент не просил."""
    encoding = (encoding or "").lower().strip()
    try:
        if encoding == "gzip" or body[:2] == GZIP_MAGIC:
            with gzip.GzipFile(fileobj=io.BytesIO(body)) as handle:
                data = handle.read(MAX_BYTES + 1)
        elif encoding == "deflate":
            data = zlib.decompressobj().decompress(body, MAX_BYTES + 1)
        else:
            return body
    except (OSError, zlib.error, EOFError):
        raise SubscriptionError("Ответ провайдера повреждён: не удалось распаковать сжатые данные.") from None
    if len(data) > MAX_BYTES:
        raise SubscriptionError("Подписка превышает допустимый размер 8 МБ.")
    return data


def decode_subscription(body):
    raw = body.decode("utf-8-sig", errors="replace").strip()
    compact = "".join(raw.split())
    if compact and re.fullmatch(r"[A-Za-z0-9+/=_-]+", compact):
        try:
            decoded = base64.b64decode(compact + "===", altchars=b"-_").decode("utf-8-sig")
            if decoded.strip():
                raw = decoded.strip()
        except (ValueError, UnicodeError):
            pass
    if raw.lower().startswith(("<!doctype html", "<html")):
        raise SubscriptionError("Вместо подписки получена веб-страница. Нужна ссылка для импорта в VPN-клиент, а не страница личного кабинета.")
    return raw


def no_servers_error(raw):
    if re.search(r"(?m)^proxies:\s*\[\]", raw):
        return SubscriptionError("Провайдер вернул пустой список серверов (proxies: []). Проверьте подписку и поддержку клиента у провайдера; текущие серверы сохранены.")
    return SubscriptionError("В ответе нет поддерживаемых серверов. Нужен список ссылок VLESS/SS/Trojan/Hysteria2 либо Clash YAML. Текущие серверы сохранены.")
