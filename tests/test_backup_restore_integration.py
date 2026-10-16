"""
Phase 7 restore test, automated: real pg_dump -> fake "flash drive" folder ->
real pg_restore into a NEW database -> compare the data.

Skipped unless TEST_DATABASE_URL points at a throwaway PostgreSQL database
whose name contains "test" (the role needs the CREATEDB privilege), and the
PostgreSQL client tools can be found (PATH or PG_BIN_DIR).
"""

import dataclasses
import os
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

TEST_DB_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not TEST_DB_URL, reason="set TEST_DATABASE_URL to run")

from backup import backup_job, restore, settings  # noqa: E402
from backup.drives import initialize_drive  # noqa: E402
from backup.errors import BackupError  # noqa: E402
from backup.pgtools import ConnectionSettings, dump_database, find_pg_tool, run_tool  # noqa: E402
from backup.storage import list_backups, verify_backup  # noqa: E402
from data.database import Base  # noqa: E402
from data.models.transaction import Transaction  # noqa: E402
from data.models.user import ROLE_ADMIN, ROLE_RECEPTIONIST, User  # noqa: E402
from logic import doctors, patients, transactions  # noqa: E402


def test_backup_then_restore_roundtrip(tmp_path):
    import data.models  # noqa: F401

    try:
        find_pg_tool("pg_dump"), find_pg_tool("pg_restore"), find_pg_tool("createdb"), find_pg_tool("dropdb")
    except BackupError as exc:
        pytest.skip(str(exc))

    source = ConnectionSettings.from_url(TEST_DB_URL)
    assert "test" in (source.database or "").lower()
    restored = dataclasses.replace(source, database=source.database + "_restored")

    engine = create_engine(TEST_DB_URL, future=True)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, future=True)

    with Session() as s:
        admin = User(username="admin1", password_hash="x", role=ROLE_ADMIN, active=True)
        rec = User(username="rec1", password_hash="x", role=ROLE_RECEPTIONIST, active=True)
        s.add_all([admin, rec])
        s.flush()
        doctor = doctors.create_doctor(
            s, name="Dr. Ahmed Smith", standard_percentage=Decimal("60.00"), acting_user=admin
        )
        patient = patients.create_patient(
            s, full_name="Mona Youssef", phone="0100000001", acting_user=rec
        )
        txn = transactions.record_transaction(
            s,
            patient_id=patient.id,
            doctor_id=doctor.id,
            total_amount=Decimal("500.00"),
            acting_user=rec,
        )
        txn_id = txn.id

    drive_root = tmp_path / "flash"
    drive_root.mkdir()
    drive = initialize_drive(drive_root, "test drive")

    result = backup_job.run_backup(
        Session,
        force=True,
        now=datetime.now(timezone.utc),
        find_drives=lambda: [drive],
        dump=lambda dest: dump_database(dest, source),
        schema_revision=lambda: None,
    )
    assert result.status == backup_job.RESULT_OK, result.message
    (info,) = list_backups(drive_root / settings.BACKUP_DIR_NAME)
    verify_backup(info)

    try:
        report = restore.restore_backup(info.dump_path, target=restored)
        assert report.created_database
        assert report.mismatches == []
        assert report.row_counts["transactions"] == 1
        assert report.row_counts["patients"] == 1

        eng2 = create_engine(restored.sqlalchemy_url(), future=True)
        with sessionmaker(bind=eng2)() as s2:
            row = s2.execute(select(Transaction).where(Transaction.id == txn_id)).scalar_one()
            assert (row.total_amount, row.doctor_amount, row.center_amount) == (
                Decimal("500.00"),
                Decimal("300.00"),
                Decimal("200.00"),
            )
        eng2.dispose()

        # Restoring over a non-empty database must be refused without --replace-existing.
        with pytest.raises(BackupError, match="not empty"):
            restore.restore_backup(info.dump_path, target=restored)
    finally:
        run_tool([find_pg_tool("dropdb"), "--if-exists", "--no-password",
                  "--host", restored.host or "localhost", "--username", restored.user or "postgres",
                  restored.database], restored)
        Base.metadata.drop_all(engine)
        engine.dispose()