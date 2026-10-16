"""Backup file format: listing, verification, pruning and cleanup (backup/storage.py)."""

import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from backup import settings, storage
from backup.errors import BackupError
from backup.drives import find_backup_drives, initialize_drive

T0 = datetime(2026, 10, 11, 20, 5, tzinfo=timezone.utc)


def make_backup(directory, stamp, *, created, content=b"data" * 50):
    directory.mkdir(parents=True, exist_ok=True)
    dump = directory / f"hcs-backup-{stamp}.dump"
    dump.write_bytes(content)
    storage.write_sidecars(
        dump,
        {
            "format": 1,
            "file": dump.name,
            "created_at": created.isoformat(),
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
            "schema_revision": "rev1",
            "app_version": "1.0.0",
            "row_counts": {"patients": 2},
            "drive_id": "d1",
        },
    )
    return dump


def test_list_backups_is_newest_first_and_ignores_incomplete(tmp_path):
    older = make_backup(tmp_path, "20261010-200000", created=T0 - timedelta(days=1))
    newer = make_backup(tmp_path, "20261011-200000", created=T0)
    (tmp_path / "hcs-backup-20261012-200000.dump").write_bytes(b"no manifest")  # interrupted write

    infos = storage.list_backups(tmp_path)

    assert [i.dump_path for i in infos] == [newer, older]
    assert infos[0].row_counts == {"patients": 2}


def test_verify_passes_for_an_intact_backup(tmp_path):
    make_backup(tmp_path, "20261011-200000", created=T0)
    storage.verify_backup(storage.list_backups(tmp_path)[0])


def test_verify_detects_a_damaged_dump(tmp_path):
    dump = make_backup(tmp_path, "20261011-200000", created=T0, content=b"a" * 200)
    info = storage.list_backups(tmp_path)[0]
    dump.write_bytes(b"b" * 200)  # same size, different content
    with pytest.raises(BackupError, match="checksum"):
        storage.verify_backup(info)


def test_verify_detects_a_truncated_dump(tmp_path):
    dump = make_backup(tmp_path, "20261011-200000", created=T0)
    info = storage.list_backups(tmp_path)[0]
    dump.write_bytes(b"short")
    with pytest.raises(BackupError, match="size"):
        storage.verify_backup(info)


def test_verify_detects_a_missing_checksum_file(tmp_path):
    dump = make_backup(tmp_path, "20261011-200000", created=T0)
    info = storage.list_backups(tmp_path)[0]
    storage.sidecar_paths(dump)[0].unlink()
    with pytest.raises(BackupError, match="checksum file"):
        storage.verify_backup(info)


def test_prune_keeps_only_the_newest_and_removes_all_three_files(tmp_path):
    dumps = [
        make_backup(tmp_path, f"2026101{i}-200000", created=T0 + timedelta(days=i)) for i in range(4)
    ]

    removed = storage.prune(tmp_path, keep=2)

    assert set(removed) == {dumps[0], dumps[1]}
    for gone in (dumps[0], dumps[1]):
        assert not gone.exists()
        assert not any(p.exists() for p in storage.sidecar_paths(gone))
    assert [i.dump_path for i in storage.list_backups(tmp_path)] == [dumps[3], dumps[2]]


def test_prune_never_deletes_the_last_backup(tmp_path):
    make_backup(tmp_path, "20261011-200000", created=T0)
    assert storage.prune(tmp_path, keep=0) == []
    assert len(storage.list_backups(tmp_path)) == 1


def test_cleanup_removes_interrupted_debris_only(tmp_path):
    good = make_backup(tmp_path, "20261011-200000", created=T0)
    (tmp_path / "hcs-backup-20261012-200000.dump.part").write_bytes(b"half")
    (tmp_path / "hcs-backup-20261013-200000.dump").write_bytes(b"orphan")
    marker = tmp_path / settings.MARKER_FILE
    marker.write_text("{}")
    unrelated = tmp_path / "holiday-photos.zip"
    unrelated.write_bytes(b"x")

    removed = storage.cleanup_incomplete(tmp_path, min_age_seconds=0)

    assert len(removed) == 2
    assert good.exists() and all(p.exists() for p in storage.sidecar_paths(good))
    assert marker.exists() and unrelated.exists()


def test_cleanup_spares_recent_files_that_another_run_may_be_writing(tmp_path):
    part = tmp_path / "hcs-backup-20261012-200000.dump.part"
    part.write_bytes(b"in progress")
    assert storage.cleanup_incomplete(tmp_path, min_age_seconds=600) == []
    assert part.exists()


# --- drives ---------------------------------------------------------------------


def test_only_marked_drives_are_found(tmp_path):
    marked, plain = tmp_path / "marked", tmp_path / "plain"
    marked.mkdir()
    plain.mkdir()
    drive = initialize_drive(marked, "Drive A")

    found = find_backup_drives([marked, plain])

    assert [d.drive_id for d in found] == [drive.drive_id]
    assert found[0].label == "Drive A"


def test_two_drives_get_different_ids(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    assert initialize_drive(a).drive_id != initialize_drive(b).drive_id


def test_a_marked_drive_cannot_be_marked_twice(tmp_path):
    initialize_drive(tmp_path)
    with pytest.raises(BackupError):
        initialize_drive(tmp_path)


def test_a_missing_folder_cannot_be_marked(tmp_path):
    with pytest.raises(BackupError):
        initialize_drive(tmp_path / "does-not-exist")