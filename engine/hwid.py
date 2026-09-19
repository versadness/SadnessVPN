"""Privacy-preserving, stable client identifiers.

The value is generated once and persisted by ui.server. It deliberately does not
contain motherboard, registry, MAC-address, user-name, or host-name data.
"""

import secrets


HWID_PREFIX = "svpn-"


def generate_hwid() -> str:
    """Return a new opaque 128-bit client identifier."""
    return HWID_PREFIX + secrets.token_hex(16)


def is_private_hwid(value: str) -> bool:
    if not isinstance(value, str) or not value.startswith(HWID_PREFIX):
        return False
    suffix = value[len(HWID_PREFIX):]
    return len(suffix) == 32 and all(ch in "0123456789abcdef" for ch in suffix)
