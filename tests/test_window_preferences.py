import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from engine.window_preferences import load_maximized,save_maximized


class WindowPreferenceTests(unittest.TestCase):
    def test_default_roundtrip_and_invalid(self):
        with tempfile.TemporaryDirectory() as folder,patch('engine.window_preferences.data_dir',return_value=folder):
            self.assertFalse(load_maximized())
            save_maximized(True);self.assertTrue(load_maximized())
            save_maximized(False);self.assertFalse(load_maximized())
            (Path(folder)/'window-state.json').write_text('{broken')
            self.assertFalse(load_maximized())
