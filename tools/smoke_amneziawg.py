"""Short administrator-only handshake smoke test for the imported AWG profile."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from engine.amneziawg import AmneziaWGManager  # noqa: E402


def _find_awg_server(groups: list) -> dict | None:
    for group in groups:
        for server in group.get("servers", []):
            if server.get("is_awg"):
                return server
    return None


def main() -> int:
    local_appdata = os.environ.get("LOCALAPPDATA")
    if not local_appdata:
        print("LOCALAPPDATA is unavailable")
        return 2
    store = Path(local_appdata, "SadnessVPN", "data", "wg_servers.json")
    try:
        groups = json.loads(store.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"Cannot read the WireGuard store: {type(exc).__name__}")
        return 2

    server = _find_awg_server(groups)
    if not server:
        print("No imported AWG server found")
        return 2

    def log(message: str, tag: str):
        print(f"[{tag}] {message}")

    manager = AmneziaWGManager(log_callback=log)
    try:
        # Preserve the profile's original routes during the smoke test so the
        # test itself does not redirect all traffic on the host.
        connected = manager.start(
            server,
            handshake_timeout=20,
            force_full_route=False,
        )
        if not connected:
            print("AWG_SMOKE=FAILED")
            return 1
        uploaded, downloaded = manager.get_transfer()
        print(f"AWG_SMOKE=OK transfer_up={uploaded} transfer_down={downloaded}")
        return 0
    finally:
        manager.stop()


if __name__ == "__main__":
    raise SystemExit(main())
