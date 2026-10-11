"""Build a standard, offline x64 MSI with Windows' cabinet/MSI APIs (Python 3.11).

No installer compiler download, custom extraction wrapper, or antivirus exclusions.
One file per stable component; Windows Installer owns install/repair/uninstall.
"""
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning, module=".*")
import msilib
from msilib import schema, sequence, text, add_data, Dialog

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine.app_meta import APP_VERSION

NAMESPACE = uuid.UUID("f32aa11c-42dd-4ef9-a65f-d5efb8cad112")
UPGRADE_CODE = "{2697D9D3-96DB-4DCC-A018-B47AD3B3FBB1}"
# Keep the 2.x servicing identity stable so .msp minor updates remain registered
# with the original installation. Change only for a deliberate major upgrade.
# 2.0.26 — мажорный апгрейд: WebView2 удалён, а minor upgrade не умеет
# удалять компоненты. Новый ProductCode при прежнем UpgradeCode заставляет
# RemoveExistingProducts снести старую установку и поставить новую.
# 3.0.4 — обновления больше не идут через MSP: версии ставятся рядом, а
# указатель переключается апдейтером. Совместимость патчей с базой больше
# ничего не связывает, поэтому MSI снова мажорный — он ставится двойным
# кликом поверх любой предыдущей версии.
PRODUCT_BASE_VERSION = "3.0.4"


def guid(value):
    return "{" + str(uuid.uuid5(NAMESPACE, value)).upper() + "}"


def ident(prefix, value):
    return prefix + hashlib.sha256(value.encode()).hexdigest()[:24]


