"""
Finding the backup flash drive(s).

Only drives carrying a marker file (.hcs_backup_drive, created once with
`--init-drive`) are ever written to, so an unrelated USB stick is never used.
Each drive has its own id, which is how two rotating drives are told apart.
"""

import ctypes
import json
import sys
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from backup import settings
from backup.errors import BackupError

DRIVE_REMOVABLE = 2


@dataclass(frozen=True)
class BackupDrive:
    root: Path
    drive_id: str
    label: str | None = None


def removable_roots() -> list[Path]:
    """Root paths of removable drives (Windows). Empty elsewhere."""
    if not sys.platform.startswith("win"):
        return []
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    mask = kernel32.GetLogicalDrives()
    roots = []
    for index in range(26):
        if mask & (1 << index):
            root = f"{chr(ord('A') + index)}:\\"
            if kernel32.GetDriveTypeW(root) == DRIVE_REMOVABLE:
                roots.append(Path(root))
    return roots


def read_marker(root: Path) -> dict | None:
    try:
        data = json.loads((Path(root) / settings.MARKER_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("drive_id") else None


def find_backup_drives(roots: Iterable[Path] | None = None) -> list[BackupDrive]:
    """Marked drives among `roots` (default: removable drives + BACKUP_DRIVE_PATHS)."""
    if roots is None:
        roots = removable_roots() + settings.extra_drive_paths()
    drives, seen = [], set()
    for root in roots:
        root = Path(root)
        if root in seen:
            continue
        seen.add(root)
        marker = read_marker(root)
        if marker:
            drives.append(BackupDrive(root, str(marker["drive_id"]), marker.get("label")))
    return drives


def initialize_drive(root: Path, label: str | None = None) -> BackupDrive:
    """Mark `root` as a backup drive. Refuses to re-mark an already marked drive."""
    root = Path(root)
    if not root.is_dir():
        raise BackupError(f"{root} is not an accessible folder or drive")
    if read_marker(root):
        raise BackupError(f"{root} is already marked as a backup drive")
    drive_id = uuid.uuid4().hex[:12]
    marker = {
        "drive_id": drive_id,
        "label": label,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        (root / settings.MARKER_FILE).write_text(json.dumps(marker, indent=2), encoding="utf-8")
    except OSError as exc:
        raise BackupError(f"Could not write to {root}: {exc}") from exc
    return BackupDrive(root, drive_id, label)
