"""
Financial logic (task plan 2.2) — the split calculator and transaction
recording. Decimal throughout, never float (design doc Section 3).

IMMUTABILITY (task plan 2.2 "Enforce transaction immutability at the
logic layer"): this module deliberately exposes no update or delete
function for a saved Transaction. That absence *is* the enforcement —
there is no code path anywhere in this module (or any other) that can
alter a transaction once record_transaction() returns. Do not add one.
Corrections go through a separate adjustment mechanism (see the note in
record_adjustment_placeholder() below) once that's designed.

Transactions are also NOT routed through logic.audit.update_and_log or
record_creation. This matches data/models/transaction.py's docstring:
the row itself (recorded_by, created_at, and the frozen percentage/amount
snapshot) already gives full accountability for a create-only record, and
audit_log's "edit history" concept doesn't apply to something that's
never edited. See logic/audit.py's module docstring for the audit_log
side of this same rule.
"""

import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from data.models.doctor import Doctor
from data.models.patient import Patient
from data.models.transaction import Transaction
from logic.dates import day_bounds_utc
from logic.errors import NotFoundError, ValidationError
from logic.validation import validate_amount, validate_optional_text, validate_percentage

TWO_PLACES = Decimal("0.01")


def calculate_split(total_amount: Decimal, doctor_percentage: Decimal) -> tuple[Decimal, Decimal]:
    """
    The split calculator (task plan 2.2). Pure function, no I/O — given a
    total and the doctor's percentage, returns (doctor_amount, center_amount).

    Rounding rule (explicit, per task plan 2.2 "decide who absorbs
    rounding remainders"): doctor_amount is computed first and rounded to
    2 decimal places using ROUND_HALF_UP (standard "round half up"
    financial rounding, e.g. 0.125 -> 0.13). center_amount is then
    total_amount - doctor_amount, NOT its own independent rounding of
    (100 - doctor_percentage)% — this guarantees doctor_amount +
    center_amount always equals total_amount exactly, with the center
    absorbing the (at most $0.01) rounding remainder. This mirrors the
    convention already used in data/seed.py.
    """
    total_amount = validate_amount(total_amount, "Total amount")
    doctor_percentage = validate_percentage(doctor_percentage, "Doctor percentage")

    doctor_amount = (total_amount * doctor_percentage / Decimal(100)).quantize(
        TWO_PLACES, rounding=ROUND_HALF_UP
    )
    center_amount = total_amount - doctor_amount
    return doctor_amount, center_amount


def record_transaction(
    session: Session,
    *,
    patient_id: uuid.UUID,
    doctor_id: uuid.UUID,
    total_amount: Decimal,
    recorded_by: uuid.UUID,
    description: str | None = None,
) -> Transaction:
    """
    Record a new transaction (task plan 2.2): validates input, snapshots
    the doctor's CURRENT standard_percentage onto the transaction (so a
    later rate change never alters this record — see Transaction's
    docstring), computes the split, saves, and returns it.

    Requires the patient to exist (any patient — active or deactivated;
    deactivation doesn't erase the ability to bill an already-scheduled
    service) and the doctor to exist and be active (an inactive doctor
    shouldn't be receiving new transactions).
    """
    patient = session.get(Patient, patient_id)
    if patient is None:
        raise NotFoundError(f"No patient found with id {patient_id}.")

    doctor = session.get(Doctor, doctor_id)
    if doctor is None:
        raise NotFoundError(f"No doctor found with id {doctor_id}.")
    if not doctor.active:
        raise ValidationError(
            f"Doctor '{doctor.name}' is not active and cannot be assigned a new transaction."
        )

    clean_amount = validate_amount(total_amount, "Total amount")
    clean_description = validate_optional_text(description, "Description", max_length=5000)

    doctor_percentage = doctor.standard_percentage
    center_percentage = Decimal(100) - doctor_percentage
    doctor_amount, center_amount = calculate_split(clean_amount, doctor_percentage)

    transaction = Transaction(
        patient_id=patient_id,
        doctor_id=doctor_id,
        recorded_by=recorded_by,
        total_amount=clean_amount,
        doctor_percentage=doctor_percentage,
        center_percentage=center_percentage,
        doctor_amount=doctor_amount,
        center_amount=center_amount,
        description=clean_description,
    )
    session.add(transaction)
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise
    return transaction


def get_transaction(session: Session, transaction_id: uuid.UUID) -> Transaction:
    """Fetch a single transaction by id, or raise NotFoundError."""
    transaction = session.get(Transaction, transaction_id)
    if transaction is None:
        raise NotFoundError(f"No transaction found with id {transaction_id}.")
    return transaction


def list_transactions(
    session: Session,
    *,
    patient_id: uuid.UUID | None = None,
    doctor_id: uuid.UUID | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[Transaction]:
    """
    List transactions, optionally filtered by patient, doctor, and/or an
    inclusive [start_date, end_date] calendar range. All filters are
    optional and combine with AND — this is the shared building block
    behind the patient billing-history view and logic/reports.py.
    """
    q = session.query(Transaction)
    if patient_id is not None:
        q = q.filter(Transaction.patient_id == patient_id)
    if doctor_id is not None:
        q = q.filter(Transaction.doctor_id == doctor_id)
    if start_date is not None and end_date is not None:
        start_dt, end_dt = day_bounds_utc(start_date, end_date)
        q = q.filter(Transaction.created_at >= start_dt, Transaction.created_at <= end_dt)
    elif start_date is not None or end_date is not None:
        raise ValidationError("start_date and end_date must both be provided, or neither.")
    return q.order_by(Transaction.created_at.desc()).all()


# ---------------------------------------------------------------------------
# Adjustments / corrections — OPEN DESIGN ITEM, not built.
# ---------------------------------------------------------------------------
#
# Task plan 2.2 and design doc Section 9 both flag the transaction
# correction mechanism as an item to confirm with the client before
# building, since it affects the schema (a new adjustment entry type
# referencing the original transaction) and the Phase 4 UI (a dedicated
# adjustment entry screen). Rather than guess at that shape here, this is
# deliberately left unbuilt. When it's ready to design, the open
# questions are things like: does an adjustment need its own table, or a
# nullable `adjusts_transaction_id` FK on Transaction itself (which would
# mean Transaction is no longer *fully* create-only); can an adjustment
# be negative (a correction/refund) as well as positive; does it need its
# own approval/reason field beyond `description`.