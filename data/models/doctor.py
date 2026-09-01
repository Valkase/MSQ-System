"""
Doctor model.

Notes:
- `standard_percentage` is the doctor's standing/annual split rate — the
  DEFAULT used when a new transaction is recorded. It is NOT touched
  retroactively: Transaction stores its own copied percentage at the time
  it's created, so changing this value later never alters past records
  (see data/models/transaction.py, built next).
- Uses Numeric (not Float) so percentages stay exact — required by the
  "Decimal throughout, no floats" rule in the financial logic module.
- `active` supports soft-disabling a doctor without deleting their history.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from data.database import Base


class Doctor(Base):
    __tablename__ = "doctors"
    __table_args__ = (
        CheckConstraint(
            "standard_percentage >= 0 AND standard_percentage <= 100",
            name="ck_doctors_percentage_range",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)

    # The doctor's share, e.g. 60.00 means 60%. Center's share is derived
    # (100 - standard_percentage) rather than stored, to avoid the two
    # numbers ever drifting out of sync.
    standard_percentage: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False
    )

    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self) -> str:
        return (
            f"<Doctor name={self.name!r} standard_percentage={self.standard_percentage} "
            f"active={self.active}>"
        )