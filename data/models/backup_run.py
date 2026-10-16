"""
BackupRun — one row per backup attempt (per drive), written by backup/backup_job.py.

System bookkeeping, deliberately NOT routed through update_and_log: the job
inserts rows directly and never edits them. The app reads the newest rows to
warn an admin when backups are overdue (logic/backup_status.py).
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from data.database import Base

STATUS_OK = "ok"
STATUS_FAILED = "failed"
STATUS_DRIVE_MISSING = "drive_missing"
VALID_STATUSES = (STATUS_OK, STATUS_FAILED, STATUS_DRIVE_MISSING)


class BackupRun(Base):
    __tablename__ = "backup_runs"
    __table_args__ = (
        CheckConstraint(f"status IN {VALID_STATUSES}", name="ck_backup_runs_status_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    drive_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<BackupRun status={self.status!r} started_at={self.started_at} drive_id={self.drive_id!r}>"