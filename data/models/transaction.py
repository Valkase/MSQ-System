"""
Transaction model — financial records. IMMUTABLE by design.

Notes:
- `doctor_percentage` / `center_percentage` are COPIED from the doctor at
  the moment the transaction is created (not a live reference to Doctor).
  This means a later change to Doctor.standard_percentage never alters
  past transactions — each row is a frozen snapshot of the split that
  actually applied at the time.
- `doctor_amount` / `center_amount` are also stored (not recalculated on
  the fly) so the historical record is self-contained and independently
  auditable, even if the split-calculation logic changes later.
- All money/percentage fields use Numeric, never Float — required by the
  "Decimal throughout" rule in the financial logic module.
- Immutability is enforced in the LOGIC layer (logic/transactions.py):
  no update/delete function will exist for a saved transaction. This
  model intentionally has no soft-delete/active flag — a transaction is
  never edited or hidden, only ever corrected via a future separate
  "adjustment" entry that references the original (open design item,
  not built yet).
- `recorded_by` links to the User (receptionist/admin) who entered it,
  for accountability — separate from the doctor who performed the service.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from data.database import Base


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("total_amount > 0", name="ck_transactions_amount_positive"),
        CheckConstraint(
            "doctor_percentage >= 0 AND doctor_percentage <= 100",
            name="ck_transactions_doctor_pct_range",
        ),
        CheckConstraint(
            "center_percentage >= 0 AND center_percentage <= 100",
            name="ck_transactions_center_pct_range",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False, index=True
    )
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doctors.id"), nullable=False, index=True
    )
    recorded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )

    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    # Snapshot of the split at the moment of creation — see module docstring.
    doctor_percentage: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    center_percentage: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    doctor_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    center_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Deliberately named created_at, not updated_at — transactions never update.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self) -> str:
        return (
            f"<Transaction id={self.id} total_amount={self.total_amount} "
            f"doctor_amount={self.doctor_amount} center_amount={self.center_amount}>"
        )