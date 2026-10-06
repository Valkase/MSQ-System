# -*- mode: python ; coding: utf-8 -*-
# Build with:  python -m scripts.build_release --tag vX.Y.Z --key <private key>
# (builds HealthCenterUpdater.spec first; this spec bundles dist/HealthCenterUpdater.exe)
from PyInstaller.utils.hooks import collect_data_files

datas = [("locales", "locales")]                        # i18n catalogs (app_paths.resource_path)
datas += collect_data_files("babel")                    # CLDR locale data used by i18n/formatting.py
datas += [("dist/HealthCenterUpdater.exe", ".")]        # swap helper, copied to temp at update time

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=["psycopg2", "sqlalchemy.dialects.postgresql.psycopg2"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="HealthCenterSystem",
    debug=False,
    strip=False,
    upx=False,          # UPX-packed exes trigger far more antivirus false positives
    runtime_tmpdir=None,
    console=False,      # GUI app: no console window
)
