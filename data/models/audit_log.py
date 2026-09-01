"""
AuditLog model — append-only trail of changes made through the
"update and log" function (logic/audit.py, not built yet).

Notes:
- This table is written to, never updated or deleted — it's the audit
  trail itself, so it must be at least as immutable as what it's logging.
- `table_name` + `record_id` together identify which row changed, without
  needing a separate FK/table per entity type (patients, doctors, etc.
  all log through this one shared table).
- `old_values` / `new_values` store the changed fields as JSON — flexible
  enough to log a partial update on any model without needing a column
  per possible field.
- Transactions are explicitly EXCLUDED from ever appearing here as an
  "edit" — they're append-only themselves and never go through the
  update-and-log path (see data/models/transaction.py).
- `changed_by` links to the User who made the change, for accountability.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from data.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    table_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    changed_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    # Field-level diff of the change. Nullable old_values covers row creation
    # (nothing existed beforehand to snapshot).
    old_values: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    new_values: Mapped[dict] = mapped_column(JSONB, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self) -> str:
        return f"<AuditLog table_name={self.table_name!r} record_id={self.record_id} changed_by={self.changed_by}>"