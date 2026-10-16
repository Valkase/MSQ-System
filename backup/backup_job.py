"""
The automatic offline backup job (task plan Phase 7).

Run by Windows Task Scheduler on the database PC, every hour:

    HealthCenterSystem.exe --backup          (installed build, self-updating)
    python -m backup.backup_job              (from source)

The job decides for itself whether a backup is due (default: once a day after
20:00), so an hourly trigger doubles as a retry: if the flash drive wasn't
plugged in at 20:00, the first run after it is connected makes the backup.

Every attempt is recorded in the backup_runs table; the app reads that table
to warn an admin at login when backups are overdue (logic/backup_status.py).

One-time drive setup:
    python -m backup.backup_job --init-drive E:\\ --label "Drive A"

Exit codes: 0 ok / nothing due, 1 failed, 2 no backup drive connected.
"""

import argparse
import logging
import logging.handlers
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select

import data.models  # noqa: F401  (registers every table on Base.metadata)
from app_paths import config_dir
from backup import settings
from backup.drives import BackupDrive, find_backup_drives, initialize_drive
from backup.errors import BackupError
from backup.pgtools import dump_database
from backup.storage import (
    as_aware_utc,
    backup_file_name,
    cleanup_incomplete,
    fsync_file,
    prune,
    sha256_file,
    write_sidecars,
)
from data.database import Base, SessionLocal, engine
from data.models.backup_run import (
    STATUS_DRIVE_MISSING,
    STATUS_FAILED,
    STATUS_OK,
    BackupRun,
)
from data.schema_check import get_db_revision
from version import __version__

log = logging.getLogger("backup")

RESULT_OK = "ok"
RESULT_NOT_DUE = "not_due"
RESULT_FAILED = "failed"
RESULT_DRIVE_MISSING = "drive_missing"

_EXIT_CODES = {RESULT_OK: 0, RESULT_NOT_DUE: 0, RESULT_FAILED: 1, RESULT_DRIVE_MISSING: 2}


@dataclass
class BackupResult:
    status: str
    files: list[Path]
    message: str


# --- scheduling -----------------------------------------------------------------


def latest_scheduled(now: datetime, at: time) -> datetime:
    """The most recent moment a backup was supposed to start (today at `at`, or yesterday's)."""
    candidate = now.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)
    return candidate if now >= candidate else candidate - timedelta(days=1)


def is_backup_due(last_ok: datetime | None, now: datetime, at: time) -> bool:
    """Due when no successful backup has happened since the latest scheduled time."""
    if last_ok is None:
        return True
    return as_aware_utc(last_ok) < latest_scheduled(now, at)


# --- bookkeeping ----------------------------------------------------------------


def collect_row_counts(session) -> dict[str, int]:
    """Row count per table; stored in the manifest so a restore can be sanity-checked."""
    return {
        table.name: session.execute(select(func.count()).select_from(table)).scalar_one()
        for table in Base.metadata.sorted_tables
    }


def _record(session_factory, *, now: datetime, status: str, **fields) -> None:
    """Write one backup_runs row. Never raises: a bookkeeping failure must not hide the backup outcome."""
    try:
        with session_factory() as session:
            session.add(
                BackupRun(
                    started_at=now.astimezone(timezone.utc),
                    finished_at=datetime.now(timezone.utc),
                    status=status,
                    **fields,
                )
            )
            session.commit()
    except Exception:
        log.exception("Could not record the backup run in the database")


def _last_run_status(session_factory) -> str | None:
    with session_factory() as session:
        return session.execute(
            select(BackupRun.status).order_by(BackupRun.started_at.desc()).limit(1)
        ).scalar_one_or_none()


# --- writing to a drive ---------------------------------------------------------


def _write_to_drive(
    drive: BackupDrive,
    dump_path: Path,
    *,
    sha: str,
    size: int,
    now: datetime,
    revision: str | None,
    counts: dict,
    min_orphan_age: float,
) -> Path:
    directory = drive.root / settings.BACKUP_DIR_NAME
    directory.mkdir(parents=True, exist_ok=True)
    cleanup_incomplete(directory, min_age_seconds=min_orphan_age)

    if shutil.disk_usage(directory).free < size * 1.1 + 1_000_000:
        raise BackupError(f"Not enough free space on {drive.root}")

    final = directory / dump_path.name
    part = final.with_name(final.name + settings.PART_SUFFIX)
    try:
        shutil.copyfile(dump_path, part)
        fsync_file(part)
        if sha256_file(part) != sha:  # re-read from the flash drive: catches bad writes
            raise BackupError("The copy written to the drive does not match the original")
        os.replace(part, final)
    except Exception:
        try:
            part.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    from config import DB_NAME

    write_sidecars(
        final,
        {
            "format": settings.MANIFEST_FORMAT,
            "file": final.name,
            "created_at": now.astimezone(timezone.utc).isoformat(),
            "app_version": __version__,
            "schema_revision": revision,
            "db_name": DB_NAME,
            "size_bytes": size,
            "sha256": sha,
            "row_counts": counts,
            "drive_id": drive.drive_id,
        },
    )
    return final


# --- the job --------------------------------------------------------------------


