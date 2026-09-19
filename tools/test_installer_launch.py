"""Negative preflight check: a standalone launcher must diagnose missing runtime."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
launcher = root / "build/installer-stage-2.0.17/SadnessVPN.exe"
with tempfile.TemporaryDirectory(prefix="sadness-missing-runtime-") as folder:
    copy = Path(folder, "SadnessVPN.exe")
    shutil.copy2(launcher, copy)
    result = subprocess.run([str(copy), "--check", "--quiet"], timeout=15,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 1, result.returncode
    path = Path(os.environ["LOCALAPPDATA"], "SadnessVPN/data/diagnostics/launcher.log")
    # GetFolderPath may not use an overridden test environment, so the real user
    # profile is deliberately used only to read the launcher's own diagnostics.
    text = path.read_text(encoding="utf8")
    assert "runtime/SadnessVPN.exe" in text.splitlines()[-1]
    print("PASS: missing Python payload prevented; exact filename logged before Python started")
