import base64
import copy
import hashlib
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
from engine.update_manifest import canonical,verify,select_package,parse,version,verify_file,safe_url
from engine.updates import UpdateManager


class UpdateTests(unittest.TestCase):
    def test_explicit_port_is_pinned(self):
        hosts=['mygermany2.duckdns.org:8444']
        safe_url('https://mygermany2.duckdns.org:8444/updates/beta.json',hosts)
        for url in ['https://mygermany2.duckdns.org/updates/beta.json','https://mygermany2.duckdns.org:8443/a','https://evil.test:8444/a']:
            with self.assertRaises(ValueError):safe_url(url,hosts)

    def setUp(self):
        self.key=Ed25519PrivateKey.generate()
        self.public=base64.b64encode(self.key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)).decode()
        self.package=dict(url='https://updates.example.com/releases/2.0.20/setup.msi',size=3,sha256=hashlib.sha256(b'abc').hexdigest())
        self.data=dict(schema=1,product='Sadness VPN',version='2.0.20',channel='beta',notes=['Test'],full=self.package,patches={})

    def sign(self,data):
        result=copy.deepcopy(data);result['signature']=base64.b64encode(self.key.sign(canonical(result))).decode();return result

    def test_signature_tampering_and_wrong_key(self):
        signed=self.sign(self.data);verify(signed,self.public,['updates.example.com'],'beta')
        signed['version']='2.0.21'
        with self.assertRaises(ValueError):verify(signed,self.public,['updates.example.com'],'beta')

    def test_patch_only_requires_exact_base_and_downloads_no_msi(self):
        import io
        package={**self.package,'url':self.package['url'].replace('.msi','.msp')}
        data={**self.data,'distribution':'patch-only','patches':{'2.0.19':package}}
        data.pop('full');data=self.sign(data)
        verify(data,self.public,['updates.example.com'],'beta')
        self.assertEqual(select_package(data,'2.0.19'),package)
        self.assertIsNone(select_package(data,'2.0.18'))
        with tempfile.TemporaryDirectory() as directory:
            manager=UpdateManager(directory);manager.manifest=data;manager.package=package
            with patch('engine.updates.fetch',return_value=io.BytesIO(b'abc')) as fetch:
                manager._download()
            self.assertEqual(fetch.call_count,1)
            self.assertEqual(manager.state['status'],'ready')

    def test_patch_only_empty_or_backward_rejected(self):
        data={**self.data,'distribution':'patch-only','patches':{}};data.pop('full')
        with self.assertRaises(ValueError):verify(self.sign(data),self.public,['updates.example.com'],'beta')
        data['patches']={'2.0.21':{**self.package,'url':self.package['url'].replace('.msi','.msp')}}
        with self.assertRaises(ValueError):verify(self.sign(data),self.public,['updates.example.com'],'beta')

    def test_skipped_versions_select_direct_patch(self):
        data={'version':'2.0.25','distribution':'patch-only','patches':{
            '2.0.22':{'id':'22-to-25'},'2.0.23':{'id':'23-to-25'},'2.0.24':{'id':'24-to-25'}}}
        self.assertEqual(select_package(data,'2.0.22'),{'id':'22-to-25'})
        self.assertEqual(select_package(data,'2.0.24'),{'id':'24-to-25'})
        self.assertIsNone(select_package(data,'2.0.21'))
        self.assertIsNone(select_package(data,'2.0.25'))

    def test_signed_untrusted_url_and_channel(self):
        for url in ['http://updates.example.com/a.msi','https://attacker.example/a.msi','https://updates.example.com:444/a.msi','https://user@updates.example.com/a.msi','https://updates.example.com/../a.msi']:
            data=copy.deepcopy(self.data);data['full']['url']=url
            with self.assertRaises(ValueError):verify(self.sign(data),self.public,['updates.example.com'],'beta')
        with self.assertRaises(ValueError):verify(self.sign(self.data),self.public,['updates.example.com'],'stable')

    def test_precise_patch_selection_and_numeric_version(self):
        patch_package={**self.package,'url':self.package['url'].replace('.msi','.msp')}
        self.data['patches']={'2.0.19':patch_package}
        self.assertEqual(select_package(self.data,'2.0.19'),patch_package)
        self.assertEqual(select_package(self.data,'2.0.9'),self.package)
        self.assertIsNone(select_package(self.data,'2.0.21'))
        self.assertIsNone(select_package(self.data,'2.0.20'))

    def test_duplicate_fields_and_bad_versions(self):
        with self.assertRaises(ValueError):parse(b'{"version":"1","version":"2"}')
        for value in ['2.0.020','2.0.1.exe','256.0.0',None]:
            with self.assertRaises(ValueError):version(value)

    def test_payload_hash_and_size(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'a';p.write_bytes(b'abc');verify_file(p,self.package)
            p.write_bytes(b'xyz')
            with self.assertRaises(ValueError):verify_file(p,self.package)
            p.write_bytes(b'abcd')
            with self.assertRaises(ValueError):verify_file(p,self.package)

    def test_only_one_startup_check_manual_remains_available(self):
        manager=UpdateManager('unused')
        with patch('engine.updates.threading.Thread') as thread:
            manager.check(automatic=True);manager.change(status='current')
            manager.check(automatic=True)
            self.assertEqual(thread.call_count,1)
            manager.check();self.assertEqual(thread.call_count,2)

    def test_no_endpoint_has_explicit_state(self):
        manager=UpdateManager('unused')
        with patch('engine.updates.policy.MANIFEST_BASE',''):
            manager._check()
        self.assertEqual(manager.snapshot()['status'],'unconfigured')

    def test_failure_limit_persists_without_counting_client_restarts(self):
        from installer.updater_main import record_result
        with tempfile.TemporaryDirectory() as d, patch.dict('os.environ', {'ProgramData': d}):
            result = Path(d)/'SadnessVPN-Update'/'result.json'
            result.parent.mkdir()
            for count in range(1, 4):
                outcome = record_result(result, dict(ok=False, version='2.0.21', message='Test'))
                self.assertEqual(outcome['failure_count'], count)
            for _ in range(3):
                manager = UpdateManager(d)
                manager.change(status='available', available_version='2.0.21')
                self.assertTrue(manager.snapshot()['suppress_notice'])
                self.assertEqual(manager.snapshot()['last_update']['failure_count'], 3)
            manager.change(available_version='2.0.22')
            self.assertFalse(manager.snapshot()['suppress_notice'])
            record_result(result, dict(ok=True, version='2.0.21', message='Success'))
            manager.change(available_version='2.0.21')
            self.assertFalse(manager.snapshot()['suppress_notice'])
            self.assertEqual(manager.snapshot()['last_update']['failure_count'], 0)

    def test_failed_new_version_starts_its_own_counter(self):
        from installer.updater_main import record_result
        with tempfile.TemporaryDirectory() as d:
            result=Path(d)/'result.json'
            record_result(result, dict(ok=False,version='2.0.21'))
            outcome=record_result(result, dict(ok=False,version='2.0.22'))
            self.assertEqual(outcome['failure_count'],1)

    def test_cancelled_download_removes_partial_package(self):
        import io
        with tempfile.TemporaryDirectory() as d:
            manager=UpdateManager(d);manager.package=self.package;manager.manifest=self.sign(self.data)
            manager.cancel.set()
            with patch('engine.updates.fetch',return_value=io.BytesIO(b'abc')):
                manager._download()
            self.assertEqual(manager.snapshot()['status'],'cancelled')
            self.assertEqual(list(manager.directory.glob('*.download')),[])
            self.assertIsNone(manager.path)

    def test_bad_download_never_becomes_installable(self):
        import io
        with tempfile.TemporaryDirectory() as d:
            manager=UpdateManager(d);manager.package=self.package;manager.manifest=self.sign(self.data)
            with patch('engine.updates.fetch',return_value=io.BytesIO(b'xyz')):
                manager._download()
            self.assertEqual(manager.snapshot()['status'],'error')
            self.assertEqual(list(manager.directory.glob('*.download')),[])
            self.assertIsNone(manager.path)
            self.assertTrue(manager.snapshot()['can_download'])

    def test_new_check_discards_old_release_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            manager=UpdateManager(d)
            manager.package=self.package
            manager.change(status='available',available_version='2.0.21',notes=['Old release'],size=123)
            with patch('engine.updates.threading.Thread'):
                state=manager.check()
            self.assertIsNone(state['available_version'])
            self.assertEqual(state['notes'],[])
            self.assertFalse(state['can_download'])

    def test_patch_also_downloads_verified_recovery_msi(self):
        import io
        with tempfile.TemporaryDirectory() as d:
            manager=UpdateManager(d)
            full=self.package
            payload=b'patch'
            patch_package=dict(url=full['url'].replace('.msi','.msp'),size=len(payload),sha256=hashlib.sha256(payload).hexdigest())
            manager.package=patch_package;manager.manifest=self.sign(self.data)
            with patch('engine.updates.fetch',side_effect=[io.BytesIO(payload),io.BytesIO(b'abc')]) as fetch:
                manager._download()
            self.assertEqual(manager.snapshot()['status'],'ready')
            self.assertEqual(fetch.call_count,2)
            self.assertTrue((manager.directory/(full['sha256']+'.msi')).exists())
            self.assertTrue(manager.path.is_file())

    def test_bad_recovery_msi_blocks_patch_installation(self):
        import io
        with tempfile.TemporaryDirectory() as d:
            manager=UpdateManager(d)
            payload=b'patch'
            manager.package=dict(url=self.package['url'].replace('.msi','.msp'),size=len(payload),sha256=hashlib.sha256(payload).hexdigest())
            manager.manifest=self.sign(self.data)
            with patch('engine.updates.fetch',side_effect=[io.BytesIO(payload),io.BytesIO(b'bad')]):manager._download()
            self.assertEqual(manager.snapshot()['status'],'error')
            self.assertIsNone(manager.path)
            self.assertFalse((manager.directory/'manifest.json').exists())


if __name__=='__main__':unittest.main()
