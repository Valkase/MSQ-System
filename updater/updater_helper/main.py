"""
Updater helper (task plan Phase 5: "waits for main app to close, swaps files,
relaunches"). Built as its own tiny exe (HealthCenterUpdater.exe), bundled
inside the main exe, and copied to a temp folder by the app before it is run
(Windows locks a running exe, so it can't live in the install folder).

Deliberately STANDARD LIBRARY ONLY and no imports from the rest of the project,
so it stays small and can't be broken by changes elsewhere.

Sequence:
 1. wait for the main app process to exit (abort, touching nothing, if it doesn't)
 2. re-check the staged exe's SHA-256 (the app already verified checksum + signature)
 3. copy staged exe next to the install as <exe>.new, back up the current exe as <exe>.bak
 4. atomically os.replace(<exe>.new -> <exe>)   [old exe is intact if this fails]
 5. launch the new exe and watch it for a grace period; if it dies with an
    error, restore <exe>.bak and relaunch the old version.
The relaunch also happens when the update itself fails, so the receptionist
always ends up with a running app.

Exit codes: 0 updated, 1 failed (old version still installed), 2 rolled back.
"""

import argparse
import hashlib
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_ROLLED_BACK = 2

log = logging.getLogger("updater_helper")


class UpdateFailed(Exception):
    """The update could not be applied; the installed exe was left untouched."""


def pid_exists(pid: int) -> bool:
    if sys.platform.startswith("win"):
        # NOT os.kill(pid, 0): on Windows that TERMINATES the process.
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            return False
        try:
            return kernel32.WaitForSingleObject(handle, 0) == 0x102  # WAIT_TIMEOUT: still running
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def wait_for_exit(pid, timeout, *, exists=pid_exists, sleep=time.sleep, clock=time.monotonic, poll=0.25) -> bool:
    deadline = clock() + timeout
    while exists(pid):
        if clock() >= deadline:
            return False
        sleep(poll)
    return True


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def replace_with_retry(src: Path, dst: Path, *, attempts=20, delay=0.5, sleep=time.sleep) -> None:
    """os.replace, retrying: antivirus or the Windows loader may briefly hold the old exe."""
    last: OSError | None = None
    for _ in range(attempts):
        try:
            os.replace(src, dst)
            return
        except OSError as exc:
            last = exc
            sleep(delay)
    raise last  # type: ignore[misc]


def apply_update(target: Path, new_exe: Path, expected_sha256: str, *, replace=replace_with_retry) -> Path:
    """Swap `new_exe` in as `target`. Returns the backup path. Raises UpdateFailed."""
    staged = target.with_name(target.name + ".new")
    backup = target.with_name(target.name + ".bak")
    try:
        if sha256_file(new_exe) != expected_sha256.lower():
            raise UpdateFailed("Staged update does not match the expected checksum")
        shutil.copy2(new_exe, staged)  # same folder as target => same volume => atomic replace
        if sha256_file(staged) != expected_sha256.lower():
            raise UpdateFailed("Copied update does not match the expected checksum")
        if target.exists():
            shutil.copy2(target, backup)
        replace(staged, target)
    except UpdateFailed:
        staged.unlink(missing_ok=True)
        raise
    except OSError as exc:
        staged.unlink(missing_ok=True)
        raise UpdateFailed(f"Could not install update: {exc}") from exc
    return backup


def rollback(target: Path, backup: Path, *, replace=replace_with_retry) -> None:
    if not backup.exists():
        raise UpdateFailed("No backup available to roll back to")
    tmp = target.with_name(target.name + ".rollback")
    try:
        shutil.copy2(backup, tmp)
        replace(tmp, target)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise UpdateFailed(f"Rollback failed: {exc}") from exc


def launch(target: Path, *, popen=subprocess.Popen):
    kwargs = {}
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return popen([str(target)], close_fds=True, **kwargs)


def launch_and_watch(target: Path, grace: float, *, popen=subprocess.Popen, sleep=time.sleep, clock=time.monotonic) -> bool:
    """Start the app; True if it is still running after `grace` seconds or exited cleanly."""
    proc = launch(target, popen=popen)
    deadline = clock() + grace
    while clock() < deadline:
        code = proc.poll()
        if code is not None:
            return code == 0
        sleep(0.25)
    return True


def perform_update(
    *,
    pid: int,
    target: Path,
    new_exe: Path,
    expected_sha256: str,
    wait_timeout: float = 60.0,
    grace: float = 8.0,
    popen=subprocess.Popen,
    exists=pid_exists,
    sleep=time.sleep,
    clock=time.monotonic,
    replace=replace_with_retry,
) -> int:
    log.info("Waiting for app (pid %s) to exit", pid)
    if not wait_for_exit(pid, wait_timeout, exists=exists, sleep=sleep, clock=clock):
        log.error("App did not exit within %ss; update abandoned, nothing changed", wait_timeout)
        return EXIT_FAILED

    try:
        backup = apply_update(target, new_exe, expected_sha256, replace=replace)
    except UpdateFailed as exc:
        log.error("Update failed: %s", exc)
        launch(target, popen=popen)  # the user closed the app for this: give it back (old version)
        return EXIT_FAILED

    log.info("Update installed; starting new version")
    if launch_and_watch(target, grace, popen=popen, sleep=sleep, clock=clock):
        log.info("New version is running")
        new_exe.unlink(missing_ok=True)
        return EXIT_OK

    log.error("New version exited with an error; rolling back")
    try:
        rollback(target, backup, replace=replace)
    except UpdateFailed as exc:
        log.critical("%s", exc)
        return EXIT_FAILED
    launch(target, popen=popen)
    return EXIT_ROLLED_BACK


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--new", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--log", type=Path)
    parser.add_argument("--wait", type=float, default=60.0)
    parser.add_argument("--grace", type=float, default=8.0)
    args = parser.parse_args(argv)

    handlers = []
    if args.log:
        args.log.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(args.log, encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO, handlers=handlers or None, format="%(asctime)s %(levelname)s %(message)s"
    )
    try:
        return perform_update(
            pid=args.pid,
            target=args.target,
            new_exe=args.new,
            expected_sha256=args.sha256,
            wait_timeout=args.wait,
            grace=args.grace,
        )
    except Exception:
        log.exception("Unexpected error in updater helper")
        return EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
