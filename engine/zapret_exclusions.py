"""Адреса VPN-серверов, которые winws обязан пропускать без обработки.

Когда Mihomo и Zapret работают одновременно, WinDivert видит не только обычный
трафик, но и внешнее зашифрованное соединение с VPN-сервером: оно идёт на те же
443 и 80, что и всё остальное. Десинхронизация этого соединения ломает сам
туннель — ровно та поломка, которую пользователь потом принимает за «VPN не
работает».

Поэтому перед запуском обхода адреса всех известных VPN-эндпоинтов
записываются в lists/ipset-exclude-user.txt: профили Flowseal уже передают этот
файл через ``--ipset-exclude``.

Файл пользовательский, поэтому свои строки он сохраняет: управляемый блок
ограничен маркерами и переписывается только внутри них.
"""
from __future__ import annotations

import ipaddress
import os
import socket

BEGIN = "# >>> SadnessVPN: адреса VPN-серверов, добавлено автоматически >>>"
END = "# <<< SadnessVPN <<<"


def _addresses(host: str, port: int = 443) -> list[str]:
    """IP-адреса узла. Имя резолвится обычным системным DNS."""
    if not host:
        return []
    try:
        ipaddress.ip_address(host)
        return [host]
    except ValueError:
        pass
    try:
        found = socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except OSError:
        return []
    return list(dict.fromkeys(item[4][0] for item in found))


def collect(servers) -> list[str]:
    """Собрать адреса из списка серверов. Пароли и ключи не читаются."""
    result: list[str] = []
    for server in servers or []:
        if not isinstance(server, dict):
            continue
        host = str(server.get("host") or "")
        try:
            port = int(server.get("port") or 443)
        except (TypeError, ValueError):
            port = 443
        for address in _addresses(host, port):
            if address not in result:
                result.append(address)
    return result


def render(existing: str, addresses) -> str:
    """Вернуть содержимое файла с обновлённым управляемым блоком."""
    lines = existing.splitlines()
    kept, inside = [], False
    for line in lines:
        if line.strip() == BEGIN:
            inside = True
            continue
        if line.strip() == END:
            inside = False
            continue
        if not inside:
            kept.append(line)
    while kept and not kept[-1].strip():
        kept.pop()
    if not addresses:
        return ("\n".join(kept) + "\n") if kept else ""
    block = [BEGIN, *addresses, END]
    return "\n".join([*kept, *block]) + "\n"


def write(path: str, servers) -> list[str]:
    """Обновить файл исключений. Возвращает записанные адреса."""
    addresses = collect(servers)
    try:
        existing = ""
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as handle:
                existing = handle.read()
        content = render(existing, addresses)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
    except OSError:
        return []
    return addresses
