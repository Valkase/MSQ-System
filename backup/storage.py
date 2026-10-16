"""
On-disk format of a backup, shared by the backup job and the restore tool.

A backup is three files in <drive>\\HealthCenterBackups:
    hcs-backup-<stamp>.dump          pg_dump custom-format file
    hcs-backup-<stamp>.dump.sha256   sha256sum-style checksum
    hcs-backup-<stamp>.dump.json     manifest, written LAST

A backup is COMPLETE only once its manifest exists. Anything else with our
prefix (a .part file, a dump with no manifest) is debris from an interrupted
write and is cleaned up, never treated as a backup.
"""

import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from backup import settings
from backup.errors import BackupError


def as_aware_utc(value: datetime) -> datetime:
    """Some backends (SQLite in tests) return naive datetimes; treat them as UTC."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fsync_file(path: Path) -> None:
    with open(path, "rb+") as fh:
        fh.flush()
        os.fsync(fh.fileno())


def write_text_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + settings.PART_SUFFIX)
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def backup_file_name(created: datetime) -> str:
    return f"{settings.FILE_PREFIX}{created:%Y%m%d-%H%M%S}{settings.DUMP_SUFFIX}"


def sidecar_paths(dump_path: Path) -> tuple[Path, Path]:
    """(checksum_path, manifest_path) for a dump file."""
    return (
        dump_path.with_name(dump_path.name + settings.CHECKSUM_SUFFIX),
        dump_path.with_name(dump_path.name + settings.MANIFEST_SUFFIX),
    )


def write_sidecars(dump_path: Path, manifest: dict) -> None:
    """Write the checksum file, then the manifest (last: it marks the backup complete)."""
    checksum_path, manifest_path = sidecar_paths(dump_path)
    write_text_atomic(checksum_path, f"{manifest['sha256']}  {dump_path.name}\n")
    write_text_atomic(manifest_path, json.dumps(manifest, indent=2, sort_keys=True) + "\n")


@dataclass(frozen=True)
class BackupInfo:
    dump_path: Path
    manifest_path: Path
    checksum_path: Path
    created_at: datetime
    sha256: str
    size_bytes: int
    schema_revision: str | None
    app_version: str | None
    row_counts: dict
    drive_id: str | None


def load_info(manifest_path: Path) -> BackupInfo | None:
    """Parse a manifest. None if it is unreadable or its dump file is missing."""
    manifest_path = Path(manifest_path)
    name = manifest_path.name
    if not name.endswith(settings.MANIFEST_SUFFIX):
        return None
    dump_path = manifest_path.with_name(name[: -len(settings.MANIFEST_SUFFIX)])
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not dump_path.is_file():
            return None
        return BackupInfo(
            dump_path=dump_path,
            manifest_path=manifest_path,
            checksum_path=sidecar_paths(dump_path)[0],
            created_at=as_aware_utc(datetime.fromisoformat(data["created_at"])),
            sha256=str(data["sha256"]).lower(),
            size_bytes=int(data["size_bytes"]),
            schema_revision=data.get("schema_revision"),
            app_version=data.get("app_version"),
            row_counts=dict(data.get("row_counts") or {}),
            drive_id=data.get("drive_id"),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


def list_backups(directory: Path) -> list[BackupInfo]:
    """Complete backups in `directory`, newest first."""
    directory = Path(directory)
    if not directory.is_dir():
        return []
    pattern = f"{settings.FILE_PREFIX}*{settings.DUMP_SUFFIX}{settings.MANIFEST_SUFFIX}"
    infos = [i for i in (load_info(p) for p in directory.glob(pattern)) if i is not None]
    infos.sort(key=lambda i: i.created_at, reverse=True)
    return infos


def verify_backup(info: BackupInfo) -> None:
    """Raise BackupError unless the dump matches its manifest and checksum file."""
    try:
        actual_size = info.dump_path.stat().st_size
    except OSError as exc:
        raise BackupError(f"Cannot read {info.dump_path.name}: {exc}") from exc
    if actual_size != info.size_bytes:
        raise BackupError(f"{info.dump_path.name}: size differs from its manifest")
    if sha256_file(info.dump_path) != info.sha256:
        raise BackupError(f"{info.dump_path.name}: checksum mismatch (file is damaged)")
    try:
        sidecar = info.checksum_path.read_text(encoding="utf-8").split()[0].lower()
    except (OSError, IndexError) as exc:
        raise BackupError(f"{info.dump_path.name}: checksum file missing or unreadable") from exc
    if sidecar != info.sha256:
        raise BackupError(f"{info.dump_path.name}: checksum file disagrees with the manifest")


def prune(directory: Path, keep: int) -> list[Path]:
    """Delete complete backups beyond the newest `keep`. Returns removed dump paths."""
    keep = max(int(keep), 1)
    removed = []
    for info in list_backups(directory)[keep:]:
        try:
            # Manifest first, so a half-deleted backup is never seen as complete.
            info.manifest_path.unlink(missing_ok=True)
            info.checksum_path.unlink(missing_ok=True)
            info.dump_path.unlink(missing_ok=True)
            removed.append(info.dump_path)
        except OSError:
            continue
    return removed


def cleanup_incomplete(directory: Path, *, min_age_seconds: float = 600.0) -> list[Path]:
    """Remove debris from interrupted writes (our-prefix files that aren't part of a complete backup)."""
    directory = Path(directory)
    if not directory.is_dir():
        return []
    complete: set[Path] = set()
    for info in list_backups(directory):
        complete |= {info.dump_path, info.checksum_path, info.manifest_path}
    cutoff = time.time() - min_age_seconds
    removed = []
    for path in directory.iterdir():
        if not path.name.startswith(settings.FILE_PREFIX) or path in complete:
            continue
        try:
            if path.is_file() and path.stat().st_mtime <= cutoff:
                path.unlink()
                removed.append(path)
        except OSError:
            continue
    return removed