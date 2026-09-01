"""
Attachment model.

Notes:
- Stores a FILE PATH REFERENCE ONLY — never the file's actual bytes, per
  the design decision to keep attachments as local/network filesystem
  references rather than blobs in the database.
- `file_path` should be a shared/network path convention so a file
  attached at one desk is visible from another (this convention itself
  is still an open decision in the task plan's "Open decisions" list —
  revisit this field's expected format once that's settled).
- Opening an attachment (resolving the path + launching the OS's default
  viewer, and handling a path that no longer resolves) is logic-layer
  behavior (logic/attachments.py, not built yet) — this model just stores
  the reference.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from data.database import Base


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False, index=True
    )

    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self) -> str:
        return f"<Attachment patient_id={self.patient_id} file_path={self.file_path!r}>"