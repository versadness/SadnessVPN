# -*- mode: python ; coding: utf-8 -*-
# Бэкенд Sadness VPN для Linux (AppImage, deb, rpm, pacman).
#
# Отличия от SadnessVPN.spec (Windows):
#   * двоичные файлы берутся из bin-linux/ (mihomo для Linux, geo-базы) и в
#     пакете лежат в bin/ — engine/paths.bin_path находит их там же;
#   * нет uac_admin: приложение работает от обычного пользователя, права на
#     TUN получает только ядро (engine/linux_core.py);
#   * нет Zapret, AmneziaWG и Wintun — на Linux они не используются.
import os
import sys

sys.path.insert(0, SPECPATH)

if not os.path.isfile(os.path.join(SPECPATH, 'bin-linux', 'mihomo')):
    raise SystemExit('bin-linux/mihomo не найден: скачайте ядро Mihomo для Linux')

a = Analysis(
    ['bootstrap.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('app.png', '.'),
        ('ui/templates', 'ui/templates'),
        ('ui/static', 'ui/static'),
    ],
    hiddenimports=['backend_main'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Windows-модули, которые на Linux не импортируются никогда.
    excludes=['win32com', 'pythoncom', 'pywintypes', 'win32api', 'winreg', 'msilib', 'clr', 'webview'],
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
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    Tree('bin-linux', prefix='bin'),
    strip=False,
    upx=False,
    name='SadnessVPN',
)
