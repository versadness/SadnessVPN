"""Signed, bounded update metadata shared by publisher, client and updater."""
import base64
import hashlib
import json
import re
from urllib.parse import urlsplit, unquote
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

MAX_MANIFEST = 256 * 1024
MAX_PACKAGE = 2 * 1024 * 1024 * 1024


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,4})', value):
        raise ValueError('Некорректный номер версии')
    parts = tuple(map(int, value.split('.')))
    if parts[0] > 255 or parts[1] > 255 or parts[2] > 65535: raise ValueError('Версия не поддерживается MSI')
    return parts


def canonical(data):
    return json.dumps({k:v for k,v in data.items() if k != 'signature'}, ensure_ascii=False,
                      sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def safe_url(value, hosts):
    if not isinstance(value, str): raise ValueError('Некорректный адрес обновления')
    parsed = urlsplit(value)
    port=parsed.port or 443
    authority=parsed.hostname if port==443 else f'{parsed.hostname}:{port}'
    if (parsed.scheme != 'https' or authority not in hosts or parsed.username or parsed.password
            or parsed.query or parsed.fragment
            or any(p == '..' for p in unquote(parsed.path).split('/'))):
        raise ValueError('Недоверенный адрес обновления')
    return value


def verify(data, public_key, hosts, channel):
    if not isinstance(data, dict): raise ValueError('Некорректный манифест')
    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key, validate=True))
        key.verify(base64.b64decode(data.get('signature',''), validate=True), canonical(data))
    except Exception:
        raise ValueError('Подпись обновления не прошла проверку') from None
    if data.get('schema') != 1 or data.get('product') != 'Sadness VPN' or data.get('channel') != channel or channel not in {'stable','beta'}:
        raise ValueError('Манифест другого продукта или канала')
    version(data.get('version'))
    notes = data.get('notes', [])
    if not isinstance(notes,list) or len(notes)>100 or any(not isinstance(n,str) or len(n)>2000 for n in notes):
        raise ValueError('Некорректное описание обновления')
    patches = data.get('patches',{})
    if not isinstance(patches,dict) or len(patches)>100: raise ValueError('Некорректный список патчей')
    for base in patches:
        if version(base)>=version(data['version']):raise ValueError('Патч должен повышать версию')
    patch_only=data.get('distribution')=='patch-only'
    if patch_only and (not patches or data.get('full') is not None):raise ValueError('Некорректный режим только патчей')
    for kind, package in ([] if patch_only else [('msi',data.get('full'))]) + [('msp',p) for p in patches.values()]:
        if not isinstance(package,dict): raise ValueError('Отсутствует пакет обновления')
        url = safe_url(package.get('url'),hosts)
        if not urlsplit(url).path.lower().endswith('.'+kind): raise ValueError('Неверный тип пакета')
        if type(package.get('size')) is not int or not 0 < package['size'] <= MAX_PACKAGE: raise ValueError('Недопустимый размер пакета')
        if not isinstance(package.get('sha256'),str) or not re.fullmatch('[0-9a-f]{64}',package['sha256']): raise ValueError('Некорректный хеш')
    return data


def select_package(data, installed):
    if version(data['version']) <= version(installed): return None
    return data.get('patches',{}).get(installed) or data.get('full')


def packages(data):
    return ([data['full']] if data.get('full') else [])+list(data.get('patches',{}).values())


def verify_file(path, package):
    if path.stat().st_size != package['size']: raise ValueError('Размер загрузки не совпадает')
    # The publisher also runs on VPS Python 3.10, which has no file_digest.
    checksum=hashlib.sha256()
    with path.open('rb') as stream:
        while chunk:=stream.read(1024*1024):checksum.update(chunk)
    digest=checksum.hexdigest()
    if digest != package['sha256']: raise ValueError('Контрольная сумма загрузки не совпадает')


def parse(raw):
    if len(raw)>MAX_MANIFEST: raise ValueError('Манифест слишком большой')
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result: raise ValueError('Повторяющееся поле манифеста')
            result[key]=value
        return result
    return json.loads(raw,object_pairs_hook=unique,parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Некорректное число')))
