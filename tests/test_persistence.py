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


class RoutingAndWireGuardBackupTests(unittest.TestCase):
    def test_routing_rules_survive_a_corrupted_file(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root, "apps.json")
            with mock.patch.object(apps, "_APPS_PATH", str(path)):
                apps.save_apps({"mode": "whitelist", "apps": [{"exe": "a.exe"}], "rules": []})
                apps.save_apps({"mode": "whitelist", "apps": [{"exe": "b.exe"}], "rules": []})
                path.write_text("{broken", encoding="utf-8")
                self.assertEqual(apps.load_apps()["apps"], [{"exe": "a.exe"}])

    def test_wireguard_groups_survive_a_corrupted_file(self):
        from engine import wg_storage
        with tempfile.TemporaryDirectory() as root:
            path = Path(root, "wg_servers.json")
            groups = [{"id": "manual-wg", "name": "Вручную", "servers": []}]
            with mock.patch.object(wg_storage, "_WG_PATH", str(path)):
                wg_storage.save_wg_groups(groups)
                wg_storage.save_wg_groups(groups + [{"id": "x", "name": "X", "servers": []}])
                path.write_text("not json", encoding="utf-8")
                self.assertEqual(wg_storage.load_wg_groups(), groups)


class SettingsRecoveryTests(unittest.TestCase):
    """Повреждённый settings.json не должен стоить пользователю HWID и профиля."""

    def paths(self, root):
        from ui import app_state
        path = Path(root, "settings.json")
        return app_state, path, mock.patch.multiple(
            app_state, SETTINGS_PATH=str(path), SETTINGS_BAK_PATH=str(path) + ".bak")

    def test_save_keeps_previous_valid_version_as_backup(self):
        with tempfile.TemporaryDirectory() as root:
            app_state, path, patched = self.paths(root)
            with patched:
                self.assertTrue(app_state.save_settings({"hwid": "svpn-old"}))
                self.assertTrue(app_state.save_settings({"hwid": "svpn-new"}))
            self.assertEqual(json.loads(Path(str(path) + ".bak").read_text(encoding="utf-8")),
                             {"hwid": "svpn-old"})

    def test_corrupted_file_falls_back_to_backup_and_is_kept_aside(self):
        with tempfile.TemporaryDirectory() as root:
            app_state, path, patched = self.paths(root)
            path.write_text('{"hwid": "svpn-', encoding="utf-8")
            Path(str(path) + ".bak").write_text(
                json.dumps({"hwid": "svpn-backup", "dns_preset": "quad9"}), encoding="utf-8")
            with patched:
                settings = app_state.load_settings()
            self.assertEqual(settings["hwid"], "svpn-backup")
            self.assertEqual(settings["dns_preset"], "quad9")
            self.assertEqual(Path(str(path) + ".corrupt").read_text(encoding="utf-8"), '{"hwid": "svpn-')
            self.assertFalse(path.exists())

    def test_missing_file_gives_defaults(self):
        with tempfile.TemporaryDirectory() as root:
            app_state, _path, patched = self.paths(root)
            with patched:
                self.assertEqual(app_state.load_settings()["hwid"], "")

    def test_normalization_failure_keeps_hwid(self):
        with tempfile.TemporaryDirectory() as root:
            app_state, path, patched = self.paths(root)
            path.write_text(json.dumps({"hwid": "svpn-keep", "dns_preset": "cf_google"}), encoding="utf-8")
            with patched, mock.patch.object(app_state.game_filter, "normalize_stored",
                                            side_effect=RuntimeError("bug")):
                settings = app_state.load_settings()
            self.assertEqual(settings["hwid"], "svpn-keep")


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
