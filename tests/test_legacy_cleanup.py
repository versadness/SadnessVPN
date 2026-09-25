"""Обновление не должно оставлять бинарники удалённого ядра.

И при этом не должно трогать ничего, кроме известных файлов самого приложения
внутри его каталога: ни пользовательских данных, ни чужих установок.
"""
import os
import unittest
from pathlib import Path
import tempfile
from unittest import mock

from engine import legacy_cleanup


class ObsoleteFileRemovalTests(unittest.TestCase):
    def _bin(self, root):
        return mock.patch("engine.legacy_cleanup.bin_path",
                          side_effect=lambda name: str(Path(root, name)))

    def test_the_removed_core_binary_is_deleted(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "mihomo.exe").write_bytes(b"core")
            Path(root, "sing-box.exe").write_bytes(b"obsolete")

            with self._bin(root):
                removed = legacy_cleanup.remove_obsolete_files()

            self.assertIn("sing-box.exe", removed)
            self.assertFalse(Path(root, "sing-box.exe").exists())
            self.assertTrue(Path(root, "mihomo.exe").exists())

    def test_the_obsolete_licence_of_a_removed_component_is_deleted(self):
        with tempfile.TemporaryDirectory() as root:
            licenses = Path(root, "licenses")
            licenses.mkdir()
            licenses.joinpath("xray-MPL-2.0.txt").write_text("old", encoding="utf-8")
            licenses.joinpath("mihomo-GPL-3.0.txt").write_text("keep", encoding="utf-8")

            with self._bin(root):
                removed = legacy_cleanup.remove_obsolete_files()

            self.assertIn("xray-MPL-2.0.txt", removed)
            self.assertTrue(licenses.joinpath("mihomo-GPL-3.0.txt").exists())

    def test_nothing_outside_the_known_list_is_touched(self):
        with tempfile.TemporaryDirectory() as root:
            for name in ("mihomo.exe", "winws.exe", "wintun.dll", "servers.json",
                         "settings.json", "someone-elses.exe"):
                Path(root, name).write_bytes(b"x")

            with self._bin(root):
                removed = legacy_cleanup.remove_obsolete_files()

            self.assertEqual(removed, [])
            for name in os.listdir(root):
                self.assertTrue(Path(root, name).exists(), name)

    def test_running_twice_is_safe(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "sing-box.exe").write_bytes(b"obsolete")
            with self._bin(root):
                first = legacy_cleanup.remove_obsolete_files()
                second = legacy_cleanup.remove_obsolete_files()

            self.assertEqual(first, ["sing-box.exe"])
            self.assertEqual(second, [])

    def test_a_locked_file_is_reported_but_does_not_break_startup(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "sing-box.exe").write_bytes(b"obsolete")

            with self._bin(root), \
                    mock.patch("engine.legacy_cleanup.os.remove", side_effect=OSError("in use")), \
                    mock.patch("engine.legacy_cleanup.journal") as journal:
                removed = legacy_cleanup.remove_obsolete_files()

            self.assertEqual(removed, [])
            journal.warning.assert_called()

    def test_a_missing_directory_is_not_an_error(self):
        with self._bin(os.path.join(tempfile.gettempdir(), "sadness-does-not-exist")):
            self.assertEqual(legacy_cleanup.remove_obsolete_files(), [])


class PackagingTests(unittest.TestCase):
    def test_the_build_spec_excludes_the_removed_core(self):
        spec = (Path(__file__).resolve().parents[1] / "SadnessVPN.spec").read_text(encoding="utf-8")
        self.assertIn("sing-box.exe", spec)
        self.assertIn("excludes", spec)

    def test_the_repository_no_longer_carries_the_removed_core(self):
        root = Path(__file__).resolve().parents[1]
        self.assertFalse((root / "bin" / "sing-box.exe").exists())
        self.assertFalse((root / "engine" / "singbox.py").exists())

    def test_the_launcher_no_longer_requires_the_removed_core(self):
        launcher = (Path(__file__).resolve().parents[1]
                    / "installer" / "Launcher.cs").read_text(encoding="utf-8-sig")
        self.assertNotIn("sing-box.exe", launcher)
        self.assertIn("bin/mihomo.exe", launcher)

    def test_no_source_file_still_imports_the_removed_core(self):
        root = Path(__file__).resolve().parents[1]
        offenders = []
        for folder in ("engine", "ui", "tools", "tests"):
            for path in (root / folder).rglob("*.py"):
                if path.name == Path(__file__).name:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                # Упоминание в комментарии допустимо; запрещены импорт и вызов.
                forbidden = ("import engine.singbox", "from engine.singbox",
                             "SingBoxManager(")
                if any(item in text for item in forbidden):
                    offenders.append(str(path.relative_to(root)))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
