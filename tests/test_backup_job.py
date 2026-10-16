"""The backup job (backup/backup_job.py), with fake drives and a fake pg_dump."""

from datetime import datetime, time, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backup import backup_job, settings
from backup.drives import initialize_drive
from backup.errors import BackupError
from backup.storage import list_backups, verify_backup
from data.models.backup_run import BackupRun

T0 = datetime(2026, 10, 11, 20, 5, tzinfo=timezone.utc)
DIR = settings.BACKUP_DIR_NAME


@pytest.fixture()
def session_factory():
    import data.models  # noqa: F401
    from data.database import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


@pytest.fixture()
def drives(tmp_path):
    a, b = tmp_path / "driveA", tmp_path / "driveB"
    a.mkdir()
    b.mkdir()
    return [initialize_drive(a, "A"), initialize_drive(b, "B")]


def fake_dump(dest):
    Path(dest).write_bytes(b"PGDMP-fake-" * 100)


def run(session_factory, drives, **kw):
    kw.setdefault("dump", fake_dump)
    return backup_job.run_backup(
        session_factory,
        find_drives=lambda: drives,
        schema_revision=lambda: "rev1",
        min_orphan_age=0,
        **kw,
    )


def rows(session_factory):
    with session_factory() as s:
        return s.execute(select(BackupRun).order_by(BackupRun.started_at)).scalars().all()


# --- scheduling -----------------------------------------------------------------


def test_is_backup_due_rules():
    at = time(20, 0)
    now = datetime(2026, 10, 11, 21, 0, tzinfo=timezone.utc)
    assert backup_job.is_backup_due(None, now, at)
    assert not backup_job.is_backup_due(datetime(2026, 10, 11, 20, 10, tzinfo=timezone.utc), now, at)
    assert backup_job.is_backup_due(datetime(2026, 10, 10, 20, 10, tzinfo=timezone.utc), now, at)

    before = datetime(2026, 10, 11, 19, 0, tzinfo=timezone.utc)  # today's backup not yet due
    assert not backup_job.is_backup_due(datetime(2026, 10, 10, 20, 10, tzinfo=timezone.utc), before, at)
    assert backup_job.is_backup_due(datetime(2026, 10, 9, 20, 10, tzinfo=timezone.utc), before, at)


# --- successful runs ------------------------------------------------------------


def test_first_run_writes_a_verified_backup_to_every_drive(session_factory, drives):
    result = run(session_factory, drives, now=T0)

    assert result.status == backup_job.RESULT_OK and len(result.files) == 2
    for drive in drives:
        (info,) = list_backups(drive.root / DIR)
        verify_backup(info)
        assert info.schema_revision == "rev1"
        assert info.row_counts["patients"] == 0
        assert info.drive_id == drive.drive_id
    recorded = rows(session_factory)
    assert [r.status for r in recorded] == ["ok", "ok"]
    assert {r.drive_id for r in recorded} == {d.drive_id for d in drives}


def test_a_recent_success_means_nothing_is_due(session_factory, drives):
    run(session_factory, drives, now=T0)
    calls = []

    def counting_dump(dest):
        calls.append(1)
        fake_dump(dest)

    result = run(session_factory, drives, now=T0 + timedelta(hours=1), dump=counting_dump)

    assert result.status == backup_job.RESULT_NOT_DUE and calls == []


def test_next_evening_a_new_backup_is_made(session_factory, drives):
    run(session_factory, drives, now=T0)
    result = run(session_factory, drives, now=T0 + timedelta(days=1))

    assert result.status == backup_job.RESULT_OK
    assert len(list_backups(drives[0].root / DIR)) == 2


def test_force_backs_up_even_when_not_due(session_factory, drives):
    run(session_factory, drives, now=T0)
    result = run(session_factory, drives, now=T0 + timedelta(seconds=30), force=True)
    assert result.status == backup_job.RESULT_OK


def test_old_backups_are_pruned_to_the_keep_limit(session_factory, drives):
    for day in range(3):
        run(session_factory, drives, now=T0 + timedelta(days=day), keep=2)

    for drive in drives:
        assert len(list_backups(drive.root / DIR)) == 2


# --- failure modes --------------------------------------------------------------


def test_no_drive_records_drive_missing_once_and_makes_no_dump(session_factory):
    calls = []

    def counting_dump(dest):
        calls.append(1)

    for hours in (0, 1):
        result = backup_job.run_backup(
            session_factory,
            now=T0 + timedelta(hours=hours),
            find_drives=lambda: [],
            dump=counting_dump,
            schema_revision=lambda: None,
        )
        assert result.status == backup_job.RESULT_DRIVE_MISSING

    assert calls == []
    assert [r.status for r in rows(session_factory)] == ["drive_missing"]  # not one row per hourly retry


def test_dump_failure_is_recorded_and_writes_nothing(session_factory, drives):
    def failing_dump(dest):
        raise BackupError("pg_dump failed (exit code 1): connection refused")

    result = run(session_factory, drives, now=T0, dump=failing_dump)

    assert result.status == backup_job.RESULT_FAILED
    (row,) = rows(session_factory)
    assert row.status == "failed" and "connection refused" in row.error
    assert not (drives[0].root / DIR).exists()


def test_one_bad_drive_does_not_stop_the_good_one(session_factory, tmp_path):
    bad_root, good_root = tmp_path / "bad", tmp_path / "good"
    bad_root.mkdir()
    good_root.mkdir()
    bad, good = initialize_drive(bad_root), initialize_drive(good_root)
    (bad_root / DIR).write_text("blocks the backup folder")  # mkdir will fail

    result = run(session_factory, [bad, good], now=T0)

    assert result.status == backup_job.RESULT_OK and len(result.files) == 1
    by_drive = {r.drive_id: r.status for r in rows(session_factory)}
    assert by_drive == {bad.drive_id: "failed", good.drive_id: "ok"}
    assert len(list_backups(good_root / DIR)) == 1


def test_a_failed_write_leaves_the_previous_backup_intact(session_factory, drives):
    run(session_factory, drives[:1], now=T0)
    before = list_backups(drives[0].root / DIR)

    def broken_copy(src, dst):
        Path(dst).write_bytes(b"half")
        raise OSError("drive unplugged")

    original = backup_job.shutil.copyfile
    backup_job.shutil.copyfile = broken_copy
    try:
        result = run(session_factory, drives[:1], now=T0 + timedelta(days=1))
    finally:
        backup_job.shutil.copyfile = original

    assert result.status == backup_job.RESULT_FAILED
    assert list_backups(drives[0].root / DIR) == before
    assert not list((drives[0].root / DIR).glob("*.part"))