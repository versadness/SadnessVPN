# -*- mode: python ; coding: utf-8 -*-
import os

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

# Tree() размещает папки РЯДОМ с SadnessVPN.exe (не в _internal/)
# Это критично для paths.py — он ищет bin/ рядом с exe
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    # bin/ рядом с .exe → dist/SadnessVPN/bin/
    Tree('bin',  prefix='bin'),
    # data/ рядом с .exe → dist/SadnessVPN/data/
    Tree('data', prefix='data'),
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SadnessVPN',
)
