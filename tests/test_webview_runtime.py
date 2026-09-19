import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

from engine.webview_runtime import prepare_webview_runtime, validate_webview_runtime


class FixedRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'bin' / 'webview2'
        self.root.mkdir(parents=True)
        for name in ['msedgewebview2.exe','msedge.dll','icudtl.dat','resources.pak','locales/en-US.pak']:
            target = self.root / name
            target.parent.mkdir(exist_ok=True)
            target.touch()
        self.pe = patch('engine.webview_runtime.read_pe_machine', return_value=0x8664)
        self.pe.start();self.addCleanup(self.pe.stop)

    def test_full_build_pins_bundled_folder(self):
        settings={}
        with patch('engine.webview_runtime.subprocess.run') as run:
            root=prepare_webview_runtime(self.base,settings,frozen=True,windows_build=26200)
        self.assertEqual(settings['WEBVIEW2_RUNTIME_PATH'],str(self.root.resolve()))
        self.assertEqual(root,self.root.resolve());run.assert_not_called()

    def test_frozen_missing_bundle_is_actionable_not_silent_system_fallback(self):
        (self.root/'msedge.dll').unlink()
        with self.assertRaisesRegex(RuntimeError,'msedge.dll.*установщик'):
            prepare_webview_runtime(self.base,{},frozen=True,windows_build=26200)

    def test_dev_without_bundle_keeps_system_option(self):
        self.assertIsNone(prepare_webview_runtime(self.base/'source',{},frozen=False))

    def test_wrong_architecture_rejected(self):
        with patch('engine.webview_runtime.read_pe_machine',return_value=0x14c):
            with self.assertRaisesRegex(RuntimeError,'x64'):
                validate_webview_runtime(self.root)

    def test_missing_locales_rejected(self):
        (self.root/'locales/en-US.pak').unlink()
        with self.assertRaisesRegex(RuntimeError,'языковые ресурсы'):
            validate_webview_runtime(self.root)

    def test_win10_only_grants_read_execute_to_runtime(self):
        with patch('engine.webview_runtime.subprocess.run',return_value=Mock(returncode=0)) as run:
            prepare_webview_runtime(self.base,{},frozen=True,windows_build=19045)
        args=run.call_args.args[0]
        self.assertEqual(args[1],str(self.root.resolve()))
        self.assertEqual(args[2:],['/grant','*S-1-15-2-2:(OI)(CI)(RX)','*S-1-15-2-1:(OI)(CI)(RX)'])
        self.assertNotIn('/T',args)

    def test_acl_failure_does_not_disable_sandbox(self):
        settings={}
        with patch('engine.webview_runtime.subprocess.run',return_value=Mock(returncode=5)):
            with self.assertRaisesRegex(RuntimeError,'доступ'):
                prepare_webview_runtime(self.base,settings,frozen=True,windows_build=19045)
        self.assertNotIn('WEBVIEW2_RUNTIME_PATH',settings)


if __name__ == '__main__':
    unittest.main()
