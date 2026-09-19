import unittest
from pathlib import Path


class LauncherVersionTests(unittest.TestCase):
    def test_log_uses_assembly_version(self):
        source = (Path(__file__).resolve().parents[1] / 'installer' / 'Launcher.cs').read_text(encoding='utf-8')
        self.assertIn('Assembly.GetExecutingAssembly().GetName().Version.ToString(3)', source)
        self.assertNotIn('Launcher 2.0.24 started', source)


if __name__ == '__main__':
    unittest.main()
