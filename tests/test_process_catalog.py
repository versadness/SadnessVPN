import unittest
from types import SimpleNamespace
from unittest.mock import patch
from engine.process_catalog import process_catalog,process_icon


class ProcessCatalogTests(unittest.TestCase):
    def test_catalog_deduplicates_and_exposes_only_names(self):
        processes=[SimpleNamespace(info=dict(name=n,exe='C:/Private/'+n)) for n in ['Telegram.exe','Telegram.exe','svchost.exe','test.exe']]
        with patch('psutil.process_iter',return_value=processes) as iterator:
            result=process_catalog()
        self.assertEqual(len(result),2)
        self.assertTrue(all(set(r)=={'exe','name'} for r in result))
        self.assertNotIn('Private',str(result))
        iterator.assert_called_once_with(['name'])

    def test_icon_rejects_paths_and_system_processes(self):
        with patch('psutil.process_iter') as iterator:
            for name in ['../secret.exe',r'C:\Private\a.exe','svchost.exe',None,'not-executable']:
                self.assertIsNone(process_icon(name))
            iterator.assert_not_called()
