"""Build a native Windows Installer minor-update MSP from two released MSIs.

Requires the existing Windows SDK patchwiz.dll on the BUILD machine only.
End users only need Windows Installer. No custom privileged file-copy updater.
"""
import argparse
import ctypes
import gc
import json
import msilib
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]


def query(db, sql):
    view = db.OpenView(sql)
    view.Execute(None)
    result = []
    while row := view.Fetch():
        result.append(tuple(row.GetString(i) for i in range(1, row.GetFieldCount() + 1)))
    view.Close()
    return result


def verify_pair(old, new):
    databases = [msilib.OpenDatabase(str(p), 0) for p in (old, new)]
    props = [dict(query(db, "SELECT `Property`,`Value` FROM `Property`")) for db in databases]
    if props[0]["ProductCode"] != props[1]["ProductCode"] or props[0]["UpgradeCode"] != props[1]["UpgradeCode"]:
        raise ValueError("MSP requires matching product and upgrade identity")
    if tuple(map(int, props[0]["ProductVersion"].split("."))) >= tuple(map(int, props[1]["ProductVersion"].split("."))):
        raise ValueError("MSP must advance the installed version")
    # Do not silently create a patch after moving/removing component key paths.
    components = [dict((r[0], r[1:]) for r in query(db, "SELECT `Component`,`ComponentId`,`Directory_`,`KeyPath` FROM `Component`")) for db in databases]
    for key, value in components[0].items():
        if components[1].get(key) != value:
            raise ValueError("Not a compatible minor update: " + key)
    return props


def administrative_image(msi, destination):
    destination.mkdir(parents=True, exist_ok=False)
    log = destination / "admin-image.log"
    result = subprocess.run(["msiexec.exe", "/a", str(msi), "/qn", "TARGETDIR=" + str(destination),
                             "/L*v", str(log)], creationflags=0x08000000)
    if result.returncode not in (0, 3010):
        raise RuntimeError(f"Administrative image failed ({result.returncode}): {log}")
    image = destination / msi.name
    if not image.is_file():
        raise RuntimeError("Administrative MSI missing")
    return image


def create_pcp(path, old_image, new_image, output, product_code, version):
    db = msilib.OpenDatabase(str(path), msilib.MSIDBOPEN_CREATE)
    columns = {
        "Properties": "`Name` CHAR(72) NOT NULL, `Value` CHAR(0) PRIMARY KEY `Name`",
        "ImageFamilies": "`Family` CHAR(8) NOT NULL, `MediaSrcPropName` CHAR(72), `MediaDiskId` SHORT, `FileSequenceStart` LONG, `DiskPrompt` CHAR(128), `VolumeLabel` CHAR(32) PRIMARY KEY `Family`",
        "UpgradedImages": "`Upgraded` CHAR(13) NOT NULL, `MsiPath` CHAR(255) NOT NULL, `PatchMsiPath` CHAR(255), `SymbolPaths` CHAR(255), `Family` CHAR(8) NOT NULL PRIMARY KEY `Upgraded`",
        "TargetImages": "`Target` CHAR(13) NOT NULL, `MsiPath` CHAR(255) NOT NULL, `SymbolPaths` CHAR(255), `Upgraded` CHAR(13) NOT NULL, `Order` SHORT NOT NULL, `ProductValidateFlags` CHAR(16), `IgnoreMissingSrcFiles` SHORT NOT NULL PRIMARY KEY `Target`",
        "PatchMetadata": "`Company` CHAR(72), `Property` CHAR(72) NOT NULL, `Value` CHAR(0) PRIMARY KEY `Company`, `Property`",
    }
    for table, fields in columns.items():
        db.OpenView(f"CREATE TABLE `{table}` ({fields})").Execute(None)
    patch_guid = "{" + str(uuid.uuid4()).upper() + "}"
    msilib.add_data(db, "Properties", [
        ("PatchGUID", patch_guid), ("PatchOutputPath", str(output)),
        ("ListOfTargetProductCodes", product_code), ("MinimumRequiredMsiVersion", "300"),
        ("AllowProductCodeMismatches", "0"), ("AllowProductVersionMajorMismatches", "0"),
        # Only changed files, as whole files: reliable repair without needing
        # the old compressed PyInstaller EXE or original installation media.
        ("IncludeWholeFilesOnly", "1"), ("SEQUENCE_DATA_SUPERSEDENCE", "1"),
    ])
    msilib.add_data(db, "ImageFamilies", [("Sadness", None, None, None, None, None)])
    msilib.add_data(db, "UpgradedImages", [("New", str(new_image), None, None, "Sadness")])
    msilib.add_data(db, "TargetImages", [("Base", str(old_image), None, "New", 1, "0x00000922", 0)])
    msilib.add_data(db, "PatchMetadata", [(None, name, value) for name, value in (
        ("AllowRemoval", "1"), ("Classification", "Update"),
        ("CreationTimeUTC", __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%m-%d-%y %H:%M")),
        ("Description", "Sadness VPN Beta: Hysteria 2 and incremental servicing"),
        ("DisplayName", f"Sadness VPN {version} Beta Update"), ("ManufacturerName", "Sadness VPN"),
        ("TargetProductName", "Sadness VPN"), ("MoreInfoURL", "https://github.com/versadness/SadnessVPN/releases"))])
    db.Commit()
    del db
    gc.collect()
    return patch_guid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="2.0.17")
    parser.add_argument("--new", default="2.0.18")
    args = parser.parse_args()
    old, new = [ROOT / "dist" / f"SadnessVPN-{v}-Setup-x64.msi" for v in (args.base, args.new)]
    properties = verify_pair(old, new)
    work = ROOT / "build" / f"patch-{args.base}-to-{args.new}"
    work.mkdir(exist_ok=False)
    output = ROOT / "dist" / f"SadnessVPN-{args.base}-to-{args.new}-Beta-Update-x64.msp"
    if output.exists():
        raise FileExistsError(output)
    old_image = administrative_image(old, work / "base")
    new_image = administrative_image(new, work / "updated")
    pcp = work / "update.pcp"
    patch_guid = create_pcp(pcp, old_image, new_image, output, properties[0]["ProductCode"], args.new)
    libraries = sorted(Path(r"C:\Program Files (x86)\Windows Kits\10\bin").glob("*/x64/patchwiz.dll"))
    if not libraries:
        raise RuntimeError("Windows SDK x64 patchwiz.dll is required on the build machine")
    library = ctypes.WinDLL(str(libraries[-1]))
    build = library.UiCreatePatchPackageExW
    build.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_void_p,
                      ctypes.c_wchar_p, ctypes.c_int, ctypes.c_uint32, ctypes.c_uint32]
    build.restype = ctypes.c_uint32
    log = work / "patch-build.log"
    # fRemoveTempFolderIfPresent=false: never recursively delete a supplied path.
    result = build(str(pcp), str(output), str(log), None, str(work / "scratch"), False, 15, 0)
    if result:
        raise RuntimeError(f"Patch build failed 0x{result:08x}: {log}")
    print(json.dumps({"patch": str(output), "bytes": output.stat().st_size, "patchCode": patch_guid}), flush=True)


if __name__ == "__main__":
    main()
