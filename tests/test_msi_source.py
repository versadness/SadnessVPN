import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from installer.msi_source import stage_minor_msi, validate_name


class MsiSourceTests(unittest.TestCase):
    def test_rejects_paths_and_arguments(self):
        for value in ['../setup.msi', 'C:\\setup.msi', 'setup.msi /quiet', '..msi', 'a:b.msi']:
            with self.assertRaises(ValueError):validate_name(value)

    def test_stages_verified_bytes_under_registered_name(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'new.msi';source.write_bytes(b'new MSI')
            package=dict(size=7,sha256=hashlib.sha256(b'new MSI').hexdigest())
            with patch('installer.msi_source.registered_package_name',return_value='original.msi'):
                target=stage_minor_msi(source,root,package)
                self.assertEqual(target.name,'original.msi')
                self.assertEqual(target.read_bytes(),source.read_bytes())
                target.write_bytes(b'corrupt')
                with self.assertRaises(ValueError):stage_minor_msi(source,root,package)
