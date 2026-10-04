"""
Adjustment model — a signed, immutable correction to a Transaction.

Notes:
- Transactions are never edited (see data/models/transaction.py). A mistake
  is corrected by adding an Adjustment that references the original.
- `total_amount` is signed and never zero: negative reduces the transaction
  (a void is an adjustment of minus the current net), positive increases it.
- `doctor_amount` / `center_amount` are the signed CHANGE to each share,
  computed in logic/adjustments.py from the original transaction's saved
  percentage — so a later rate change never alters corrections.
- Like Transaction, there is no update path and no soft-delete flag; the row
  (recorded_by, created_at, reason) is its own accountability record.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from data.database import Base


class Adjustment(Base):
    __tablename__ = "adjustments"
    __table_args__ = (
        CheckConstraint("total_amount <> 0", name="ck_adjustments_amount_nonzero"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transactions.id"), nullable=False, index=True
    )
    recorded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )

    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    doctor_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    center_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    reason: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self) -> str:
        return (
            f"<Adjustment transaction_id={self.transaction_id} "
            f"total_amount={self.total_amount}>"
        )