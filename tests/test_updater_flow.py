"""Exercise the helper state machine with signed metadata and simulated MSI/HTTP."""
import base64
import io
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock,patch
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
from engine.update_manifest import canonical
from installer import updater_main as updater


class UpdaterFlowTests(unittest.TestCase):
    def run_case(self,ready=True,signature=True):
        with tempfile.TemporaryDirectory() as d,ExitStack() as stack:
            root=Path(d);local=root/'local';protected=root/'protected';protected.mkdir()
            directory=local/'SadnessVPN/data/updates';directory.mkdir(parents=True)
            key=Ed25519PrivateKey.generate();public=base64.b64encode(key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)).decode()
            package=dict(url='https://updates.test/releases/2.0.21/setup.msi',sha256='a'*64,size=3)
            data=dict(schema=1,product='Sadness VPN',channel='beta',version='2.0.21',full=package,patches={})
            data['signature']=base64.b64encode(key.sign(canonical(data))).decode() if signature else 'invalid'
            (directory/'manifest.json').write_text(json.dumps(data))
            (directory/('a'*64+'.msi')).write_bytes(b'msi')
            old=protected/'old.msi';old.write_bytes(b'old')
            stack.enter_context(patch.dict('os.environ',{'ProgramFiles':str(root),'LOCALAPPDATA':str(local)}))
            stack.enter_context(patch.object(updater.sys,'argv',['updater']))
            stack.enter_context(patch.object(updater.policy,'PUBLIC_KEY_BASE64',public))
            stack.enter_context(patch.object(updater.policy,'ALLOWED_HOSTS',['updates.test']))
            kernel=Mock();kernel.CreateMutexW.return_value=123
            stack.enter_context(patch.object(updater.ctypes,'WinDLL',return_value=kernel))
            stack.enter_context(patch.object(updater.ctypes,'get_last_error',return_value=0))
            stack.enter_context(patch.object(updater.ctypes.windll.shell32,'IsUserAnAdmin',return_value=1))
            stack.enter_context(patch.object(updater,'protected_directory',return_value=protected))
            stack.enter_context(patch.object(updater,'verify_file'))
            stack.enter_context(patch.object(updater,'cache_full'))
            stack.enter_context(patch.object(updater,'stage_minor_msi',side_effect=lambda source,*_:source))
            recovery=stack.enter_context(patch.object(updater,'recovery_package',return_value=old))
            stack.enter_context(patch('psutil.process_iter',return_value=[]))
            stack.enter_context(patch.object(updater,'installed_version',side_effect=['2.0.19','2.0.21','2.0.19']))
            execute=stack.enter_context(patch.object(updater.subprocess,'run',return_value=Mock(returncode=0)))
            stack.enter_context(patch.object(updater.subprocess,'Popen'))
            stack.enter_context(patch.object(updater.time,'sleep'))
            def response(*args,**kwargs):return io.BytesIO(json.dumps(dict(version='2.0.21',ui_ready=ready)).encode())
            stack.enter_context(patch.object(updater.urllib.request,'urlopen',side_effect=response))
            code=updater.main()
            result=json.loads((protected/'result.json').read_text())
            return code,result,execute.call_args_list,recovery.call_count

    def test_success_requires_ready_signal(self):
        code,result,commands,_=self.run_case()
        self.assertEqual(code,0);self.assertTrue(result['ok']);self.assertEqual(len(commands),1)

    def test_no_ready_restores_exact_previous_package(self):
        code,result,commands,count=self.run_case(ready=False)
        self.assertEqual(code,2);self.assertFalse(result['ok']);self.assertEqual(len(commands),3)
        self.assertIn('/x',commands[1].args[0]);self.assertIn('/i',commands[2].args[0]);self.assertEqual(count,1)
        # Удаление при откате помечено: задача автозапуска и служба не снимаются.
        self.assertIn('SADNESS_ROLLBACK=1',commands[1].args[0])

    def test_bad_signature_never_starts_installer(self):
        code,result,commands,count=self.run_case(signature=False)
        self.assertEqual(code,1);self.assertFalse(result['ok']);self.assertEqual(commands,[]);self.assertEqual(count,0)


class UninstallCleanupTests(unittest.TestCase):
    def test_removes_only_the_apps_own_task_and_tunnel_service(self):
        with tempfile.TemporaryDirectory() as d:
            manager=Path(d,'runtime','_internal','bin','amneziawg','amneziawg.exe')
            manager.parent.mkdir(parents=True);manager.write_bytes(b'MZ')
            run=Mock(return_value=Mock(returncode=0))
            updater.uninstall_cleanup(d,run=run)
        commands=[call.args[0] for call in run.call_args_list]
        self.assertIn(['schtasks.exe','/Delete','/F','/TN','SadnessVPN'],commands)
        self.assertIn([str(manager),'/uninstalltunnelservice','SadnessVPN'],commands)
        self.assertIn(['sc.exe','delete','AmneziaWGTunnel$SadnessVPN'],commands)

    def test_msi_runs_cleanup_only_on_real_removal(self):
        source=Path('installer/build_msi.py').read_text(encoding='utf-8')
        self.assertIn("'--uninstall-cleanup'",source)
        self.assertIn('REMOVE~="ALL" AND NOT UPGRADINGPRODUCTCODE AND NOT SADNESS_ROLLBACK',source)