def add_ui(db):
    add_data(db, "TextStyle", [("Normal", "Segoe UI", 9, None, 0), ("Heading", "Segoe UI", 14, None, 1)])
    add_data(db, "Property", [("DefaultUIFont", "Normal"), ("ErrorDialog", "ErrorDlg")])
    for name, message, exitcode in (("ExitDialog", "Setup completed. Start Sadness VPN from the desktop or Start menu.\nPersonal profiles were preserved.", "Return"),
                                     ("FatalError", "Setup could not be completed.\nLog: [MsiLogFileLocation]", "Exit"),
                                     ("UserExit", "Setup was cancelled.\nLog: [MsiLogFileLocation]", "Exit")):
        dialog = Dialog(db, name, 50, 50, 370, 210, 3, "Sadness VPN Setup", "Finish", "Finish", "Finish")
        dialog.text("Heading", 20, 20, 330, 25, 3, "{\\Heading}Sadness VPN " + APP_VERSION + " Beta")
        dialog.text("Message", 20, 60, 330, 100, 3, message)
        dialog.pushbutton("Finish", 280, 178, 70, 20, 3, "Finish", None).event("EndDialog", exitcode)
    welcome = Dialog(db, "WelcomeDlg", 50, 50, 370, 250, 3, "Sadness VPN Setup", "Install", "Install", "Cancel")
    welcome.text("Heading", 20, 20, 330, 30, 3, "{\\Heading}Install Sadness VPN " + APP_VERSION + " Beta")
    welcome.text("Message", 20, 65, 330, 90, 3,
                 "Offline package for Windows 10/11 x64. Electron, Python and VPN cores are included.\n\n"
                 "Close Sadness VPN before installing. Personal subscriptions and settings are not included or removed.\n\n"
                 "This package does not disable Windows security.")
    welcome.text("Path", 20, 168, 330, 30, 3, "Install folder: [INSTALLDIR]")
    welcome.pushbutton("Install", 200, 217, 70, 20, 3, "Install", "Cancel").event("EndDialog", "Return")
    welcome.pushbutton("Cancel", 280, 217, 70, 20, 3, "Cancel", "Install").event("EndDialog", "Exit")
    update = Dialog(db, "UpdateDlg", 50, 50, 370, 235, 3, "Sadness VPN Beta Update", "Update", "Update", "Cancel")
    update.text("Heading", 20, 20, 330, 30, 3, "{\\Heading}Update to " + APP_VERSION + " Beta")
    update.text("Message", 20, 65, 330, 95, 3, "Close Sadness VPN and disconnect VPN first.\n\nOnly updated components are included. Your subscriptions, settings and desktop shortcut are preserved.\n\nNo uninstall is needed.")
    button = update.pushbutton("Update", 200, 195, 70, 22, 3, "Update", "Cancel")
    button.event("[REINSTALL]", "ALL", ordering=1)
    button.event("[REINSTALLMODE]", "omus", ordering=2)
    button.event("EndDialog", "Return", ordering=3)
    update.pushbutton("Cancel", 280, 195, 70, 22, 3, "Cancel", "Update").event("EndDialog", "Exit")
    maintenance = Dialog(db, "MaintenanceDlg", 50, 50, 370, 235, 3, "Sadness VPN Maintenance", "Repair", "Repair", "Cancel")
    maintenance.text("Heading", 20, 20, 330, 30, 3, "{\\Heading}Repair or remove Sadness VPN")
    maintenance.text("Message", 20, 65, 330, 85, 3, "Close Sadness VPN first. Repair reinstalls bundled components.\n\nRemoval preserves your personal settings, subscriptions and logs. Turn off autostart in the app before removing it.")
    repair = maintenance.pushbutton("Repair", 120, 195, 70, 22, 3, "Repair", "Remove")
    repair.event("[REINSTALL]", "ALL", ordering=1)
    repair.event("[REINSTALLMODE]", "amus", ordering=2)
    repair.event("EndDialog", "Return", ordering=3)
    remove = maintenance.pushbutton("Remove", 200, 195, 70, 22, 3, "Remove", "Cancel")
    remove.event("[REMOVE]", "ALL", ordering=1)
    remove.event("EndDialog", "Return", ordering=2)
    maintenance.pushbutton("Cancel", 280, 195, 70, 22, 3, "Cancel", "Repair").event("EndDialog", "Exit")
    progress = Dialog(db, "ProgressDlg", 50, 50, 370, 180, 1, "Sadness VPN Setup", "Status", None, None)
    progress.text("Heading", 20, 20, 330, 30, 3, "{\\Heading}Installing / updating components")
    progress.text("Status", 20, 65, 330, 40, 3, "Please wait...").mapping("ActionText", "Text")
    progress.control("Progress", "ProgressBar", 20, 118, 330, 16, 65537, None, None, None, None).mapping("SetProgress", "Progress")
    error = Dialog(db, "ErrorDlg", 50, 50, 370, 230, 65539, "Sadness VPN Setup", "OK", "OK", "OK")
    error.text("ErrorText", 20, 20, 330, 155, 3, "[ErrorText]")
    for number, caption in ((1, "OK"), (2, "Cancel"), (3, "Abort"), (4, "Retry"), (5, "Ignore"), (6, "Yes"), (7, "No")):
        button = error.pushbutton(caption, 20 + ((number-1) % 4)*85, 190, 70, 22, 3, caption, None)
        button.event("EndDialog", str(number))
    files = Dialog(db, "FilesInUse", 50, 50, 370, 230, 3, "Close running applications", "Retry", "Retry", "Exit")
    files.text("Text", 20, 20, 330, 45, 3, "Close Sadness VPN and the processes below, then click Retry. Your VPN connection must be stopped first.")
    files.control("List", "ListBox", 20, 75, 330, 95, 7, "FileInUseProcess", None, None, None)
    files.pushbutton("Retry", 200, 195, 70, 22, 3, "Retry", "Exit").event("EndDialog", "Retry")
    files.pushbutton("Exit", 280, 195, 70, 22, 3, "Cancel", "Retry").event("EndDialog", "Exit")


# Каталоги, входившие в пакет Electron до 3.0.6. Обновление поверх прежней
# версии оставило бы их на диске: msiexec удаляет только то, что перечислено
# в RemoveFile, — на 3.0.5 это 62 МБ мусора.
_KOFFI = Path("electron/resources/app.asar.unpacked/node_modules/koffi")
_STALE_KOFFI_PLATFORMS = (
    "darwin_arm64", "darwin_x64", "freebsd_arm64", "freebsd_ia32", "freebsd_x64",
    "linux_arm64", "linux_armhf", "linux_ia32", "linux_loong64", "linux_riscv64d",
    "linux_x64", "musl_arm64", "musl_x64", "openbsd_ia32", "openbsd_x64",
    "win32_arm64", "win32_ia32",
)
# Вложенные каталоги идут раньше родительских: пустой каталог удаляется только
# после того, как из него вынесены файлы и подкаталоги.
_STALE_KOFFI_TREES = ("doc", "src/cnoke/assets", "src/cnoke/src", "src/cnoke",
                      "src/koffi/src", "src/koffi/tools", "src/koffi", "src")


