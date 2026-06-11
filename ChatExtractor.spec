# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

rapidocr_datas, rapidocr_binaries, rapidocr_hiddenimports = collect_all('rapidocr_onnxruntime')
onnxruntime_datas, onnxruntime_binaries, onnxruntime_hiddenimports = collect_all('onnxruntime')
apkutils2_datas, apkutils2_binaries, apkutils2_hiddenimports = collect_all('apkutils2')


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[
        ('tools\\\\adb\\\\adb.exe', 'tools\\\\adb'),
        ('tools\\\\adb\\\\AdbWinApi.dll', 'tools\\\\adb'),
        ('tools\\\\adb\\\\AdbWinUsbApi.dll', 'tools\\\\adb'),
    ] + rapidocr_binaries + onnxruntime_binaries + apkutils2_binaries,
    datas=rapidocr_datas + onnxruntime_datas + apkutils2_datas,
    hiddenimports=rapidocr_hiddenimports + onnxruntime_hiddenimports + apkutils2_hiddenimports + ['pytesseract', 'numpy', 'apkutils2'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    name='ChatExtractor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    exclude_binaries=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ChatExtractor',
)
