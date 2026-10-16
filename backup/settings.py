"""
Backup settings. Constants are fixed; the functions read optional overrides
from the machine's .env at call time (config.py loads it).

    BACKUP_TIME=20:00             when the daily backup becomes due (local time)
    BACKUP_KEEP=30                complete backups kept per drive
    BACKUP_ALERT_AFTER_HOURS=30   admin is warned when the last success is older
    BACKUP_ALERTS=1               set to 0 to silence the admin warning (dev PCs)
    BACKUP_DRIVE_PATHS=E:\\       extra roots to look for the marker file, ';'
                                  separated (e.g. a USB hard disk Windows
                                  reports as a fixed drive)
    PG_BIN_DIR=C:\\Program Files\\PostgreSQL\\16\\bin
"""

import os
from datetime import time, timedelta
from pathlib import Path

MARKER_FILE = ".hcs_backup_drive"
BACKUP_DIR_NAME = "HealthCenterBackups"
FILE_PREFIX = "hcs-backup-"
DUMP_SUFFIX = ".dump"
CHECKSUM_SUFFIX = ".sha256"
MANIFEST_SUFFIX = ".json"
PART_SUFFIX = ".part"
MANIFEST_FORMAT = 1


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        value = int(os.getenv(name, ""))
    except ValueError:
        return default
    return value if value >= minimum else default


def keep_per_drive() -> int:
    return _env_int("BACKUP_KEEP", 30)


def alert_after() -> timedelta:
    return timedelta(hours=_env_int("BACKUP_ALERT_AFTER_HOURS", 30))


def alerts_enabled() -> bool:
    return os.getenv("BACKUP_ALERTS", "1").strip().lower() not in ("0", "false", "no")


def backup_time() -> time:
    raw = os.getenv("BACKUP_TIME", "20:00")
    try:
        hour, minute = raw.split(":")
        return time(int(hour), int(minute))
    except ValueError:
        return time(20, 0)


def extra_drive_paths() -> list[Path]:
    raw = os.getenv("BACKUP_DRIVE_PATHS", "")
    return [Path(p.strip()) for p in raw.split(os.pathsep) if p.strip()]

