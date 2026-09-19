"""Inspect non-secret runtime settings of a locally stored official AWG profile."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path


MANAGER = Path(r"C:\Program Files\AmneziaWG\amneziawg.exe")
AWG = Path(r"C:\Program Files\AmneziaWG\awg.exe")
PROFILE_NAME = sys.argv[1] if len(sys.argv) > 1 else "AmneziaWG-Germany"
if PROFILE_NAME not in {"AmneziaWG-Germany", "AmneziaWG-Russia"}:
    raise SystemExit("Unsupported diagnostic profile")
PROFILE = Path(
    r"C:\Program Files\AmneziaWG\Data\Configurations",
    f"{PROFILE_NAME}.conf.dpapi",
)
TUNNEL = PROFILE_NAME


def run(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def main() -> int:
    install = run([str(MANAGER), "/installtunnelservice", str(PROFILE)])
    if install.returncode != 0:
        print(f"INSTALL_FAILED={install.returncode}")
        return 1
    try:
        deadline = time.time() + 10
        handshake = "0"
        while time.time() < deadline:
            result = run([str(AWG), "show", TUNNEL, "latest-handshakes"])
            if result.returncode == 0 and result.stdout.strip():
                handshake = result.stdout.split()[-1]
                if handshake.isdigit() and int(handshake) > 0:
                    break
            time.sleep(0.5)
        print(f"OFFICIAL_HANDSHAKE={'OK' if handshake.isdigit() and int(handshake) > 0 else 'FAILED'}")

        status = run([str(AWG), "show", TUNNEL])
        safe_terms = (
            "endpoint:",
            "allowed ips:",
            "latest handshake:",
            "persistent keepalive:",
            "junk",
            "padding",
            "header",
        )
        for line in status.stdout.splitlines():
            if any(term in line.lower() for term in safe_terms):
                print(line.strip())
        return 0 if handshake.isdigit() and int(handshake) > 0 else 1
    finally:
        run([str(MANAGER), "/uninstalltunnelservice", TUNNEL])


if __name__ == "__main__":
    raise SystemExit(main())