def _short_name(name, used):
    base = re.sub(r"[^A-Z0-9]", "", name.upper())[:6] or "DIR"
    for index in range(1, 1000):
        candidate = base + "~" + str(index)
        if candidate not in used:
            used.add(candidate)
            return candidate
    raise RuntimeError("Не удалось подобрать короткое имя каталога: " + name)


def stale_electron_removals(db, directories, component):
    """RemoveFile-строки для того, что выведено из пакета Electron в 3.0.6.

    Маски по каталогу locales здесь нет и быть не должно. Полный MSI после
    RemoveFiles ставит ru.pak и en-US.pak заново, а патч (MSP) переустанавливает
    только изменившиеся файлы: маска *.pak удаляла языки Electron, и окно после
    обновления патчем падало (3.4.4 → 3.4.5). Лишние языки старше 3.0.6 у всех,
    кто с тех пор обновлялся, уже удалены.
    """
    rows, nodes, shorts = [], {}, {}

    def node_for(path, parent_logical):
        if path in nodes:
            return nodes[path]
        logical = ident("D", "stale/" + path.as_posix())
        used = shorts.setdefault(parent_logical, set())
        add_data(db, "Directory",
                 [(logical, parent_logical, _short_name(path.name, used) + "|" + path.name)])
        nodes[path] = logical
        return logical

    targets = []
    builds = directories.get(_KOFFI / "build" / "koffi")
    if builds:
        targets += [(_KOFFI / "build" / "koffi" / name, builds.logical)
                    for name in _STALE_KOFFI_PLATFORMS]
    root = directories.get(_KOFFI)
    if root:
        for tree in _STALE_KOFFI_TREES:
            parts = Path(tree).parts
            parent = root.logical
            for level in range(1, len(parts)):
                parent = node_for(_KOFFI.joinpath(*parts[:level]), parent)
            targets.append((_KOFFI / tree, parent))

    for path, parent_logical in targets:
        logical = node_for(path, parent_logical)
        key = ident("R", path.as_posix())
        rows.append((key + "F", component, "*", logical, 1))
        rows.append((key + "D", component, None, logical, 1))
    return rows


