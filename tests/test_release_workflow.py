import hashlib
import base64
import io
import json
import tempfile
import unittest
from pathlib import Path
from tools.activate_release import checked_child,referenced_versions
from tools.publish_release import prepare
from unittest.mock import patch
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
from engine.update_manifest import canonical
from tools import activate_release as deployment


class ReleaseWorkflowTests(unittest.TestCase):
    def test_patch_only_cannot_drop_existing_upgrade_paths(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);config,release=self.deployment_fixture(root)
            release('2.0.22');new,stage=release('2.0.25',stage=True)
            # Verification itself is covered by signature tests; isolate coverage gate.
            new.pop('full');new['distribution']='patch-only';new['patches']={}
            (stage/'setup.msi').unlink()
            (stage/'manifest.json').write_text(json.dumps(new))
            before=(root/'beta.json').read_bytes()
            with patch.object(deployment,'ROOT',root),patch.object(deployment,'CONFIG',config),patch.object(deployment,'verify',side_effect=lambda data,*_:data):
                with self.assertRaisesRegex(ValueError,'preserve direct upgrades'):deployment.activate(stage.name)
            self.assertEqual((root/'beta.json').read_bytes(),before)
            self.assertTrue((root/'releases/2.0.22').exists())

    def test_expired_upload_cleanup_keeps_recent_and_unexpected_content(self):
        import os
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);releases=root/'releases';releases.mkdir()
            stale=releases/('incoming-'+'a'*32);stale.mkdir();(stale/'setup.msi').write_bytes(b'old')
            recent=releases/('incoming-'+'b'*32);recent.mkdir();(recent/'setup.msi').write_bytes(b'new')
            unknown=releases/('incoming-'+'c'*32);unknown.mkdir();(unknown/'private.txt').write_bytes(b'keep')
            for p in [stale/'setup.msi',stale,unknown/'private.txt',unknown]:os.utime(p,(1,1))
            with patch.object(deployment,'ROOT',root):removed=deployment.cleanup_expired_uploads()
            self.assertEqual(removed,[stale.name]);self.assertTrue(recent.exists());self.assertTrue(unknown.exists())

    def deployment_fixture(self, root):
        key=Ed25519PrivateKey.generate()
        public=base64.b64encode(key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)).decode()
        config=root/'config.json'
        config.write_text(json.dumps(dict(public_key_base64=public,allowed_hosts=['updates.example.com'],https_base='https://updates.example.com/updates')))
        releases=root/'releases';releases.mkdir()
        def release(v,channel='beta',stage=False):
            data=dict(schema=1,product='Sadness VPN',version=v,channel=channel,notes=[],patches={},full=dict(url=f'https://updates.example.com/updates/releases/{v}/setup.msi',size=3,sha256=hashlib.sha256(b'abc').hexdigest()))
            data['signature']=base64.b64encode(key.sign(canonical(data))).decode()
            folder=releases/('incoming-'+'a'*32 if stage else v);folder.mkdir()
            (folder/'setup.msi').write_bytes(b'abc');(folder/'manifest.json').write_text(json.dumps(data))
            if not stage:(root/(channel+'.json')).write_text(json.dumps(data))
            return data,folder
        return config,release

    def test_failed_https_restores_previous_and_allows_same_version_retry(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);config,release=self.deployment_fixture(root)
            old,_=release('2.0.19');new,stage=release('2.0.20',stage=True)
            before=(root/'beta.json').read_bytes()
            with patch.object(deployment,'ROOT',root),patch.object(deployment,'CONFIG',config),patch.object(deployment.urllib.request,'urlopen',side_effect=OSError('offline')):
                with self.assertRaises(OSError):deployment.activate(stage.name)
            self.assertEqual((root/'beta.json').read_bytes(),before)
            self.assertTrue((root/'releases/2.0.19/setup.msi').exists())
            self.assertFalse((root/'releases/2.0.20').exists())
            self.assertFalse(stage.exists())
            _,stage=release('2.0.20',stage=True)
            self.assertTrue(stage.exists())

    def test_success_preserves_stable_and_removes_only_obsolete_beta(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);config,release=self.deployment_fixture(root)
            release('2.0.18','stable');release('2.0.19');new,stage=release('2.0.20',stage=True)
            def response(url,**kwargs):return io.BytesIO(json.dumps(new).encode() if url.endswith('.json') else b'abc')
            with patch.object(deployment,'ROOT',root),patch.object(deployment,'CONFIG',config),patch.object(deployment.urllib.request,'urlopen',side_effect=response):
                deployment.activate(stage.name)
            self.assertTrue((root/'releases/2.0.18/setup.msi').exists())
            self.assertTrue((root/'releases/2.0.20/setup.msi').exists())
            self.assertFalse((root/'releases/2.0.19').exists())
            self.assertIn('setup.msi',(root/'publication.log').read_text())

    def test_invalid_payload_never_changes_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);config,release=self.deployment_fixture(root)
            release('2.0.19');_,stage=release('2.0.20',stage=True)
            before=(root/'beta.json').read_bytes();(stage/'setup.msi').write_bytes(b'bad')
            with patch.object(deployment,'ROOT',root),patch.object(deployment,'CONFIG',config),patch.object(deployment.urllib.request,'urlopen') as network:
                with self.assertRaises(ValueError):deployment.activate(stage.name)
                network.assert_not_called()
            self.assertEqual((root/'beta.json').read_bytes(),before)
            self.assertFalse(stage.exists())

    def test_nested_content_and_active_release_cannot_be_deleted(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);config,release=self.deployment_fixture(root)
            _,folder=release('2.0.19');(folder/'unexpected').mkdir()
            with patch.object(deployment,'ROOT',root):
                with self.assertRaises(ValueError):deployment.remove_release(folder)
                with self.assertRaises(ValueError):deployment.remove_release(folder,{'2.0.19'})
            self.assertTrue((folder/'setup.msi').exists())

    def test_no_publication_without_microtest(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'test-report.json').write_text(json.dumps(dict(ready=False)))
            with self.assertRaisesRegex(ValueError,'Micro-test'):prepare(root,{},root/'missing-key')

    def test_technical_approval_does_not_bypass_required_checks(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            report=dict(version='2.0.24',ready=True,manual={},automated={'unit_tests':True},
                        publication_approval='owner_authorized_technical_only')
            (root/'test-report.json').write_text(json.dumps(report))
            (root/'update.json').write_text(json.dumps(dict(version='2.0.24')))
            with self.assertRaisesRegex(ValueError,'Technical publication checks'):prepare(root,{},root/'missing-key')

    def test_technical_approval_never_accepts_a_failed_check(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            report=dict(ready=True,manual={},automated={'unit_tests':False},
                        publication_approval='owner_authorized_technical_only')
            (root/'test-report.json').write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError,'incomplete or failed'):prepare(root,{},root/'missing-key')

    def test_paths_do_not_escape_release_root(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name in ['../outside','a/b','']:
                with self.assertRaises(ValueError):checked_child(root,name)
            self.assertEqual(checked_child(root,'2.0.20'),root/'2.0.20')

    def test_retain_both_channels_and_shared_payloads(self):
        def manifest(v):return dict(full=dict(url=f'https://updates.example.com/updates/releases/{v}/setup.msi'),patches={})
        self.assertEqual(referenced_versions([manifest('2.0.19'),manifest('2.0.20')]),{'2.0.19','2.0.20'})
        with self.assertRaises(ValueError):referenced_versions([dict(full=dict(url='https://updates.example.com/private/setup.msi'))])


if __name__=='__main__':unittest.main()
