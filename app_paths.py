"""
Where things live, both when run from source and when frozen by PyInstaller.

- resource_path(): read-only files bundled INTO the exe (locales/, ...).
  Frozen --onefile apps unpack to a temp dir exposed as sys._MEIPASS.
- config_dir(): where the machine-specific .env (DB credentials) lives. When
  frozen it is %APPDATA%\\HealthCenterSystem, NOT next to the exe, so a
  self-update that replaces the exe can never touch or delete credentials,
  and nothing secret is ever baked into a build published on GitHub.
"""

import os
import sys
from pathlib import Path

APP_DIR_NAME = "HealthCenterSystem"
_PROJECT_ROOT = Path(__file__).resolve().parent


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_path(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", _PROJECT_ROOT))
    return base.joinpath(*parts)


def install_dir() -> Path:
    """Folder containing the running exe (frozen) or the project root (source)."""
    return Path(sys.executable).resolve().parent if is_frozen() else _PROJECT_ROOT


def config_dir() -> Path:
    if is_frozen():
        base = Path(os.environ.get("APPDATA") or Path.home())
        return base / APP_DIR_NAME
    return _PROJECT_ROOT


def env_file_path() -> Path:
    return config_dir() / ".env"
