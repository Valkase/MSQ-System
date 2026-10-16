"""
Restore a backup (task plan Phase 7: documented and TESTED restore).

    python -m backup.restore --list
    python -m backup.restore --latest --target-db healthcenter_restored
    python -m backup.restore --file E:\\HealthCenterBackups\\hcs-backup-....dump --target-db healthcenter_restored
    python -m backup.restore --latest --target-db healthcenter --replace-existing   (disaster recovery)

Safety rules:
  * --target-db is always explicit; there is no default.
  * The backup's checksum is verified before anything is touched.
  * A non-empty target is refused unless --replace-existing is given (and
    confirmed by typing the database name, unless --yes).
  * pg_restore runs as ONE transaction: a failed restore leaves the target as it was.
  * Afterwards the restored row counts are compared with the counts recorded
    at backup time and the schema revision is checked against this app.

Connection details (host/user/password) come from the machine's .env.
"""

import argparse
import dataclasses
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.pool import NullPool

import data.models  # noqa: F401
from backup import settings
from backup.drives import find_backup_drives
from backup.errors import BackupError
from backup.pgtools import (
    ConnectionSettings,
    createdb_command,
    find_pg_tool,
    pg_restore_command,
    run_tool,
)
from backup.storage import BackupInfo, list_backups, load_info, sidecar_paths, verify_backup
from data.database import Base
from version import EXPECTED_SCHEMA_REVISION, SCHEMA_REVISIONS


@dataclass
class RestoreReport:
    target_db: str
    created_database: bool
    schema_revision: str | None
    row_counts: dict
    mismatches: list = field(default_factory=list)  # (table, expected, actual)
    schema_note: str | None = None
    warnings: list = field(default_factory=list)


# --- real database hooks (replaced by fakes in unit tests) ----------------------


def database_exists(conn: ConnectionSettings) -> bool:
    eng = create_engine(conn.sqlalchemy_url("postgres"), poolclass=NullPool)
    try:
        with eng.connect() as c:
            row = c.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": conn.database}
            ).first()
        return row is not None
    finally:
        eng.dispose()


def existing_tables(conn: ConnectionSettings) -> list[str]:
    eng = create_engine(conn.sqlalchemy_url(), poolclass=NullPool)
    try:
        return inspect(eng).get_table_names()
    finally:
        eng.dispose()


def summarize_database(conn: ConnectionSettings) -> tuple[str | None, dict]:
    """(alembic revision, {table: row count}) of the restored database."""
    eng = create_engine(conn.sqlalchemy_url(), poolclass=NullPool)
    try:
        with eng.connect() as c:
            names = set(inspect(c).get_table_names())
            counts = {
                t.name: c.execute(select(func.count()).select_from(t)).scalar_one()
                for t in Base.metadata.sorted_tables
                if t.name in names
            }
            revision = (
                c.execute(text("SELECT version_num FROM alembic_version")).scalar()
                if "alembic_version" in names
                else None
            )
        return revision, counts
    finally:
        eng.dispose()


# --- logic ------------------------------------------------------------------------


def describe_schema(revision: str | None) -> str | None:
    if not revision:
        return None
    if revision == EXPECTED_SCHEMA_REVISION:
        return "The backup's schema matches this version of the app."
    if revision in SCHEMA_REVISIONS and SCHEMA_REVISIONS.index(revision) < SCHEMA_REVISIONS.index(
        EXPECTED_SCHEMA_REVISION
    ):
        return "The backup is from an OLDER schema. Run 'alembic upgrade head' on the restored database."
    return "The backup is from a NEWER or unknown schema. Update the app before using this database."


def _load_and_verify(backup_file: Path, allow_unverified: bool) -> BackupInfo | None:
    if not backup_file.is_file():
        raise BackupError(f"Backup file not found: {backup_file}")
    manifest_path = sidecar_paths(backup_file)[1]
    if manifest_path.is_file():
        info = load_info(manifest_path)
        if info is None:
            if not allow_unverified:
                raise BackupError("The backup's manifest is unreadable. Refusing to restore.")
            return None
        verify_backup(info)  # raises BackupError if the file is damaged
        return info
    if not allow_unverified:
        raise BackupError(
            "This backup has no manifest (incomplete or interrupted). "
            "Use another backup, or pass --allow-unverified if you accept the risk."
        )
    return None


