"""
Unit tests for logic/permissions.py and its enforcement inside
logic/patients.py, logic/doctors.py, logic/transactions.py, and
logic/reports.py (task plan 2.4).

Split into two halves: unit tests against permissions.py directly
(has_permission / require_permission in isolation), and integration
tests confirming the *actual* write functions raise PermissionDeniedError
for the right role/user, not just that the permission table itself looks
right. A permissions module nobody calls doesn't protect anything.
"""

from datetime import date
from decimal import Decimal

import pytest

from logic import doctors, patients, reports, transactions
from logic.errors import PermissionDeniedError
from logic.permissions import Permission, has_permission, require_permission


# --- permissions.py in isolation -------------------------------------------------


def test_admin_has_every_permission(admin_user):
    for permission in Permission:
        assert has_permission(admin_user, permission), permission


def test_receptionist_lacks_admin_only_permissions(receptionist_user):
    assert not has_permission(receptionist_user, Permission.MANAGE_DOCTORS)
    assert not has_permission(receptionist_user, Permission.MANAGE_USERS)


def test_receptionist_has_day_to_day_permissions(receptionist_user):
    for permission in (
        Permission.CREATE_PATIENT,
        Permission.EDIT_PATIENT,
        Permission.DELETE_PATIENT,
        Permission.DEACTIVATE_PATIENT,
        Permission.ATTACH_FILE,
        Permission.RECORD_TRANSACTION,
        Permission.VIEW_REPORTS,
    ):
        assert has_permission(receptionist_user, permission), permission


def test_deactivated_user_has_no_permissions_regardless_of_role(admin_user):
    admin_user.active = False
    for permission in Permission:
        assert not has_permission(admin_user, permission), permission


def test_require_permission_raises_for_missing_permission(receptionist_user):
    with pytest.raises(PermissionDeniedError):
        require_permission(receptionist_user, Permission.MANAGE_DOCTORS)


def test_require_permission_raises_for_deactivated_user(admin_user):
    admin_user.active = False
    with pytest.raises(PermissionDeniedError):
        require_permission(admin_user, Permission.VIEW_REPORTS)


def test_require_permission_is_silent_when_allowed(admin_user):
    assert require_permission(admin_user, Permission.MANAGE_DOCTORS) is None


# --- enforcement inside the actual logic functions --------------------------------


def test_receptionist_can_create_patient(session, receptionist_user):
    patient = patients.create_patient(
        session, full_name="Mona Youssef", phone="0100000001", acting_user=receptionist_user
    )
    assert patient.id is not None


def test_deactivated_receptionist_cannot_create_patient(session, inactive_receptionist_user):
    with pytest.raises(PermissionDeniedError):
        patients.create_patient(
            session,
            full_name="Mona Youssef",
            phone="0100000001",
            acting_user=inactive_receptionist_user,
        )


def test_receptionist_cannot_create_doctor(session, receptionist_user):
    with pytest.raises(PermissionDeniedError):
        doctors.create_doctor(
            session,
            name="Dr. Ahmed Smith",
            standard_percentage=Decimal("60.00"),
            acting_user=receptionist_user,
        )


def test_admin_can_create_doctor(session, admin_user):
    doctor = doctors.create_doctor(
        session, name="Dr. Ahmed Smith", standard_percentage=Decimal("60.00"), acting_user=admin_user
    )
    assert doctor.id is not None


def test_receptionist_cannot_update_doctor_percentage(session, admin_user, receptionist_user):
    doctor = doctors.create_doctor(
        session, name="Dr. Sara Lee", standard_percentage=Decimal("50.00"), acting_user=admin_user
    )
    with pytest.raises(PermissionDeniedError):
        doctors.update_doctor_percentage(
            session,
            doctor_id=doctor.id,
            new_percentage=Decimal("70.00"),
            acting_user=receptionist_user,
        )
    # confirm the rejected attempt didn't leak through
    session.refresh(doctor)
    assert doctor.standard_percentage == Decimal("50.00")


def test_receptionist_can_record_transaction(session, admin_user, receptionist_user):
    doctor = doctors.create_doctor(
        session, name="Dr. Ahmed Smith", standard_percentage=Decimal("60.00"), acting_user=admin_user
    )
    patient = patients.create_patient(
        session, full_name="Mona Youssef", phone="0100000001", acting_user=receptionist_user
    )
    txn = transactions.record_transaction(
        session,
        patient_id=patient.id,
        doctor_id=doctor.id,
        total_amount=Decimal("500.00"),
        acting_user=receptionist_user,
    )
    assert txn.recorded_by == receptionist_user.id


def test_deactivated_user_cannot_record_transaction(
    session, admin_user, receptionist_user, inactive_receptionist_user
):
    doctor = doctors.create_doctor(
        session, name="Dr. Ahmed Smith", standard_percentage=Decimal("60.00"), acting_user=admin_user
    )
    patient = patients.create_patient(
        session, full_name="Mona Youssef", phone="0100000001", acting_user=receptionist_user
    )
    with pytest.raises(PermissionDeniedError):
        transactions.record_transaction(
            session,
            patient_id=patient.id,
            doctor_id=doctor.id,
            total_amount=Decimal("500.00"),
            acting_user=inactive_receptionist_user,
        )


def test_reports_require_permission(session, admin_user, inactive_receptionist_user):
    today = date.today()
    # An active user (any role) can view reports.
    totals = reports.center_totals_for_range(
        session, start_date=today, end_date=today, acting_user=admin_user
    )
    assert totals.transaction_count == 0

    # A deactivated user cannot.
    with pytest.raises(PermissionDeniedError):
        reports.center_totals_for_range(
            session, start_date=today, end_date=today, acting_user=inactive_receptionist_user
        )