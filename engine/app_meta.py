"""Shared application metadata and outbound client identity."""

from __future__ import annotations

import platform
import sys


APP_NAME = "Sadness VPN"
APP_SLUG = "SadnessVPN"
APP_VERSION = "3.4.3"


def windows_version() -> str:
    """Return the Windows version in the form subscription panels expect."""
    value = platform.version().strip()
    if value:
        return value
    release = platform.release().strip()
    return release or "unknown"


def architecture() -> str:
    machine = platform.machine().lower()
    return {
        "x86_64": "amd64",
        "amd64": "amd64",
        "aarch64": "arm64",
        "arm64": "arm64",
        "x86": "386",
        "i386": "386",
        "i686": "386",
    }.get(machine, machine or "unknown")


def _os_name() -> str:
    return "windows" if sys.platform == "win32" else "linux"


def os_version() -> str:
    """Версия ОС для панелей подписок: сборка Windows или версия ядра Linux."""
    if _os_name() == "windows":
        return windows_version()
    return platform.release().strip() or "unknown"


def subscription_user_agent() -> str:
    """Identify the real client; do not force a provider's Clash response template."""
    return (
        f"{APP_SLUG}/v{APP_VERSION} "
        f"platform/{_os_name()} platform-version/{os_version()} "
        f"arch/{architecture()}"
    )


def subscription_headers(hwid: str = "") -> dict[str, str]:
    name = _os_name()
    headers = {
        "User-Agent": subscription_user_agent(),
        "Accept": "*/*",
        "X-Client-Name": APP_NAME,
        "X-Client-Version": APP_VERSION,
        "X-Platform": name,
        "X-Platform-Version": os_version(),
        "X-Device-OS": name.capitalize(),
        "X-Ver-OS": os_version(),
        "X-Device-Model": "PC",
    }
    if hwid:
        headers.update({
            "HWID": hwid,
            "X-HWID": hwid,
            "Device-Id": hwid,
        })
    return headers
