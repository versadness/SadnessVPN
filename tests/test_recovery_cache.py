import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from installer.recovery_cache import cache_full,recovery_package


class RecoveryCacheTests(unittest.TestCase):
    def test_seed_restore_and_tamper(self):
        with tempfile.TemporaryDirectory() as d,patch('installer.recovery_cache.msi_identity',return_value='2.0.20'):
            root=Path(d);source=root/'setup.msi';source.write_bytes(b'offline msi')
            cache=root/'protected';cache.mkdir()
            target=cache_full(source,cache,'2.0.20')
            self.assertEqual(recovery_package(cache,'2.0.20'),target)
            target.write_bytes(b'changed msi')
            with self.assertRaises(ValueError):recovery_package(cache,'2.0.20')

    def test_wrong_version_never_creates_receipt(self):
        with tempfile.TemporaryDirectory() as d,patch('installer.recovery_cache.msi_identity',return_value='2.0.19'):
            root=Path(d);source=root/'setup.msi';source.write_bytes(b'msi')
            with self.assertRaises(ValueError):cache_full(source,root,'2.0.20')
            self.assertFalse((root/'recovery-2.0.20.json').exists())