def main():
    source = ROOT / "dist" / ("SadnessVPN-v" + APP_VERSION + "-installer-runtime") / "SadnessVPN"
    stage = ROOT / "build" / ("installer-stage-" + APP_VERSION)
    output = ROOT / "dist" / ("SadnessVPN-" + APP_VERSION + "-Setup-x64.msi")
    if not source.is_dir():
        raise RuntimeError("Build PyInstaller runtime first")
    # Оболочка Electron: интерфейс приложения. Python-пакет в runtime/ остаётся
    # на месте и работает бэкендом, поэтому все ранее зарегистрированные
    # компоненты MSI сохраняются и прямые MSP-патчи продолжают собираться.
    electron = ROOT / "dist" / "electron-runtime" / "win-unpacked"
    if not electron.is_dir():
        raise RuntimeError("Соберите оболочку Electron: npm run pack:runtime")
    if not (electron / "Sadness VPN.exe").is_file():
        raise RuntimeError("В сборке Electron нет 'Sadness VPN.exe'")
    stage.mkdir(parents=True, exist_ok=False)
    shutil.copytree(source, stage / "runtime", dirs_exist_ok=True)
    shutil.copytree(electron, stage / "electron", dirs_exist_ok=True)
    updater = ROOT / 'dist' / 'updater' / 'SadnessUpdater.exe'
    if not updater.is_file():
        raise FileNotFoundError('Build SadnessUpdater.spec before assembling the MSI')
    shutil.copy2(updater, stage / 'SadnessUpdater.exe')
    shutil.copy2(ROOT / "INSTALL-README.txt", stage / "INSTALL-README.txt")
    compiler = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    # Версия лаунчера подставляется при сборке. Раньше она была захардкожена
    # в Launcher.cs и с какого-то момента перестала совпадать с реальной —
    # логи писали чужой номер, что сбивало с толку при разборе проблем.
    launcher_source = ROOT / "installer" / "Launcher.cs"
    generated = ROOT / "build" / ("Launcher-" + APP_VERSION + ".cs")
    launcher_text = launcher_source.read_text(encoding="utf-8")
    launcher_text = re.sub(r'AssemblyVersion\("[\d.]+"\)', 'AssemblyVersion("' + APP_VERSION + '.0")', launcher_text, count=1)
    launcher_text = re.sub(r'AssemblyFileVersion\("[\d.]+"\)', 'AssemblyFileVersion("' + APP_VERSION + '.0")', launcher_text, count=1)
    for attribute in ('AssemblyVersion', 'AssemblyFileVersion'):
        if f'{attribute}("{APP_VERSION}.0")' not in launcher_text:
            raise RuntimeError('Launcher version substitution failed: ' + attribute)
    generated.parent.mkdir(parents=True, exist_ok=True)
    generated.write_text(launcher_text, encoding="utf-8")
    subprocess.run([str(compiler), "/nologo", "/target:winexe", "/platform:x64", "/optimize+",
                    "/reference:System.Windows.Forms.dll", "/out:" + str(stage / "SadnessVPN.exe"),
                    "/win32icon:" + str(ROOT / "app.ico"), "/win32manifest:" + str(ROOT / "installer/launcher.manifest"),
                    str(generated)], check=True)
    files = sorted(p for p in stage.rglob("*") if p.is_file() and p.name != "files.sha256")
    # Пакет уходит другим людям, поэтому личные данные не должны попасть в него
    # даже случайно. Проверяем и по именам, и по содержимому: ссылки на серверы
    # и ключи WireGuard не могут находиться нигде, кроме подсказок в интерфейсе.
    private_names = {
        "servers.json", "servers.json.bak", "settings.json", "apps.json",
        "stats.json", "wg_servers.json", "window-appearance.json",
        "window-state.json", "subscriptions.json",
    }
    allowed_placeholders = {"index.html", "app.js"}
    secret_markers = (b"vless://", b"trojan://", b"ss://", b"hysteria2://", b"PrivateKey")
    for path in files:
        if path.name in private_names or path.suffix.lower() in {".bat", ".log"}:
            raise RuntimeError("Unexpected private/script file: " + path.name)
        if path.name in allowed_placeholders or path.suffix.lower() not in {".json", ".txt", ".conf"}:
            continue
        blob = path.read_bytes()
        for marker in secret_markers:
            if marker in blob:
                raise RuntimeError(
                    "Possible private data in " + path.relative_to(stage).as_posix()
                    + " (marker: " + marker.decode() + ")"
                )
    manifest = stage / "files.sha256"
    # Mechanical generated build output, not a source-code edit.
    rows = []
    for path in files:
        with path.open("rb") as stream:
            rows.append(hashlib.file_digest(stream, "sha256").hexdigest() + "  " + path.relative_to(stage).as_posix() + "\n")
    manifest.write_text("".join(rows), encoding="ascii")
    files.append(manifest)
    if output.exists():
        raise FileExistsError("Refusing to overwrite an existing published MSI: " + str(output))
    db = msilib.init_database(str(output), schema, "Sadness VPN", guid("product:" + PRODUCT_BASE_VERSION), APP_VERSION, "Sadness VPN")
    msilib.add_tables(db, sequence)
    msilib.add_tables(db, text)
    # Resolve prerequisite registry searches before evaluating conditions.
    for table in ("InstallUISequence", "InstallExecuteSequence"):
        db.OpenView("UPDATE `" + table + "` SET `Sequence`=450 WHERE `Action`='LaunchConditions'").Execute(None)
    db.OpenView("UPDATE `InstallExecuteSequence` SET `Sequence`=1510 WHERE `Action`='RemoveExistingProducts'").Execute(None)
    add_data(db, "Property", [("ALLUSERS", "1"), ("UpgradeCode", UPGRADE_CODE), ("INSTALLLEVEL", "1"),
        ("ARPPRODUCTICON", "AppIcon"), ("MsiLogging", "voicewarmup"), ("REBOOT", "ReallySuppress"),
        ("MSIRESTARTMANAGERCONTROL", "Disable"), ("SecureCustomProperties", "OLDPRODUCTS;NEWERPRODUCTS"),
        ("ARPCOMMENTS", "BETA. Offline client. Update existing installations with the MSP patch; personal profiles are preserved.")])
    add_data(db, "Upgrade", [(UPGRADE_CODE, None, APP_VERSION, None, 1, None, "OLDPRODUCTS"),
                              (UPGRADE_CODE, APP_VERSION, None, None, 258, None, "NEWERPRODUCTS")])
    add_data(db, "RegLocator", [("NetRelease", 2, r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full", "Release", 18),
                                ("WinBuild", 2, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion", "CurrentBuildNumber", 18)])
    add_data(db, "AppSearch", [("NETRELEASE", "NetRelease"), ("WINBUILD", "WinBuild")])
    add_data(db, "LaunchCondition", [
        ("Installed OR (VersionNT64 AND WINBUILD >= 19041)", "Windows 10 version 2004 or newer / Windows 11 x64 is required."),
        ('Installed OR NETRELEASE >= "#528040"', ".NET Framework 4.8 is required. Restore the Windows component and run Setup again."),
        ("NOT NEWERPRODUCTS", "A newer version of Sadness VPN is already installed.")])
    add_data(db, "Icon", [("AppIcon", msilib.Binary(str(ROOT / "app.ico")))])
    feature = msilib.Feature(db, "Main", "Sadness VPN", "Complete offline client", 1)
    feature.set_current()
    cab = msilib.CAB("payload.cab")
    target = msilib.Directory(db, cab, None, str(stage), "TARGETDIR", "SourceDir", 0)
    programfiles = msilib.Directory(db, cab, target, ".", "ProgramFiles64Folder", ".", 0)
    installed = msilib.Directory(db, cab, programfiles, str(stage), "INSTALLDIR", "SADNES~1|Sadness VPN", 0)
    directories = {Path("."): installed}
    for path in sorted({p.parent.relative_to(stage) for p in files}, key=lambda p: (len(p.parts), str(p))):
        if path in directories: continue
        for level in range(1, len(path.parts)+1):
            partial = Path(*path.parts[:level])
            if partial not in directories:
                parent = directories[partial.parent]
                directories[partial] = msilib.Directory(db, cab, parent, partial.name, ident("D", partial.as_posix()), parent.make_short(partial.name) + "|" + partial.name, 0)
    launcher_component = None
    updater_file = None
    # Ключи файлов выводятся только из пути.
    # Раньше они подхватывались из старого dist/SadnessVPN-2.0.19-Setup-x64.msi
    # ради совместимости с историческими пакетами. Это оказалось ловушкой:
    # когда файл удалили при чистке диска, ключи молча поменялись и патчи
    # перестали собираться. Сборка не должна зависеть от содержимого dist.
    for file in files:
        relative = file.relative_to(stage)
        directory = directories[relative.parent]
        component = ident("C", relative.as_posix())
        key_id=ident('F',relative.as_posix())
        directory.component=component
        directory.keyfiles[file.name]=key_id
        add_data(db,'Component',[(component,guid('file:'+relative.as_posix()),directory.logical,256,None,key_id)])
        add_data(db,'FeatureComponents',[(feature.id,component)])
        version = None
        if file.suffix.lower() in {".exe", ".dll", ".sys"}:
            try:
                import win32api
                v = win32api.GetFileVersionInfo(str(file), "\\")
                version = ".".join(str(n) for n in ((v["FileVersionMS"] >> 16) & 65535, v["FileVersionMS"] & 65535, (v["FileVersionLS"] >> 16) & 65535, v["FileVersionLS"] & 65535))
            except Exception: pass
        file_id=directory.add_file(file.name, version=version)
        if relative.as_posix() == 'SadnessUpdater.exe':updater_file=file_id
        if relative.as_posix() == "SadnessVPN.exe": launcher_component = component
    add_data(db, "Directory", [("DesktopFolder", "TARGETDIR", "."), ("ProgramMenuFolder", "TARGETDIR", "."),
                                ("AppMenu", "ProgramMenuFolder", "SADNES~1|Sadness VPN")])
    add_data(db, "Shortcut", [("DesktopShortcut", "DesktopFolder", "SADNES~1|Sadness VPN", launcher_component, "[INSTALLDIR]SadnessVPN.exe", None, "Sadness VPN", None, "AppIcon", 0, 1, "INSTALLDIR"),
                              ("MenuShortcut", "AppMenu", "SADNES~1|Sadness VPN", launcher_component, "[INSTALLDIR]SadnessVPN.exe", None, "Sadness VPN", None, "AppIcon", 0, 1, "INSTALLDIR"),
                              ("DiagnosticsShortcut", "AppMenu", "DIAGNO~1|Diagnostics", launcher_component, "[INSTALLDIR]SadnessVPN.exe", "--diagnostics", "Check files and open startup logs", None, "AppIcon", 0, 1, "INSTALLDIR")])
    add_data(db, "RemoveFile", [("RemoveAppMenu", launcher_component, None, "AppMenu", 2)])
    # A minor MSI upgrade does not remove obsolete files automatically.
    # Remove only the retired bundled executable, never another Xray installation.
    legacy_bin = directories[Path('runtime/_internal/bin')].logical
    add_data(db, "RemoveFile",
             [("RemoveLegacyXray", launcher_component, "xray.exe", legacy_bin, 1)]
             + stale_electron_removals(db, directories, launcher_component))
    # Commit action: cache the exact administrator-approved offline setup source.
    # Установка поверх прежней версии — это тоже REINSTALL (малое обновление),
    # поэтому без патчей и удаления пакет сохраняется всегда: иначе встроенному
    # обновлению нечем откатить следующую версию.
    add_data(db,'CustomAction',[('CacheRecoveryMsi',3602,updater_file,'--cache-installed "[OriginalDatabase]"')])
    add_data(db,'InstallExecuteSequence',[('CacheRecoveryMsi','NOT REMOVE AND NOT PATCH',6500)])
    # Полное удаление снимает то, что приложение создало вне каталога установки:
    # задачу автозапуска и службу туннеля AmneziaWG. Deferred + no-impersonate
    # (1024+2048), результат игнорируется (64): удаление не должно срываться из-за
    # уже отсутствующей задачи. До RemoveFiles (3500), пока updater ещё на месте.
    # Откат updater'а (msiexec /x с SADNESS_ROLLBACK=1) настройки пользователя сохраняет.
    add_data(db,'CustomAction',[('UninstallCleanup',3154,updater_file,'--uninstall-cleanup')])
    add_data(db,'InstallExecuteSequence',[('UninstallCleanup',
        'REMOVE~="ALL" AND NOT UPGRADINGPRODUCTCODE AND NOT SADNESS_ROLLBACK',1600)])
    add_ui(db)
    add_data(db, "InstallUISequence", [("WelcomeDlg", "NOT Installed", 1230),
        ("UpdateDlg", "Installed AND PATCH AND NOT REMOVE", 1232),
        ("MaintenanceDlg", "Installed AND NOT PATCH AND NOT RESUME AND NOT REMOVE AND NOT REINSTALL", 1235), ("ProgressDlg", None, 1280)])
    db.Commit()
    validate = db.OpenView("SELECT * FROM `File`")
    validate.Execute(None)
    while row := validate.Fetch():
        validate.Modify(msilib.MSIMODIFY_VALIDATE, row)
    validate.Close()
    print("Building embedded cabinet: " + str(len(files)) + " files", flush=True)
    cab.commit(db)
    db.Commit()
    print(json.dumps({"msi": str(output), "bytes": output.stat().st_size, "files": len(files), "productCode": guid("product:"+PRODUCT_BASE_VERSION)}), flush=True)


if __name__ == "__main__":
    main()
