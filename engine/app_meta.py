"""Shared application metadata and outbound client identity."""

from __future__ import annotations

import platform


APP_NAME = "Sadness VPN"
APP_SLUG = "SadnessVPN"
APP_VERSION = "3.1.9"


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


def subscription_user_agent() -> str:
    """Identify the real client; do not force a provider's Clash response template."""
    return (
        f"{APP_SLUG}/v{APP_VERSION} "
        f"platform/windows platform-version/{windows_version()} "
        f"arch/{architecture()}"
    )


def subscription_headers(hwid: str = "") -> dict[str, str]:
    headers = {
        "User-Agent": subscription_user_agent(),
        "Accept": "*/*",
        "X-Client-Name": APP_NAME,
        "X-Client-Version": APP_VERSION,
        "X-Platform": "windows",
        "X-Platform-Version": windows_version(),
        "X-Device-OS": "Windows",
        "X-Ver-OS": windows_version(),
        "X-Device-Model": "PC",
    }
    if hwid:
        headers.update({
            "HWID": hwid,
            "X-HWID": hwid,
            "Device-Id": hwid,
        })
    return headers
