"""Apply the local beta MSP and verify servicing without touching user profiles.

Refuses to run while the installed client/core is running. No Win32_Product
query (which would trigger repairs); no security exclusions or forced kills.
"""
import hashlib
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import winreg
import psutil

ROOT = Path(__file__).resolve().parents[1]
INSTALL = Path(os.environ["ProgramFiles"]) / "Sadness VPN"
PRODUCT = "{086ABB91-DFB2-599E-AB60-0C50D8152D24}"
PATCH = ROOT / "dist/SadnessVPN-2.0.17-to-2.0.18-Beta-Update-x64.msp"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def version():
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\" + PRODUCT, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
        return winreg.QueryValueEx(key, "DisplayVersion")[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--new", default="2.0.18")
    parser.add_argument("--base", default="2.0.17")
    parser.add_argument("--from-installed", default="2.0.17")
    parser.add_argument("--repeat", action="store_true")
    args = parser.parse_args()
    patch = ROOT / f"dist/SadnessVPN-{args.base}-to-{args.new}-Beta-Update-x64.msp"
    if not patch.is_file():
        raise RuntimeError(f"Patch not built: {patch}")
    for proc in psutil.process_iter(["exe"]):
        if proc.info["exe"] and Path(proc.info["exe"]).is_relative_to(INSTALL):
            raise RuntimeError("Close the installed Sadness VPN before the patch test")
    if version() != (args.new if args.repeat else args.from_installed):
        raise RuntimeError("Installed version does not match the requested test baseline")
    profile = Path(os.environ["LOCALAPPDATA"]) / "SadnessVPN/data"
    before = {p: digest(p) for p in profile.glob("*.json")}
    expected_stage = ROOT / f"build/installer-stage-{args.new}"
    # Prove the big runtime dependencies were not replaced by the patch.
    unchanged = {}
    for relative in ("runtime/_internal/bin/webview2/msedgewebview2.exe", "runtime/_internal/python311.dll", "runtime/_internal/bin/sing-box.exe", "runtime/_internal/bin/mihomo.exe"):
        path = INSTALL / relative
        unchanged[relative] = (digest(path), path.stat().st_ino)
    log = ROOT / f"build/apply-msp-{args.new.replace('.', '')}.log"
    result = subprocess.run(["msiexec.exe", "/p", str(patch), "/qn", "/norestart", "/L*v", str(log)], creationflags=0x08000000)
    if result.returncode not in (0, 3010):
        raise RuntimeError(f"MSP failed: {result.returncode}; {log}")
    assert version() == args.new, "Windows Installer version not updated"
    failures = []
    for row in (expected_stage / "files.sha256").read_text(encoding="ascii").splitlines():
        expected, relative = row.split("  ", 1)
        path = INSTALL / relative
        if not path.is_file() or digest(path) != expected:
            failures.append(relative)
    assert not failures, failures
    assert digest(INSTALL / "files.sha256") == digest(expected_stage / "files.sha256")
    assert all(p.is_file() and digest(p) == checksum for p, checksum in before.items()), "Profile changed"
    retained = all((digest(INSTALL / relative), (INSTALL / relative).stat().st_ino) == value for relative, value in unchanged.items())
    assert retained, "An unchanged runtime dependency was replaced"
    print(json.dumps({"version": version(), "msiExitCode": result.returncode, "profileFilesPreserved": len(before),
                      "allPayloadHashesMatch": True, "largeDependenciesRetained": retained}), flush=True)


if __name__ == "__main__":
    main()
