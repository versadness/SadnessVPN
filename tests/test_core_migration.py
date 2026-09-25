"""Миграция профиля на единственное ядро.

Требование жёсткое: настройки, подписки, серверы и правила сохраняются, выбор
удалённого ядра исчезает, профиль целиком не сбрасывается, а перед первым
изменением создаётся локальная резервная копия.
"""
import json
import unittest
from pathlib import Path
import tempfile
from unittest import mock

from ui import app_state

LEGACY = {
    "core": "singbox",
    "selected_group": "g",
    "selected_index": 3,
    "dns_preset": "adguard",
    "kill_switch": True,
    "socks": 1081,
    "favorite_servers": ["a", "b"],
    "zapret_strategy": "flowseal_alt3",
    "zapret_game_filter": {"mode": "both", "tcp_start": 27015, "tcp_end": 27030},
}


class CoreSettingMigrationTests(unittest.TestCase):
    def _load(self, stored, folder):
        settings_path = Path(folder, "settings.json")
        settings_path.write_text(json.dumps(stored), encoding="utf-8")
        backup_path = Path(folder, "settings.before-mihomo-migration.json")
        with mock.patch.object(app_state, "SETTINGS_PATH", str(settings_path)), \
                mock.patch.object(app_state, "SETTINGS_BACKUP_PATH", str(backup_path)):
            return app_state.load_settings(), backup_path

    def test_the_removed_core_setting_disappears_without_resetting_the_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            settings, _backup = self._load(LEGACY, folder)

        self.assertNotIn("core", settings)
        self.assertEqual(settings["selected_group"], "g")
        self.assertEqual(settings["selected_index"], 3)
        self.assertEqual(settings["dns_preset"], "adguard")
        self.assertTrue(settings["kill_switch"])
        self.assertEqual(settings["socks"], 1081)
        self.assertEqual(settings["favorite_servers"], ["a", "b"])
        self.assertEqual(settings["zapret_strategy"], "flowseal_alt3")

    def test_zapret_settings_migrate_instead_of_being_dropped(self):
        with tempfile.TemporaryDirectory() as folder:
            settings, _backup = self._load(LEGACY, folder)

        game_filter = settings["zapret_game_filter"]
        self.assertEqual(game_filter["scope"], "custom")
        self.assertEqual((game_filter["tcp_start"], game_filter["tcp_end"]), (27015, 27030))

    def test_the_migration_is_written_to_disk_not_only_to_memory(self):
        with tempfile.TemporaryDirectory() as folder:
            settings_path = Path(folder, "settings.json")
            settings, _backup = self._load(LEGACY, folder)

            stored = json.loads(settings_path.read_text(encoding="utf-8"))

        self.assertNotIn("core", stored)
        self.assertEqual(stored["selected_group"], "g")
        self.assertEqual(stored["dns_preset"], "adguard")
        self.assertNotIn("core", settings)
        # Нормализованные значения тоже доходят до диска, а не остаются
        # только в памяти до первой правки настроек.
        self.assertEqual(stored["zapret_game_filter"]["scope"], "custom")

    def test_a_backup_is_written_before_the_first_migration(self):
        with tempfile.TemporaryDirectory() as folder:
            _settings, backup = self._load(LEGACY, folder)

            self.assertTrue(backup.exists())
            saved = json.loads(backup.read_text(encoding="utf-8"))
            self.assertEqual(saved["core"], "singbox")

    def test_running_the_migration_again_keeps_the_original_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            self._load(LEGACY, folder)
            backup = Path(folder, "settings.before-mihomo-migration.json")
            original = backup.read_text(encoding="utf-8")

            # Второй запуск: профиль уже мигрирован, копия перезаписываться
            # не должна — иначе исходное состояние будет потеряно.
            self._load({**LEGACY, "core": "mihomo", "dns_preset": "quad9"}, folder)

            self.assertEqual(backup.read_text(encoding="utf-8"), original)

    def test_a_profile_without_the_removed_key_creates_no_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            settings, backup = self._load({"dns_preset": "quad9"}, folder)

        self.assertFalse(backup.exists())
        self.assertEqual(settings["dns_preset"], "quad9")

    def test_the_removed_setting_can_no_longer_be_set_through_the_api(self):
        with self.assertRaisesRegex(ValueError, "Mihomo"):
            app_state.normalize_tunnel_setting("core", "singbox")

    def test_the_removed_key_is_not_offered_as_a_tunnel_setting(self):
        self.assertNotIn("core", app_state.TUNNEL_KEYS)
        self.assertNotIn("core", app_state.DEFAULT_SETTINGS)


if __name__ == "__main__":
    unittest.main()
