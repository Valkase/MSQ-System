"""
App-side half of applying an update: hand a VERIFIED staged exe to the helper
and let the app quit. Also cleans up leftover staging folders.

The helper is bundled inside the main exe as HealthCenterUpdater.exe, copied
into the staging folder (a temp location, so it can overwrite the install
folder's exe while the app is closed) and started detached.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from app_paths import config_dir, is_frozen, resource_path
from updater import settings
from updater.checksum import sha256_file
from updater.downloader import STAGING_PREFIX

HELPER_NAME = "HealthCenterUpdater.exe"


class UpdateApplyError(Exception):
    pass


def can_self_update() -> bool:
    """Only a frozen build, with the repo and signing key configured, may self-update."""
    return (
        is_frozen()
        and settings.GITHUB_OWNER != "CHANGE_ME"
        and settings.GITHUB_REPO != "CHANGE_ME"
        and bool(settings.SIGNING_PUBLIC_KEY_HEX)
    )


def start_update(
    staged_exe: Path,
    *,
    pid: int | None = None,
    target: Path | None = None,
    helper_source: Path | None = None,
    log_path: Path | None = None,
    popen=subprocess.Popen,
    frozen: bool | None = None,
) -> Path:
    """
    Start the helper. The caller must quit the app right after this returns.
    Returns the helper copy's path. Raises UpdateApplyError if it can't start.
    """
    if not (is_frozen() if frozen is None else frozen):
        raise UpdateApplyError("Self-update only works in the installed (frozen) application")

    staged_exe = Path(staged_exe)
    helper_source = Path(helper_source) if helper_source else resource_path(HELPER_NAME)
    if not helper_source.is_file():
        raise UpdateApplyError("Updater helper is missing from this build")
    if not staged_exe.is_file():
        raise UpdateApplyError("Staged update file is missing")

    target = Path(target) if target else Path(sys.executable).resolve()
    log_path = Path(log_path) if log_path else config_dir() / "updater.log"
    helper_copy = staged_exe.parent / HELPER_NAME

    try:
        shutil.copy2(helper_source, helper_copy)
        args = [
            str(helper_copy),
            "--pid", str(pid if pid is not None else os.getpid()),
            "--target", str(target),
            "--new", str(staged_exe),
            "--sha256", sha256_file(staged_exe),
            "--log", str(log_path),
        ]
        flags = {}
        if sys.platform.startswith("win"):
            flags["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        else:
            flags["start_new_session"] = True
        popen(args, close_fds=True, **flags)
    except OSError as exc:
        raise UpdateApplyError(f"Could not start the updater: {exc}") from exc
    return helper_copy


def cleanup_stale_staging(max_age_seconds: float = 3600, tmp_root: Path | None = None) -> int:
    """Best-effort removal of old update staging folders. Returns how many were removed."""
    root = Path(tmp_root) if tmp_root else Path(tempfile.gettempdir())
    removed = 0
    try:
        candidates = list(root.glob(STAGING_PREFIX + "*"))
    except OSError:
        return 0
    for path in candidates:
        try:
            if path.is_dir() and time.time() - path.stat().st_mtime > max_age_seconds:
                shutil.rmtree(path, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed
