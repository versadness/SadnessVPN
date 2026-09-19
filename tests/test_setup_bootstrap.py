import unittest
from pathlib import Path


class SetupBootstrapTests(unittest.TestCase):
    def test_bootstrap_verifies_embedded_msi(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / 'installer' / 'SetupBootstrap.cs').read_text(encoding='utf-8')
        self.assertIn('ExpectedSha256', source)
        self.assertIn('ExtractAndVerify', source)
        self.assertIn('REINSTALLMODE=vomus', source)
        self.assertIn('Verb = "runas"', source)


if __name__ == '__main__':
    unittest.main()
