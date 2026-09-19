"""Validate authored rows; repair signed-word version conversion in the local draft."""
import msilib
from pathlib import Path
import sys

path = Path(__file__).resolve().parents[1] / "dist/SadnessVPN-2.0.17-Setup-x64.msi"
if "--path" in sys.argv:
    path = Path(sys.argv[sys.argv.index("--path") + 1]).resolve()
repair = "--fix-draft-versions" in sys.argv
db = msilib.OpenDatabase(str(path), 1 if repair else 0)
view = db.OpenView("SELECT * FROM `File`")
view.Execute(None)
fixed = 0
while row := view.Fetch():
    version = row.GetString(5)
    if repair and "-" in version:
        parts = version.split(".")
        assert len(parts) == 4
        row.SetString(5, ".".join(str(int(n) & 65535) for n in parts))
        view.Modify(msilib.MSIMODIFY_UPDATE, row)
        fixed += 1
view.Close()
if repair: db.Commit()
errors = []
for table in ("File", "Component", "Feature", "FeatureComponents", "Directory", "Shortcut", "Upgrade", "LaunchCondition", "InstallExecuteSequence", "InstallUISequence", "Dialog", "Control", "ControlEvent", "EventMapping", "RemoveFile"):
    v = db.OpenView("SELECT * FROM `" + table + "`")
    v.Execute(None)
    while row := v.Fetch():
        try:
            v.Modify(msilib.MSIMODIFY_VALIDATE, row)
        except msilib.MSIError:
            errors.append((table, row.GetString(1)))
    v.Close()
print({"fixedVersionRows": fixed, "validationErrors": errors[:15], "errorCount": len(errors)})
assert not errors
