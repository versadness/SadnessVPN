"""Administrator-owned full MSI recovery payloads, seeded by the MSI commit action.

Initial setup is trusted through the administrator's installation approval.
Downloaded payloads must additionally pass the publisher signature before caching.
No executable command is read from receipts.
"""
import hashlib
import json
from pathlib import Path
import shutil
from engine.json_store import atomic_write_json
from engine.update_manifest import verify_file, version
from engine.update_policy import PRODUCT_CODE


def msi_identity(path):
    import msilib
    db=msilib.OpenDatabase(str(path),0)
    view=db.OpenView('SELECT `Property`,`Value` FROM `Property`');view.Execute(None)
    props={}
    while row:=view.Fetch():props[row.GetString(1)]=row.GetString(2)
    view.Close()
    if props.get('ProductCode')!=PRODUCT_CODE:raise ValueError('Пакет восстановления другого продукта')
    version(props.get('ProductVersion'))
    view=db.OpenView('SELECT `Name` FROM `_Streams`');view.Execute(None)
    cabinet=False
    while row:=view.Fetch():cabinet|=row.GetString(1)=='payload.cab'
    view.Close()
    if not cabinet:raise ValueError('MSI не содержит полного автономного пакета')
    return props['ProductVersion']


def cache_full(source, protected, expected_version):
    source=Path(source)
    if source.suffix.lower()!='.msi' or source.is_symlink():raise ValueError('Неверный резервный пакет')
    if msi_identity(source)!=expected_version:raise ValueError('Версия резервного пакета не совпадает')
    with source.open('rb') as stream:checksum=hashlib.file_digest(stream,'sha256').hexdigest()
    package=dict(size=source.stat().st_size,sha256=checksum)
    target=protected/(checksum+'.msi')
    if target.resolve()!=target.absolute() or target.is_symlink():raise ValueError('Небезопасный путь резерва')
    if not target.exists():
        temporary=protected/(checksum+'.cache')
        try:
            with source.open('rb') as src,temporary.open('xb') as dst:
                shutil.copyfileobj(src,dst)
            verify_file(temporary,package)
            temporary.replace(target)
        finally:
            if temporary.exists():temporary.unlink()
    verify_file(target,package)
    # Inspect the copied bytes too, in case source changed while being copied.
    if msi_identity(target)!=expected_version:raise ValueError('Резервный пакет изменился')
    receipt=dict(schema=1,product_code=PRODUCT_CODE,version=expected_version,package=package)
    atomic_write_json(str(protected/('recovery-'+expected_version+'.json')),receipt)
    return target


def recovery_package(protected, expected_version):
    version(expected_version)
    receipt=json.loads((protected/('recovery-'+expected_version+'.json')).read_text(encoding='utf-8'))
    if receipt.get('schema')!=1 or receipt.get('product_code')!=PRODUCT_CODE or receipt.get('version')!=expected_version:
        raise ValueError('Некорректный резервный пакет')
    package=receipt['package'];checksum=package.get('sha256','')
    import re
    if not re.fullmatch('[0-9a-f]{64}',checksum):raise ValueError('Некорректный хеш резерва')
    target=protected/(checksum+'.msi')
    if target.is_symlink() or target.resolve()!=target.absolute():raise ValueError('Небезопасный резерв')
    verify_file(target,package)
    if msi_identity(target)!=expected_version:raise ValueError('Неверная версия резерва')
    return target
