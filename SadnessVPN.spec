# -*- mode: python ; coding: utf-8 -*-
import os
import sys

sys.path.insert(0, SPECPATH)
from engine.runtime_validation import validate_runtime_binaries


# Fail before packaging if sing-box and Wintun cannot run in one x64 process.
validate_runtime_binaries(os.path.join(SPECPATH, 'bin'))

# WebView2 и WinForms-обвязка окна убраны начиная с 2.0.26: интерфейс рисует
# Electron, а этот пакет собирается только как бэкенд движков.

a = Analysis(
    ['bootstrap.py'],
    pathex=[],
    binaries=[],
    datas=[
        # The notification-area icon is loaded at runtime by ui.tray.
        ('app.ico', '.'),
        ('PORTABLE-README.txt', '.'),
        # Шаблоны Flask — попадают в _internal/ui/templates (там и используются)
        ('ui/templates', 'ui/templates'),
        # Локальные SVG-флаги работают офлайн и не зависят от внешнего CDN.
        ('ui/static', 'ui/static'),
    ],
    hiddenimports=['backend_main'],
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
    upx=False,
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
    # webview2 исключён: Chromium теперь приходит внутри Electron.
    Tree('bin', prefix='bin', excludes=['backups', 'webview2', '*.bat', '*.backup', 'xray.exe']),
    strip=False,
    upx=False,
    upx_exclude=[],
    name='SadnessVPN',
)
