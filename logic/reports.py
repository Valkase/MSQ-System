"""
Financial reporting (task plan 2.2's last two items): queries filterable
by an arbitrary custom date range, plus per-doctor and center total
reports for that range. Read-only — nothing here writes to the database.

Aggregation is done via SQL SUM, not by pulling every row into Python.

Adjustments (logic/adjustments.py) are included: an adjustment counts in the
period in which it was RECORDED, never the original transaction's period, so
a past period's totals never change after the fact. transaction_count counts
transactions only (an adjustment isn't a new transaction).
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from data.models.adjustment import Adjustment
from data.models.doctor import Doctor
from data.models.transaction import Transaction
from data.models.user import User
from logic.dates import day_bounds_utc
from logic.permissions import Permission, require_permission


@dataclass(frozen=True)
class DoctorTotals:
    doctor_id: uuid.UUID
    doctor_name: str
    transaction_count: int
    total_amount: Decimal
    doctor_amount: Decimal
    center_amount: Decimal


@dataclass(frozen=True)
class CenterTotals:
    transaction_count: int
    total_amount: Decimal
    doctor_amount: Decimal
    center_amount: Decimal


_ZERO = Decimal("0.00")


def _adjustment_sums_by_doctor(session: Session, start_dt, end_dt) -> dict:
    rows = (
        session.query(
            Transaction.doctor_id,
            func.sum(Adjustment.total_amount),
            func.sum(Adjustment.doctor_amount),
            func.sum(Adjustment.center_amount),
        )
        .select_from(Adjustment)
        .join(Transaction, Transaction.id == Adjustment.transaction_id)
        .filter(Adjustment.created_at >= start_dt, Adjustment.created_at <= end_dt)
        .group_by(Transaction.doctor_id)
        .all()
    )
    return {r[0]: (r[1], r[2], r[3]) for r in rows}


def doctor_totals_for_range(
    session: Session,
    *,
    start_date: date,
    end_date: date,
    acting_user: User,
    include_inactive_doctors: bool = True,
) -> list[DoctorTotals]:
    """
    Per-doctor totals (task plan 2.2) for an inclusive [start_date,
    end_date] range: transaction count, total billed, and each doctor's
    share vs. the center's share, net of adjustments recorded in the range.
    Requires VIEW_REPORTS (task plan 2.4).

    Uses a LEFT JOIN from Doctor so a doctor with zero transactions in
    the range still appears with zeroed totals.
    """
    require_permission(acting_user, Permission.VIEW_REPORTS)

    start_dt, end_dt = day_bounds_utc(start_date, end_date)

    q = (
        session.query(
            Doctor.id,
            Doctor.name,
            func.count(Transaction.id),
            func.coalesce(func.sum(Transaction.total_amount), _ZERO),
            func.coalesce(func.sum(Transaction.doctor_amount), _ZERO),
            func.coalesce(func.sum(Transaction.center_amount), _ZERO),
        )
        .outerjoin(
            Transaction,
            (Transaction.doctor_id == Doctor.id)
            & (Transaction.created_at >= start_dt)
            & (Transaction.created_at <= end_dt),
        )
        .group_by(Doctor.id, Doctor.name)
        .order_by(Doctor.name.asc())
    )
    if not include_inactive_doctors:
        q = q.filter(Doctor.active.is_(True))

    adjustments = _adjustment_sums_by_doctor(session, start_dt, end_dt)
    zero = (_ZERO, _ZERO, _ZERO)

    results = []
    for row in q.all():
        adj_total, adj_doctor, adj_center = adjustments.get(row[0], zero)
        results.append(
            DoctorTotals(
                doctor_id=row[0],
                doctor_name=row[1],
                transaction_count=row[2],
                total_amount=row[3] + adj_total,
                doctor_amount=row[4] + adj_doctor,
                center_amount=row[5] + adj_center,
            )
        )
    return results


def center_totals_for_range(
    session: Session, *, start_date: date, end_date: date, acting_user: User
) -> CenterTotals:
    """
    Clinic-wide totals (task plan 2.2) for an inclusive [start_date,
    end_date] range, across all doctors combined, net of adjustments
    recorded in the range. Requires VIEW_REPORTS (task plan 2.4).
    """
    require_permission(acting_user, Permission.VIEW_REPORTS)

    start_dt, end_dt = day_bounds_utc(start_date, end_date)

    count, total, doctor_sum, center_sum = (
        session.query(
            func.count(Transaction.id),
            func.coalesce(func.sum(Transaction.total_amount), _ZERO),
            func.coalesce(func.sum(Transaction.doctor_amount), _ZERO),
            func.coalesce(func.sum(Transaction.center_amount), _ZERO),
        )
        .filter(Transaction.created_at >= start_dt, Transaction.created_at <= end_dt)
        .one()
    )
    adj_total, adj_doctor, adj_center = (
        session.query(
            func.coalesce(func.sum(Adjustment.total_amount), _ZERO),
            func.coalesce(func.sum(Adjustment.doctor_amount), _ZERO),
            func.coalesce(func.sum(Adjustment.center_amount), _ZERO),
        )
        .filter(Adjustment.created_at >= start_dt, Adjustment.created_at <= end_dt)
        .one()
    )
    return CenterTotals(
        transaction_count=count,
        total_amount=total + adj_total,
        doctor_amount=doctor_sum + adj_doctor,
        center_amount=center_sum + adj_center,
    )