def run_backup(
    session_factory=SessionLocal,
    *,
    now: datetime | None = None,
    force: bool = False,
    find_drives=find_backup_drives,
    dump=dump_database,
    schema_revision=None,
    keep: int | None = None,
    min_orphan_age: float = 600.0,
) -> BackupResult:
    now = now or datetime.now().astimezone()
    keep = keep or settings.keep_per_drive()
    if schema_revision is None:
        schema_revision = lambda: get_db_revision(engine)  # noqa: E731

    with session_factory() as session:
        last_ok = session.execute(
            select(func.max(BackupRun.started_at)).where(BackupRun.status == STATUS_OK)
        ).scalar_one()
    if not force and not is_backup_due(last_ok, now, settings.backup_time()):
        return BackupResult(RESULT_NOT_DUE, [], "No backup is due.")

    drives = find_drives()
    if not drives:
        message = "No backup drive is connected. Connect a marked flash drive."
        log.warning(message)
        if _last_run_status(session_factory) != STATUS_DRIVE_MISSING:  # don't flood the table hourly
            _record(session_factory, now=now, status=STATUS_DRIVE_MISSING, error=message)
        return BackupResult(RESULT_DRIVE_MISSING, [], message)

    with tempfile.TemporaryDirectory(prefix="hcs-backup-") as tmp:
        dump_path = Path(tmp) / backup_file_name(now)
        try:
            dump(dump_path)
            sha = sha256_file(dump_path)
            size = dump_path.stat().st_size
            with session_factory() as session:
                counts = collect_row_counts(session)
            revision = schema_revision()
        except Exception as exc:
            log.exception("Database dump failed")
            _record(session_factory, now=now, status=STATUS_FAILED, error=str(exc)[:2000])
            return BackupResult(RESULT_FAILED, [], f"Database dump failed: {exc}")

        written: list[Path] = []
        errors: list[str] = []
        for drive in drives:
            try:
                final = _write_to_drive(
                    drive,
                    dump_path,
                    sha=sha,
                    size=size,
                    now=now,
                    revision=revision,
                    counts=counts,
                    min_orphan_age=min_orphan_age,
                )
            except Exception as exc:
                log.exception("Writing the backup to drive %s failed", drive.drive_id)
                errors.append(f"{drive.root}: {exc}")
                _record(
                    session_factory,
                    now=now,
                    status=STATUS_FAILED,
                    drive_id=drive.drive_id,
                    error=str(exc)[:2000],
                )
                continue

            written.append(final)
            _record(
                session_factory,
                now=now,
                status=STATUS_OK,
                drive_id=drive.drive_id,
                file_name=final.name,
                size_bytes=size,
                sha256=sha,
            )
            try:
                removed = prune(final.parent, keep)
                if removed:
                    log.info("Pruned %d old backup(s) from %s", len(removed), drive.root)
            except Exception:
                log.exception("Pruning old backups on %s failed (ignored)", drive.root)

    if written:
        message = f"Backup written to {len(written)} drive(s)."
        if errors:
            message += " Failed on: " + "; ".join(errors)
        log.info(message)
        return BackupResult(RESULT_OK, written, message)
    return BackupResult(RESULT_FAILED, [], "Backup failed on every drive: " + "; ".join(errors))


# --- command line ---------------------------------------------------------------


def _say(text: str) -> None:
    if sys.stdout is not None:  # the windowed exe has no console
        print(text)


def _configure_logging() -> None:
    root = logging.getLogger()
    if any(getattr(h, "_hcs_backup", False) for h in root.handlers):
        return
    root.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handlers: list[logging.Handler] = []
    try:
        config_dir().mkdir(parents=True, exist_ok=True)
        handlers.append(
            logging.handlers.RotatingFileHandler(
                config_dir() / "backup.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
            )
        )
    except OSError:
        pass
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    for handler in handlers:
        handler.setFormatter(formatter)
        handler._hcs_backup = True  # type: ignore[attr-defined]
        root.addHandler(handler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Health Center offline backup job")
    parser.add_argument("--force", action="store_true", help="back up now even if none is due")
    parser.add_argument("--keep", type=int, help="backups to keep per drive (default from .env / 30)")
    parser.add_argument("--init-drive", type=Path, metavar="PATH", help="mark a drive as a backup drive")
    parser.add_argument("--label", help="friendly name for --init-drive")
    parser.add_argument("--list-drives", action="store_true", help="show connected backup drives")
    args = parser.parse_args(argv)
    _configure_logging()

    if args.init_drive:
        try:
            drive = initialize_drive(args.init_drive, args.label)
        except BackupError as exc:
            _say(str(exc))
            return 1
        _say(f"Marked {drive.root} as a backup drive (id {drive.drive_id}).")
        return 0

    if args.list_drives:
        drives = find_backup_drives()
        for d in drives:
            _say(f"{d.root}  id={d.drive_id}  label={d.label or '-'}")
        if not drives:
            _say("No backup drives connected.")
        return 0

    try:
        result = run_backup(force=args.force, keep=args.keep)
    except Exception:
        log.exception("Backup job crashed")
        _say("Backup job crashed. See backup.log.")
        return 1
    _say(result.message)
    return _EXIT_CODES[result.status]


if __name__ == "__main__":
    sys.exit(main())