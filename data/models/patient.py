"""
Patient model.

Notes:
- `active` supports soft-disabling ("deactivate") a patient. Hard deletion
  is only allowed when a patient has zero transactions (enforced in the
  logic layer, see logic/patients.py — not built yet). Deactivation is the
  fallback whenever deletion isn't allowed.
- `phone` and `email` are validated for format in the logic layer, not
  here — the model itself just stores them.
- `email` is nullable (phone is treated as the more reliable required
  contact method for this clinic); adjust if the client wants email
  required too.
"""

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from data.database import Base


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    full_name: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    phone: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(150), nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)

    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self) -> str:
        return f"<Patient full_name={self.full_name!r} phone={self.phone!r} active={self.active}>"