"""Restore tool: verification, safety refusals and the report (no real PostgreSQL needed)."""

import hashlib
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backup import restore, storage
from backup.errors import BackupError
from backup.pgtools import ConnectionSettings
from version import EXPECTED_SCHEMA_REVISION, SCHEMA_REVISIONS

TARGET = ConnectionSettings("db-host", 5432, "hcs_app", "s3cret-pw", "healthcenter_restored")
CREATED = datetime(2026, 10, 11, 20, 5, tzinfo=timezone.utc)


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        return SimpleNamespace(returncode=0, stderr="")

    def tools(self):
        return [c[0] for c in self.calls]


def make_backup(tmp_path, *, revision=EXPECTED_SCHEMA_REVISION, counts=None, manifest=True):
    dump = tmp_path / "hcs-backup-20261011-200500.dump"
    content = b"PGDMP" * 100
    dump.write_bytes(content)
    if manifest:
        storage.write_sidecars(
            dump,
            {
                "format": 1,
                "file": dump.name,
                "created_at": CREATED.isoformat(),
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
                "schema_revision": revision,
                "app_version": "1.0.0",
                "row_counts": counts if counts is not None else {"patients": 2},
                "drive_id": "d1",
            },
        )
    return dump


def restore_with(dump, recorder, *, exists=True, tables=(), summary=("rev", {"patients": 2}), **kw):
    return restore.restore_backup(
        dump,
        target=TARGET,
        runner=recorder,
        find_tool=lambda name: name,
        exists_fn=lambda c: exists,
        tables_fn=lambda c: list(tables),
        summarize_fn=lambda c: summary,
        **kw,
    )


def test_restore_into_an_existing_empty_database(tmp_path):
    recorder = Recorder()
    report = restore_with(make_backup(tmp_path), recorder)

    assert recorder.tools() == ["pg_restore"]
    assert not report.created_database and report.mismatches == []
    assert "--clean" not in recorder.calls[0]
    assert "s3cret-pw" not in " ".join(recorder.calls[0])


def test_a_missing_target_database_is_created_first(tmp_path):
    recorder = Recorder()
    report = restore_with(make_backup(tmp_path), recorder, exists=False)

    assert recorder.tools() == ["createdb", "pg_restore"]
    assert report.created_database


def test_a_non_empty_target_is_refused_by_default(tmp_path):
    recorder = Recorder()
    with pytest.raises(BackupError, match="not empty"):
        restore_with(make_backup(tmp_path), recorder, tables=["patients"])
    assert recorder.calls == []


def test_replace_existing_overwrites_with_clean(tmp_path):
    recorder = Recorder()
    restore_with(make_backup(tmp_path), recorder, tables=["patients"], replace_existing=True)
    assert "--clean" in recorder.calls[0] and "--if-exists" in recorder.calls[0]


def test_a_damaged_backup_is_refused_before_anything_runs(tmp_path):
    dump = make_backup(tmp_path)
    dump.write_bytes(b"X" * dump.stat().st_size)  # same size, wrong content
    recorder = Recorder()

    with pytest.raises(BackupError, match="checksum"):
        restore_with(dump, recorder)
    assert recorder.calls == []


def test_a_backup_without_a_manifest_needs_explicit_permission(tmp_path):
    dump = make_backup(tmp_path, manifest=False)
    recorder = Recorder()
    with pytest.raises(BackupError, match="manifest"):
        restore_with(dump, recorder)
    assert recorder.calls == []

    report = restore_with(dump, recorder, allow_unverified=True)
    assert recorder.tools() == ["pg_restore"]
    assert any("without verification" in w for w in report.warnings)


def test_row_count_differences_are_reported(tmp_path):
    dump = make_backup(tmp_path, counts={"patients": 3, "doctors": 1})
    report = restore_with(dump, Recorder(), summary=("rev", {"patients": 2, "doctors": 1}))
    assert report.mismatches == [("patients", 3, 2)]


def test_missing_file_is_a_clean_error(tmp_path):
    with pytest.raises(BackupError, match="not found"):
        restore_with(tmp_path / "nope.dump", Recorder())


def test_target_database_name_is_required(tmp_path):
    with pytest.raises(BackupError):
        restore.restore_backup(
            make_backup(tmp_path),
            target=ConnectionSettings("h", 5432, "u", "p", None),
            runner=Recorder(),
            find_tool=lambda n: n,
        )


def test_schema_notes():
    assert "matches" in restore.describe_schema(EXPECTED_SCHEMA_REVISION)
    assert "alembic upgrade head" in restore.describe_schema(SCHEMA_REVISIONS[0])
    assert "NEWER" in restore.describe_schema("ffffffffffff")
    assert restore.describe_schema(None) is None