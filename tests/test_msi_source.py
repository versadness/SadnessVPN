import os
import hashlib
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from installer.msi_source import stage_minor_msi, validate_name


class MsiSourceTests(unittest.TestCase):
    def test_rejects_paths_and_arguments(self):
        for value in ['../setup.msi', 'C:\\setup.msi', 'setup.msi /quiet', '..msi', 'a:b.msi']:
            with self.assertRaises(ValueError):validate_name(value)

    def test_stages_verified_bytes_under_registered_name(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'new.msi';source.write_bytes(b'new MSI')
            package=dict(size=7,sha256=hashlib.sha256(b'new MSI').hexdigest())
            with patch('installer.msi_source.registered_package_name',return_value='original.msi'):
                target=stage_minor_msi(source,root,package)
                self.assertEqual(target.name,'original.msi')
                self.assertEqual(target.read_bytes(),source.read_bytes())
                target.write_bytes(b'corrupt')
                with self.assertRaises(ValueError):stage_minor_msi(source,root,package)


@unittest.skipUnless(os.name == "nt", "MSI собирается только в Windows")
class StaleElectronRemovalTests(unittest.TestCase):
    """3.0.6 выкинул из пакета Electron 62 МБ, которых msiexec сам не удалит."""

    def rows(self):
        from installer import build_msi
        koffi = build_msi._KOFFI
        directories = {
            Path("electron/locales"): SimpleNamespace(logical="D_LOCALES"),
            koffi: SimpleNamespace(logical="D_KOFFI"),
            koffi / "build" / "koffi": SimpleNamespace(logical="D_BUILDS"),
        }
        added = []
        with patch.object(build_msi, "add_data", lambda db, table, data: added.append((table, data))):
            rows = build_msi.stale_electron_removals(None, directories, "LAUNCHER")
        return rows, added

    def test_locales_are_cleared_by_mask_before_install_restores_the_kept_ones(self):
        rows, _ = self.rows()
        locales = [r for r in rows if r[0] == "RemoveStaleLocales"]
        self.assertEqual(locales, [("RemoveStaleLocales", "LAUNCHER", "*.pak", "D_LOCALES", 1)])

    def test_every_foreign_koffi_platform_is_removed_and_win32_x64_is_kept(self):
        from installer import build_msi
        rows, added = self.rows()
        names = [name for table, data in added if table == "Directory"
                 for _, _, default in data for name in [default.split("|")[-1]]]
        self.assertIn("darwin_arm64", names)
        self.assertNotIn("win32_x64", names)
        self.assertEqual(len([n for n in names if n in build_msi._STALE_KOFFI_PLATFORMS]),
                         len(build_msi._STALE_KOFFI_PLATFORMS))

    def test_each_stale_directory_gets_both_a_file_sweep_and_its_own_removal(self):
        rows, _ = self.rows()
        directory_rows = [r for r in rows if r[0] != "RemoveStaleLocales"]
        self.assertEqual({r[2] for r in directory_rows}, {None, "*"})
        # Один и тот же каталог не должен попасть в таблицу дважды.
        self.assertEqual(len({r[0] for r in directory_rows}), len(directory_rows))

    def test_short_names_stay_unique_inside_one_parent(self):
        from installer.build_msi import _short_name
        used = set()
        self.assertNotEqual(_short_name("linux_arm64", used), _short_name("linux_armhf", used))
