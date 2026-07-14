import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine.paths import _frozen_data_dir, _migrate_legacy_data, data_dir


class FrozenDataPathTests(unittest.TestCase):
    def test_frozen_data_uses_local_appdata(self):
        path = _frozen_data_dir({"LOCALAPPDATA": r"C:\Users\Test\AppData\Local"})

        self.assertEqual(
            path,
            r"C:\Users\Test\AppData\Local\SadnessVPN\data",
        )

    def test_data_dir_migrates_frozen_legacy_data(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            meipass = root_path.joinpath("bundle")
            legacy = meipass.joinpath("data")
            local_appdata = root_path.joinpath("local")
            legacy.mkdir(parents=True)
            legacy.joinpath("settings.json").write_text("{}", encoding="utf-8")

            with (
                mock.patch("engine.paths.sys.frozen", True, create=True),
                mock.patch("engine.paths.sys._MEIPASS", str(meipass), create=True),
                mock.patch.dict(os.environ, {"LOCALAPPDATA": str(local_appdata)}),
            ):
                result = Path(data_dir())

            self.assertEqual(result, local_appdata.joinpath("SadnessVPN", "data"))
            self.assertTrue(result.joinpath("settings.json").is_file())


class LegacyDataMigrationTests(unittest.TestCase):
    def test_migration_copies_known_files_only(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root, "old-data")
            target = Path(root, "new-data")
            source.mkdir()
            target.mkdir()
            source.joinpath("settings.json").write_text('{"startup": false}', encoding="utf-8")
            source.joinpath("unknown.txt").write_text("do not copy", encoding="utf-8")

            copied = _migrate_legacy_data(str(target), [str(source)])

            self.assertEqual(copied, ["settings.json"])
            self.assertTrue(target.joinpath("settings.json").is_file())
            self.assertFalse(target.joinpath("unknown.txt").exists())

    def test_migration_never_overwrites_existing_file(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root, "old-data")
            target = Path(root, "new-data")
            source.mkdir()
            target.mkdir()
            source.joinpath("settings.json").write_text("old", encoding="utf-8")
            target.joinpath("settings.json").write_text("current", encoding="utf-8")

            copied = _migrate_legacy_data(str(target), [str(source)])

            self.assertEqual(copied, [])
            self.assertEqual(
                target.joinpath("settings.json").read_text(encoding="utf-8"),
                "current",
            )

    def test_migration_marker_prevents_reimport(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root, "old-data")
            target = Path(root, "new-data")
            source.mkdir()
            target.mkdir()
            source.joinpath("apps.json").write_text("{}", encoding="utf-8")

            first = _migrate_legacy_data(str(target), [str(source)])
            target.joinpath("apps.json").unlink()
            second = _migrate_legacy_data(str(target), [str(source)])

            self.assertEqual(first, ["apps.json"])
            self.assertEqual(second, [])
            self.assertFalse(target.joinpath("apps.json").exists())


class PackagingSafetyTests(unittest.TestCase):
    def test_spec_does_not_bundle_runtime_data(self):
        project_root = Path(__file__).resolve().parents[1]
        spec = project_root.joinpath("SadnessVPN.spec").read_text(encoding="utf-8")

        self.assertNotIn("Tree('data'", spec)
        self.assertNotIn('Tree("data"', spec)

    def test_spec_validates_runtime_architecture(self):
        project_root = Path(__file__).resolve().parents[1]
        spec = project_root.joinpath("SadnessVPN.spec").read_text(encoding="utf-8")

        self.assertIn("validate_runtime_binaries", spec)

    def test_spec_excludes_runtime_backups(self):
        project_root = Path(__file__).resolve().parents[1]
        spec = project_root.joinpath("SadnessVPN.spec").read_text(encoding="utf-8")

        self.assertIn("excludes=['backups']", spec)


if __name__ == "__main__":
    unittest.main()
