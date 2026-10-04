"""Tests for logic/adjustments.py and how adjustments flow into rows and reports."""

from datetime import date
from decimal import Decimal

import pytest

from i18n import set_locale
from logic import adjustments, doctors, patients, reports, transactions
from logic.errors import NotFoundError, PermissionDeniedError, ValidationError


def _setup(session, admin, receptionist, amount="500.00", pct="60.00"):
    doctor = doctors.create_doctor(
        session, name="Dr. Ahmed Smith", standard_percentage=Decimal(pct), acting_user=admin
    )
    patient = patients.create_patient(
        session, full_name="Mona Youssef", phone="0100000001", acting_user=receptionist
    )
    txn = transactions.record_transaction(
        session,
        patient_id=patient.id,
        doctor_id=doctor.id,
        total_amount=Decimal(amount),
        acting_user=receptionist,
    )
    return doctor, patient, txn


def _adjust(session, admin, txn, change, reason="Typo"):
    return adjustments.record_adjustment(
        session,
        transaction_id=txn.id,
        amount_change=Decimal(change),
        reason=reason,
        acting_user=admin,
    )


def test_void_reverses_the_exact_original_amounts(session, admin_user, receptionist_user):
    _, _, txn = _setup(session, admin_user, receptionist_user)

    adj = _adjust(session, admin_user, txn, "-500")

    assert adj.total_amount == Decimal("-500")
    assert adj.doctor_amount == Decimal("-300.00")
    assert adj.center_amount == Decimal("-200.00")


def test_partial_correction_uses_the_original_percentage(session, admin_user, receptionist_user):
    doctor, _, txn = _setup(session, admin_user, receptionist_user)
    # A later rate change must not affect the correction.
    doctors.update_doctor_percentage(
        session, doctor_id=doctor.id, new_percentage=Decimal("70.00"), acting_user=admin_user
    )

    adj = _adjust(session, admin_user, txn, "-100")  # net 500 -> 400 at 60%: 240 / 160

    assert adj.doctor_amount == Decimal("-60.00")
    assert adj.center_amount == Decimal("-40.00")


def test_positive_adjustment_increases_the_net(session, admin_user, receptionist_user):
    _, _, txn = _setup(session, admin_user, receptionist_user)

    adj = _adjust(session, admin_user, txn, "100")  # 600 at 60%: 360 / 240

    assert adj.doctor_amount == Decimal("60.00")
    assert adj.center_amount == Decimal("40.00")


def test_calculate_adjustment_keeps_net_split_consistent_when_rounding():
    # 10.05 at 50%: doctor 5.025 -> 5.03 (half up), center 5.02. Net 10.00 -> 5.00 / 5.00.
    total, doctor, center = adjustments.calculate_adjustment(
        Decimal("50.00"), Decimal("10.05"), Decimal("5.03"), Decimal("5.02"), Decimal("-0.05")
    )
    assert total == Decimal("-0.05")
    assert doctor == Decimal("-0.03")
    assert center == Decimal("-0.02")


def test_net_total_can_never_go_negative(session, admin_user, receptionist_user):
    _, _, txn = _setup(session, admin_user, receptionist_user)

    with pytest.raises(ValidationError):
        _adjust(session, admin_user, txn, "-500.01")

    _adjust(session, admin_user, txn, "-200")
    with pytest.raises(ValidationError):  # only 300 left now
        _adjust(session, admin_user, txn, "-400")


@pytest.mark.parametrize("bad", ["0", "NaN", "1.234"])
def test_invalid_changes_are_rejected(session, admin_user, receptionist_user, bad):
    _, _, txn = _setup(session, admin_user, receptionist_user)
    with pytest.raises(ValidationError):
        _adjust(session, admin_user, txn, bad)


def test_float_change_is_rejected(session, admin_user, receptionist_user):
    _, _, txn = _setup(session, admin_user, receptionist_user)
    with pytest.raises(ValidationError):
        adjustments.record_adjustment(
            session,
            transaction_id=txn.id,
            amount_change=-1.5,
            reason="x",
            acting_user=admin_user,
        )


