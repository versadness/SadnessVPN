# Independent one-file helper releases all client runtime files before MSI servicing.
a = Analysis(['installer/updater_main.py'], pathex=[SPECPATH], binaries=[], datas=[],
             hiddenimports=['win32security','win32api','pywintypes'], hookspath=[], hooksconfig={},
             runtime_hooks=[], excludes=[], noarchive=False, optimize=0)
pyz = PYZ(a.pure)
exe = EXE(pyz,a.scripts,a.binaries,a.datas,[],name='SadnessUpdater',debug=False,
          bootloader_ignore_signals=False,strip=False,upx=False,console=False,
          uac_admin=True,icon=['app.ico'])
