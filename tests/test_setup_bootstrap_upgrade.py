"""Setup.exe обновляет уже установленный продукт по правилам secure repair.

Windows Installer проводит minor upgrade через secure repair, а тот берёт пакет
только из каталога, доступного на запись исключительно администраторам, и только
под именем из SourceList\\PackageName. Распаковка в %TEMP% под собственным именем
обоих условий не выполняла, и обновление поверх 3.0.4–3.0.8 падало с 1603.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOOTSTRAP = ROOT / "installer" / "SetupBootstrap.cs"
UPDATER = ROOT / "installer" / "updater_main.py"


class SetupBootstrapUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.source = BOOTSTRAP.read_text(encoding="utf-8")

    def test_upgrade_stages_the_package_under_the_registered_name(self):
        self.assertIn("MsiSourceListGetInfoW", self.source)
        self.assertIn('"PackageName"', self.source)
        self.assertIn("RegisteredPackageName()", self.source)

    def test_registered_name_is_validated_before_use(self):
        self.assertIn('name.Contains("..")', self.source)
        self.assertRegex(self.source, r'Regex\.IsMatch\(name,\s*@"\^\[A-Za-z0-9\]')

    def test_upgrade_directory_is_admin_only_and_matches_the_updater(self):
        dacl = re.search(r'ProtectedDacl = "([^"]+)"', self.source)
        self.assertIsNotNone(dacl)
        self.assertIn("(A;OICI;FA;;;SY)", dacl.group(1))
        self.assertIn("(A;OICI;FA;;;BA)", dacl.group(1))
        self.assertIn("P", dacl.group(1).split(":")[1][:2])
        # Тот же приём и тот же корневой каталог, что у встроенного апдейтера.
        self.assertIn("SadnessVPN-Update", self.source)
        self.assertIn("SadnessVPN-Update", UPDATER.read_text(encoding="utf-8"))

    def test_upgrade_does_not_stage_into_a_user_writable_temp_directory(self):
        upgrade = self.source.split("private static int RunUpgrade()")[1].split("private static int RunInstaller")[0]
        self.assertNotIn("GetTempPath", upgrade)
        self.assertIn("CreateProtectedDirectory()", upgrade)
        self.assertIn("REINSTALL=ALL REINSTALLMODE=vomus", upgrade)

    def test_reinstall_is_never_used_for_a_clean_install(self):
        plain = self.source.split("private static int RunPlainInstall")[1].split("private static int RunUpgrade")[0]
        self.assertNotIn("REINSTALL", plain)
        self.assertIn("GetTempPath", plain)

    def test_verify_neither_elevates_nor_installs(self):
        main = self.source.split("private static int Main")[1].split("private static int RunPlainInstall")[0]
        self.assertIn('verifyOnly = args.Length == 1 && args[0] == "--verify"', main)
        self.assertIn("!verifyOnly && MsiQueryProductState", main)
        plain = self.source.split("private static int RunPlainInstall")[1].split("private static int RunUpgrade")[0]
        self.assertIn("if (verifyOnly) return 0;", plain)

    def test_elevation_happens_once_before_staging(self):
        self.assertIn("ElevatedUpgradeFlag", self.source)
        self.assertIn("WindowsBuiltInRole.Administrator", self.source)
        # Уже поднятый экземпляр не должен запрашивать runas второй раз.
        upgrade = self.source.split("private static int RunUpgrade()")[1].split("private static int RunInstaller")[0]
        self.assertIn('REINSTALL=ALL REINSTALLMODE=vomus", false)', upgrade)
        self.assertIn('if (elevate) start.Verb = "runas";', self.source)

    def test_cancelled_elevation_is_reported_as_1223(self):
        self.assertIn("NativeErrorCode == 1223", self.source)

    def test_staging_directory_is_always_removed(self):
        self.assertEqual(self.source.count("Directory.Delete(directory, true)"), 2)


if __name__ == "__main__":
    unittest.main()
