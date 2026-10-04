"""
Transaction corrections (task plan 2.2's adjustment mechanism).

A saved Transaction is never edited. A mistake is corrected by recording an
Adjustment: a signed change to the transaction's total. The new net split is
calculated once, from the ORIGINAL transaction's saved percentage, and the
adjustment stores the difference — so net doctor/center amounts always equal
what a fresh transaction for the net total would have produced, and a void
reverses the exact original amounts. Decimal throughout.

Rules: admin-only (ADJUST_TRANSACTION); a reason is required; the net total
can never go below zero; there is no update/delete function for an adjustment.
Wrong patient/doctor is fixed by voiding and re-entering, never by editing.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from data.models.adjustment import Adjustment
from data.models.doctor import Doctor
from data.models.patient import Patient
from data.models.transaction import Transaction
from data.models.user import User
from i18n import format_currency, t
from logic.errors import NotFoundError, ValidationError
from logic.permissions import Permission, require_permission
from logic.transactions import calculate_split
from logic.validation import validate_required_text, validate_signed_amount

_ZERO = Decimal("0.00")


def calculate_adjustment(
    doctor_percentage: Decimal,
    current_total: Decimal,
    current_doctor: Decimal,
    current_center: Decimal,
    change: Decimal,
) -> tuple[Decimal, Decimal, Decimal]:
    """
    Pure function (no I/O), also used by the GUI's live preview. Given the
    CURRENT net position of a transaction and a signed change to its total,
    returns (total_change, doctor_change, center_change). Raises
    ValidationError if the change is invalid or would make the net total negative.
    """
    change = validate_signed_amount(change, "fields.adjustment_amount")
    new_total = current_total + change
    if new_total < 0:
        raise ValidationError(t("adjustments.exceeds_net", net=format_currency(current_total)))
    if new_total == 0:
        new_doctor = new_center = _ZERO
    else:
        new_doctor, new_center = calculate_split(new_total, doctor_percentage)
    return change, new_doctor - current_doctor, new_center - current_center


def record_adjustment(
    session: Session,
    *,
    transaction_id: uuid.UUID,
    amount_change: Decimal,
    reason: str,
    acting_user: User,
) -> Adjustment:
    """Record a signed correction to a transaction. Admin-only. Commits on success."""
    require_permission(acting_user, Permission.ADJUST_TRANSACTION)

    # Lock the transaction row so two admins adjusting at once can't both
    # pass the "net can't go negative" check (PostgreSQL; SQLite ignores it).
    txn = (
        session.query(Transaction)
        .filter(Transaction.id == transaction_id)
        .with_for_update()
        .first()
    )
    if txn is None:
        raise NotFoundError(t("transactions.not_found", transaction_id=transaction_id))

    clean_reason = validate_required_text(reason, "fields.reason", max_length=2000)

    adj_total, adj_doctor, adj_center = (
        session.query(
            func.coalesce(func.sum(Adjustment.total_amount), _ZERO),
            func.coalesce(func.sum(Adjustment.doctor_amount), _ZERO),
            func.coalesce(func.sum(Adjustment.center_amount), _ZERO),
        )
        .filter(Adjustment.transaction_id == txn.id)
        .one()
    )

    total_change, doctor_change, center_change = calculate_adjustment(
        txn.doctor_percentage,
        txn.total_amount + adj_total,
        txn.doctor_amount + adj_doctor,
        txn.center_amount + adj_center,
        amount_change,
    )

    adjustment = Adjustment(
        transaction_id=txn.id,
        recorded_by=acting_user.id,
        total_amount=total_change,
        doctor_amount=doctor_change,
        center_amount=center_change,
        reason=clean_reason,
    )
    session.add(adjustment)
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise
    return adjustment


@dataclass(frozen=True)
class AdjustmentRow:
    """Plain-value view of an adjustment plus the names the GUI displays."""

    id: uuid.UUID
    created_at: datetime
    transaction_id: uuid.UUID
    patient_name: str
    doctor_name: str
    total_amount: Decimal
    doctor_amount: Decimal
    center_amount: Decimal
    reason: str
    recorded_by_name: str


def list_adjustment_rows(
    session: Session,
    *,
    acting_user: User,
    patient_id: uuid.UUID | None = None,
    limit: int = 100,
) -> list[AdjustmentRow]:
    """Newest-first adjustments with names joined in. Admin-only (ADJUST_TRANSACTION)."""
    require_permission(acting_user, Permission.ADJUST_TRANSACTION)

    q = (
        session.query(Adjustment, Patient.full_name, Doctor.name, User.username)
        .join(Transaction, Transaction.id == Adjustment.transaction_id)
        .join(Patient, Patient.id == Transaction.patient_id)
        .join(Doctor, Doctor.id == Transaction.doctor_id)
        .join(User, User.id == Adjustment.recorded_by)
    )
    if patient_id is not None:
        q = q.filter(Transaction.patient_id == patient_id)
    rows = q.order_by(Adjustment.created_at.desc()).limit(limit).all()

    return [
        AdjustmentRow(
            id=adj.id,
            created_at=adj.created_at,
            transaction_id=adj.transaction_id,
            patient_name=patient_name,
            doctor_name=doctor_name,
            total_amount=adj.total_amount,
            doctor_amount=adj.doctor_amount,
            center_amount=adj.center_amount,
            reason=adj.reason,
            recorded_by_name=username,
        )
        for adj, patient_name, doctor_name, username in rows
    ]