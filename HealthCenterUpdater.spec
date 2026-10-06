# -*- mode: python ; coding: utf-8 -*-
# The tiny swap helper (stdlib only). Built BEFORE the main app, which bundles it.
a = Analysis(
    ["updater/updater_helper/main.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "PySide6", "sqlalchemy", "babel", "cryptography", "requests"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="HealthCenterUpdater",
    debug=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,  # runs hidden; progress/errors go to the log file passed via --log
)
