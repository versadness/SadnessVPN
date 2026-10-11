"""Подписанные манифесты обновления (beta.json и stable.json) для релиза на GitHub.

Ключ подписи лежит вне репозитория и никуда не копируется. Манифесты кладутся
в релиз рядом с MSI; клиент берёт их по ссылке releases/latest/download.

    python tools/github_manifest.py --msi dist/SadnessVPN-3.4.3-Setup-x64.msi \
        --version 3.4.3 --notes installer/release-notes-3.4.3.json \
        --key %LOCALAPPDATA%/SadnessVPN-ReleaseKeys/publisher-ed25519.pem --out dist/manifest-3.4.3
"""
import argparse
import base64
import datetime
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, load_pem_private_key
from engine import update_policy as policy
from engine.update_manifest import canonical, verify, version

REPO = 'https://github.com/versadness/SadnessVPN/releases/download'


def _package(path: Path, ver: str) -> dict:
    return {'url': f'{REPO}/v{ver}-beta/{path.name}', 'size': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def build(msi: Path, ver: str, notes: list, key_path: Path, channel: str, patches: dict | None = None) -> dict:
    """patches — {установленная версия: путь к MSP}. Для этих версий ставится патч:
    программе обновления до 3.4.5 он не нужен пакет прежней версии для отката."""
    version(ver)
    data = {
        'schema': 1, 'product': 'Sadness VPN', 'channel': channel, 'version': ver,
        'published_at': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'notes': notes,
        'full': _package(msi, ver),
        'patches': {base: _package(Path(path), ver) for base, path in (patches or {}).items()},
    }
    key = load_pem_private_key(key_path.read_bytes(), password=None)
    public = base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode('ascii')
    if public != policy.PUBLIC_KEY_BASE64:
        raise ValueError('Ключ подписи не совпадает с ключом, встроенным в клиент')
    data['signature'] = base64.b64encode(key.sign(canonical(data))).decode('ascii')
    return verify(data, policy.PUBLIC_KEY_BASE64, policy.ALLOWED_HOSTS, channel)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--msi', type=Path, required=True)
    p.add_argument('--version', required=True)
    p.add_argument('--notes', type=Path, required=True, help='JSON: список строк или {"notes": [...]}')
    p.add_argument('--key', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--patch', action='append', default=[], metavar='BASE=PATH.msp',
                   help='прямой патч с установленной версии BASE')
    a = p.parse_args()
    if a.key.resolve().is_relative_to(ROOT):
        raise ValueError('Ключ подписи должен лежать вне репозитория')
    raw = json.loads(a.notes.read_text(encoding='utf-8'))
    notes = raw.get('notes', []) if isinstance(raw, dict) else raw
    a.out.mkdir(parents=True, exist_ok=True)
    for channel in ('beta', 'stable'):
        patches = dict(item.split('=', 1) for item in a.patch)
        data = build(a.msi, a.version, notes, a.key, channel, patches)
        (a.out / f'{channel}.json').write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    print('ok', a.out)


if __name__ == '__main__':
    main()
