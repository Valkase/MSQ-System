"""Tests for logic/reports.py and the local-calendar-day bounds in logic/dates.py."""

from datetime import date, time
from decimal import Decimal

import pytest

from logic import doctors, patients, reports, transactions
from logic.dates import day_bounds_utc
from logic.errors import ValidationError


def _setup(session, admin, receptionist):
    dr_a = doctors.create_doctor(
        session, name="Dr. Ahmed Smith", standard_percentage=Decimal("60.00"), acting_user=admin
    )
    dr_b = doctors.create_doctor(
        session, name="Dr. Sara Lee", standard_percentage=Decimal("50.00"), acting_user=admin
    )  # never gets a transaction
    patient = patients.create_patient(
        session, full_name="Mona Youssef", phone="0100000001", acting_user=receptionist
    )
    for amount in ("500.00", "250.00"):
        transactions.record_transaction(
            session,
            patient_id=patient.id,
            doctor_id=dr_a.id,
            total_amount=Decimal(amount),
            acting_user=receptionist,
        )
    return dr_a, dr_b


def test_center_totals_sum_everything_recorded_today(session, admin_user, receptionist_user):
    _setup(session, admin_user, receptionist_user)
    today = date.today()

    totals = reports.center_totals_for_range(
        session, start_date=today, end_date=today, acting_user=receptionist_user
    )

    assert totals.transaction_count == 2
    assert totals.total_amount == Decimal("750.00")
    assert totals.doctor_amount == Decimal("450.00")
    assert totals.center_amount == Decimal("300.00")


def test_doctor_totals_include_doctors_with_no_transactions(session, admin_user, receptionist_user):
    _setup(session, admin_user, receptionist_user)
    today = date.today()

    rows = reports.doctor_totals_for_range(
        session, start_date=today, end_date=today, acting_user=receptionist_user
    )

    assert [r.doctor_name for r in rows] == ["Dr. Ahmed Smith", "Dr. Sara Lee"]
    smith, lee = rows
    assert (smith.transaction_count, smith.total_amount) == (2, Decimal("750.00"))
    assert smith.doctor_amount == Decimal("450.00")
    assert smith.center_amount == Decimal("300.00")
    assert (lee.transaction_count, lee.total_amount) == (0, Decimal("0.00"))


def test_range_outside_the_transactions_gives_zero_totals(session, admin_user, receptionist_user):
    _setup(session, admin_user, receptionist_user)

    totals = reports.center_totals_for_range(
        session,
        start_date=date(2020, 1, 1),
        end_date=date(2020, 1, 31),
        acting_user=receptionist_user,
    )

    assert totals.transaction_count == 0
    assert totals.total_amount == Decimal("0.00")


def test_end_before_start_is_rejected(session, receptionist_user):
    with pytest.raises(ValidationError):
        reports.center_totals_for_range(
            session,
            start_date=date(2026, 10, 5),
            end_date=date(2026, 10, 4),
            acting_user=receptionist_user,
        )


def test_day_bounds_are_local_calendar_days():
    day = date(2026, 10, 5)
    start, end = day_bounds_utc(day, day)

    assert start.tzinfo is not None and end.tzinfo is not None
    local_start, local_end = start.astimezone(), end.astimezone()
    assert local_start.date() == day and local_start.time() == time.min
    assert local_end.date() == day and local_end.time() == time.max