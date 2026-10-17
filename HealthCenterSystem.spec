# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(SPECPATH)
MIGRATIONS = os.path.join(ROOT, "migrations")
assert os.path.isdir(os.path.join(MIGRATIONS, "versions")), "migrations folder not found: " + MIGRATIONS

datas = [(os.path.join(ROOT, "locales"), "locales")]
datas += collect_data_files("babel")
datas += [(MIGRATIONS, "migrations")]
datas += [(os.path.join(ROOT, "dist", "HealthCenterUpdater.exe"), ".")]

hiddenimports = [
    "psycopg2",
    "sqlalchemy.dialects.postgresql",
    "sqlalchemy.dialects.postgresql.psycopg2",
    "logging.config",
    "argon2",
] + collect_submodules("alembic")

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
