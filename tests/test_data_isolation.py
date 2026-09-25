"""Тесты не должны писать в профиль разработчика ./data."""
import os
import unittest
from pathlib import Path

from engine.paths import data_dir

PROJECT_DATA = Path(__file__).resolve().parent.parent / "data"


class DataIsolationTests(unittest.TestCase):
    def test_tests_use_a_temporary_data_directory(self):
        self.assertNotEqual(Path(data_dir()).resolve(), PROJECT_DATA.resolve())
        self.assertEqual(Path(data_dir()).resolve(), Path(os.environ["SADNESS_DATA_DIR"]).resolve())

    def test_settings_and_journal_live_in_that_directory(self):
        from engine import diagnostics
        from ui import app_state
        for path in (app_state.SETTINGS_PATH, diagnostics.log_path):
            self.assertTrue(Path(path).resolve().is_relative_to(Path(data_dir()).resolve()), path)


if __name__ == "__main__":
    unittest.main()
