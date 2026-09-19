"""Refresh UI in the unpublished 2.0.18 build made while UI authoring completed."""
from pathlib import Path
import sys
import msilib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from installer.build_msi import add_ui

db = msilib.OpenDatabase(str(ROOT / "dist/SadnessVPN-2.0.18-Setup-x64.msi"), 1)
for table in ("ControlEvent", "EventMapping", "Control", "Dialog", "TextStyle"):
    db.OpenView(f"DELETE FROM `{table}`").Execute(None)
for name in ("DefaultUIFont", "ErrorDialog"):
    db.OpenView(f"DELETE FROM `Property` WHERE `Property`='{name}'").Execute(None)
for name in ("WelcomeDlg", "MaintenanceDlg", "UpdateDlg", "ProgressDlg"):
    db.OpenView(f"DELETE FROM `InstallUISequence` WHERE `Action`='{name}'").Execute(None)
add_ui(db)
msilib.add_data(db, "InstallUISequence", [("WelcomeDlg", "NOT Installed", 1230),
    ("UpdateDlg", "Installed AND PATCH AND NOT REMOVE", 1232),
    ("MaintenanceDlg", "Installed AND NOT PATCH AND NOT RESUME AND NOT REMOVE AND NOT REINSTALL", 1235),
    ("ProgressDlg", None, 1280)])
db.Commit()
print("Unpublished 2.0.18 MSI UI synchronized with build_msi.py")