def test_reason_is_required(session, admin_user, receptionist_user):
    _, _, txn = _setup(session, admin_user, receptionist_user)
    with pytest.raises(ValidationError):
        _adjust(session, admin_user, txn, "-10", reason="   ")


def test_only_admins_can_adjust(session, admin_user, receptionist_user):
    _, _, txn = _setup(session, admin_user, receptionist_user)
    with pytest.raises(PermissionDeniedError):
        _adjust(session, receptionist_user, txn, "-10")


def test_unknown_transaction_raises_not_found(session, admin_user):
    import uuid

    with pytest.raises(NotFoundError):
        adjustments.record_adjustment(
            session,
            transaction_id=uuid.uuid4(),
            amount_change=Decimal("-1"),
            reason="x",
            acting_user=admin_user,
        )


def test_rows_expose_the_adjusted_totals(session, admin_user, receptionist_user):
    _, _, txn = _setup(session, admin_user, receptionist_user)
    _adjust(session, admin_user, txn, "-100")
    _adjust(session, admin_user, txn, "-50")

    (row,) = transactions.list_transaction_rows(session, acting_user=receptionist_user)

    assert row.total_amount == Decimal("500.00")  # the original is untouched
    assert row.adjusted_total == Decimal("-150.00")
    assert row.total_amount + row.adjusted_total == Decimal("350.00")
    assert row.doctor_amount + row.adjusted_doctor == Decimal("210.00")  # 60% of 350
    assert row.center_amount + row.adjusted_center == Decimal("140.00")


def test_adjustment_rows_include_names_and_reason(session, admin_user, receptionist_user):
    _, _, txn = _setup(session, admin_user, receptionist_user)
    _adjust(session, admin_user, txn, "-100", reason="Wrong amount typed")

    (row,) = adjustments.list_adjustment_rows(session, acting_user=admin_user)

    assert row.patient_name == "Mona Youssef"
    assert row.doctor_name == "Dr. Ahmed Smith"
    assert row.reason == "Wrong amount typed"
    assert row.recorded_by_name == "admin1"

    with pytest.raises(PermissionDeniedError):
        adjustments.list_adjustment_rows(session, acting_user=receptionist_user)


def test_reports_include_adjustments(session, admin_user, receptionist_user):
    doctor, _, txn = _setup(session, admin_user, receptionist_user)
    _adjust(session, admin_user, txn, "-100")
    today = date.today()

    center = reports.center_totals_for_range(
        session, start_date=today, end_date=today, acting_user=receptionist_user
    )
    (doctor_row,) = reports.doctor_totals_for_range(
        session, start_date=today, end_date=today, acting_user=receptionist_user
    )

    assert center.transaction_count == 1  # an adjustment is not a new transaction
    assert center.total_amount == Decimal("400.00")
    assert center.doctor_amount == Decimal("240.00")
    assert center.center_amount == Decimal("160.00")
    assert doctor_row.total_amount == Decimal("400.00")
    assert doctor_row.doctor_amount == Decimal("240.00")


def test_voided_transaction_nets_to_zero_in_reports(session, admin_user, receptionist_user):
    _, _, txn = _setup(session, admin_user, receptionist_user)
    _adjust(session, admin_user, txn, "-500")
    today = date.today()

    center = reports.center_totals_for_range(
        session, start_date=today, end_date=today, acting_user=receptionist_user
    )

    assert center.total_amount == Decimal("0.00")
    assert center.doctor_amount == Decimal("0.00")
    assert center.center_amount == Decimal("0.00")


def test_error_messages_are_localized(session, admin_user, receptionist_user):
    _, _, txn = _setup(session, admin_user, receptionist_user)
    set_locale("ar")
    with pytest.raises(ValidationError) as exc:
        _adjust(session, admin_user, txn, "-600")
    assert "??" not in str(exc.value)