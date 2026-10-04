"""Tests for logic.transactions.list_transaction_rows and the NaN/Infinity amount guard."""

import time
from decimal import Decimal

import pytest

from logic import doctors, patients, transactions
from logic.errors import PermissionDeniedError, ValidationError


def _setup(session, admin, receptionist):
    doctor = doctors.create_doctor(
        session, name="Dr. Ahmed Smith", standard_percentage=Decimal("60.00"), acting_user=admin
    )
    patient = patients.create_patient(
        session, full_name="Mona Youssef", phone="0100000001", acting_user=receptionist
    )
    return doctor, patient


def _record(session, user, patient, doctor, amount):
    return transactions.record_transaction(
        session,
        patient_id=patient.id,
        doctor_id=doctor.id,
        total_amount=Decimal(amount),
        acting_user=user,
    )


def test_rows_include_names_and_the_saved_split(session, admin_user, receptionist_user):
    doctor, patient = _setup(session, admin_user, receptionist_user)
    _record(session, receptionist_user, patient, doctor, "500.00")

    (row,) = transactions.list_transaction_rows(session, acting_user=receptionist_user)

    assert row.patient_name == "Mona Youssef"
    assert row.doctor_name == "Dr. Ahmed Smith"
    assert row.total_amount == Decimal("500.00")
    assert row.doctor_amount == Decimal("300.00")
    assert row.center_amount == Decimal("200.00")


def test_rows_are_newest_first_and_respect_limit(session, admin_user, receptionist_user):
    doctor, patient = _setup(session, admin_user, receptionist_user)
    _record(session, receptionist_user, patient, doctor, "100.00")
    time.sleep(0.002)
    _record(session, receptionist_user, patient, doctor, "200.00")
    time.sleep(0.002)
    _record(session, receptionist_user, patient, doctor, "300.00")

    rows = transactions.list_transaction_rows(session, acting_user=receptionist_user, limit=2)

    assert [r.total_amount for r in rows] == [Decimal("300.00"), Decimal("200.00")]


def test_rows_can_be_filtered_to_one_patient(session, admin_user, receptionist_user):
    doctor, patient = _setup(session, admin_user, receptionist_user)
    other = patients.create_patient(
        session, full_name="Karim Adel", phone="0100000002", acting_user=receptionist_user
    )
    _record(session, receptionist_user, patient, doctor, "100.00")
    _record(session, receptionist_user, other, doctor, "250.00")

    rows = transactions.list_transaction_rows(
        session, acting_user=receptionist_user, patient_id=other.id
    )

    assert [r.patient_name for r in rows] == ["Karim Adel"]


def test_deactivated_user_cannot_list_transaction_rows(
    session, admin_user, receptionist_user, inactive_receptionist_user
):
    _setup(session, admin_user, receptionist_user)
    with pytest.raises(PermissionDeniedError):
        transactions.list_transaction_rows(session, acting_user=inactive_receptionist_user)


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_amounts_are_rejected_cleanly(session, admin_user, receptionist_user, bad):
    doctor, patient = _setup(session, admin_user, receptionist_user)
    with pytest.raises(ValidationError):
        transactions.record_transaction(
            session,
            patient_id=patient.id,
            doctor_id=doctor.id,
            total_amount=Decimal(bad),
            acting_user=receptionist_user,
        )