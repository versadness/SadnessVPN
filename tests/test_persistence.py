import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine import apps, storage
from engine.json_store import atomic_write_json


class AtomicJsonTests(unittest.TestCase):
    def test_replace_failure_preserves_original_and_removes_temporary_file(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root, "settings.json")
            path.write_text('{"old": true}', encoding="utf-8")

            with (
                mock.patch("engine.json_store.os.replace", side_effect=OSError("busy")),
                self.assertRaises(OSError),
            ):
                atomic_write_json(str(path), {"new": True})

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"old": True})
            self.assertEqual(list(Path(root).glob("*.tmp")), [])

    def test_server_save_keeps_previous_valid_version_as_backup(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root, "servers.json")
            old = [{"id": "old", "servers": []}]
            new = [{"id": "new", "servers": []}]
            path.write_text(json.dumps(old), encoding="utf-8")

            with mock.patch.object(storage, "_SERVERS_PATH", str(path)):
                storage.save_groups(new)

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), new)
            self.assertEqual(json.loads(Path(str(path) + ".bak").read_text(encoding="utf-8")), old)

    def test_server_load_recovers_from_valid_backup(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root, "servers.json")
            expected = [{"id": "backup", "name": "Backup", "servers": []}]
            path.write_text("not json", encoding="utf-8")
            Path(str(path) + ".bak").write_text(json.dumps(expected), encoding="utf-8")

            with mock.patch.object(storage, "_SERVERS_PATH", str(path)):
                self.assertEqual(storage.load_groups(), expected)


class AppDefaultsTests(unittest.TestCase):
    def test_missing_app_files_return_independent_default_lists(self):
        with tempfile.TemporaryDirectory() as root:
            missing = str(Path(root, "missing.json"))
            with mock.patch.object(apps, "_APPS_PATH", missing):
                first = apps.load_apps()
                first["apps"].append({"exe": "test.exe"})
                second = apps.load_apps()

        self.assertEqual(second, {"mode": "all", "apps": []})


if __name__ == "__main__":
    unittest.main()
