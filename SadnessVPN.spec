# -*- mode: python ; coding: utf-8 -*-
import os

from engine.runtime_validation import validate_runtime_binaries


# Fail before packaging if sing-box and Wintun cannot run in one x64 process.
validate_runtime_binaries(os.path.join(SPECPATH, 'bin'))

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        # Шаблоны Flask — попадают в _internal/ui/templates (там и используются)
        ('ui/templates', 'ui/templates'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SadnessVPN',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,
    icon=['app.ico'],
)

# Пользовательские data-файлы намеренно не входят в сборку.
# Frozen-версия хранит их в %LOCALAPPDATA%\SadnessVPN\data.
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    # Сторонние движки и драйверы нужны приложению во время выполнения.
    Tree('bin', prefix='bin', excludes=['backups']),
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SadnessVPN',
)