def restore_backup(
    backup_file: Path,
    *,
    target: ConnectionSettings,
    replace_existing: bool = False,
    allow_unverified: bool = False,
    runner=subprocess.run,
    find_tool=find_pg_tool,
    exists_fn=database_exists,
    tables_fn=existing_tables,
    summarize_fn=summarize_database,
) -> RestoreReport:
    backup_file = Path(backup_file)
    if not target.database:
        raise BackupError("A target database name is required.")

    info = _load_and_verify(backup_file, allow_unverified)

    created = False
    replace = False
    if not exists_fn(target):
        run_tool(createdb_command(find_tool("createdb"), target), target, runner=runner)
        created = True
    elif tables_fn(target):
        if not replace_existing:
            raise BackupError(
                f"Database '{target.database}' is not empty. Restore into a new/empty database, "
                "or pass --replace-existing to overwrite it."
            )
        replace = True

    run_tool(
        pg_restore_command(find_tool("pg_restore"), backup_file, target, replace=replace),
        target,
        runner=runner,
    )

    revision, counts = summarize_fn(target)
    report = RestoreReport(
        target_db=target.database,
        created_database=created,
        schema_revision=revision,
        row_counts=counts,
        schema_note=describe_schema(info.schema_revision if info else revision),
    )
    if info is None:
        report.warnings.append("Restored without verification (--allow-unverified).")
    else:
        for table, expected in sorted(info.row_counts.items()):
            actual = counts.get(table)
            if actual != expected:
                report.mismatches.append((table, expected, actual))
    return report


# --- command line -----------------------------------------------------------------


def _all_backups() -> list[BackupInfo]:
    found: list[BackupInfo] = []
    for drive in find_backup_drives():
        found += list_backups(drive.root / settings.BACKUP_DIR_NAME)
    return sorted(found, key=lambda i: i.created_at, reverse=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Restore a Health Center backup")
    parser.add_argument("--list", action="store_true", help="list backups on connected drives")
    parser.add_argument("--file", type=Path, help="path to a .dump file")
    parser.add_argument("--latest", action="store_true", help="use the newest backup on connected drives")
    parser.add_argument("--target-db", help="database to restore INTO (required)")
    parser.add_argument("--replace-existing", action="store_true")
    parser.add_argument("--allow-unverified", action="store_true")
    parser.add_argument("--yes", action="store_true", help="skip the typed confirmation")
    args = parser.parse_args(argv)

    if args.list:
        backups = _all_backups()
        for b in backups:
            print(f"{b.created_at.astimezone():%Y-%m-%d %H:%M}  {b.size_bytes / 1e6:8.1f} MB  {b.dump_path}")
        if not backups:
            print("No backups found on connected backup drives.")
        return 0

    if not args.target_db:
        parser.error("--target-db is required (there is deliberately no default)")
    if bool(args.file) == bool(args.latest):
        parser.error("give exactly one of --file or --latest")

    backup_file = args.file
    if args.latest:
        backups = _all_backups()
        if not backups:
            print("No backups found on connected backup drives.")
            return 1
        backup_file = backups[0].dump_path
        print(f"Using newest backup: {backup_file}")

    target = dataclasses.replace(ConnectionSettings.from_config(), database=args.target_db)

    if args.replace_existing and not args.yes:
        typed = input(f"This will OVERWRITE database '{args.target_db}'. Type its name to continue: ")
        if typed.strip() != args.target_db:
            print("Cancelled.")
            return 1

    try:
        report = restore_backup(
            backup_file,
            target=target,
            replace_existing=args.replace_existing,
            allow_unverified=args.allow_unverified,
        )
    except BackupError as exc:
        print(f"RESTORE FAILED: {exc}")
        return 1

    print(f"\nRestored into '{report.target_db}'" + (" (database created)" if report.created_database else ""))
    print(f"Schema revision: {report.schema_revision}")
    if report.schema_note:
        print(report.schema_note)
    print("Row counts:")
    for table, count in sorted(report.row_counts.items()):
        print(f"  {table:<16} {count}")
    for warning in report.warnings:
        print(f"WARNING: {warning}")
    if report.mismatches:
        print("\nCounts differ from backup time (small differences are normal if the clinic was open):")
        for table, expected, actual in report.mismatches:
            print(f"  {table}: backup said {expected}, restored {actual}")
    return 0


if __name__ == "__main__":
    sys.exit(main())