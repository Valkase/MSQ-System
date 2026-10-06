"""Tests for logic.audit.list_history_entries (backs the Phase 4 edit-history view)."""

import time
from decimal import Decimal

import pytest

from logic import doctors, patients
from logic.audit import ACTION_CREATED, ACTION_DELETED, ACTION_EDITED, list_history_entries
from logic.errors import PermissionDeniedError


def _history(session, table, record_id, user):
    return list_history_entries(
        session, table_name=table, record_id=record_id, acting_user=user
    )


def test_creation_is_listed_with_every_field_and_the_creator(session, admin_user, receptionist_user):
    patient = patients.create_patient(
        session, full_name="Mona Youssef", phone="0100000001", acting_user=receptionist_user
    )

    (entry,) = _history(session, "patients", patient.id, admin_user)

    assert entry.action == ACTION_CREATED
    assert entry.changed_by_name == "reception1"
    by_field = {c.field: c for c in entry.changes}
    assert by_field["full_name"].old is None
    assert by_field["full_name"].new == "Mona Youssef"
    assert by_field["active"].new is True


def test_edits_show_old_and_new_values_newest_first(session, admin_user, receptionist_user):
    patient = patients.create_patient(
        session, full_name="Mona Youssef", phone="0100000001", acting_user=receptionist_user
    )
    time.sleep(0.002)
    patients.edit_patient(
        session, patient_id=patient.id, acting_user=admin_user, address="123 Nile St"
    )

    entries = _history(session, "patients", patient.id, admin_user)

    assert [e.action for e in entries] == [ACTION_EDITED, ACTION_CREATED]  # newest first
    edit = entries[0]
    assert edit.changed_by_name == "admin1"
    (change,) = edit.changes
    assert (change.field, change.old, change.new) == ("address", None, "123 Nile St")


def test_doctor_rate_change_is_listed_as_strings(session, admin_user):
    doctor = doctors.create_doctor(
        session, name="Dr. Sara Lee", standard_percentage=Decimal("50.00"), acting_user=admin_user
    )
    time.sleep(0.002)
    doctors.update_doctor_percentage(
        session, doctor_id=doctor.id, new_percentage=Decimal("55.00"), acting_user=admin_user
    )

    edit = _history(session, "doctors", doctor.id, admin_user)[0]

    (change,) = edit.changes
    assert (change.old, change.new) == ("50.00", "55.00")


def test_deleted_patient_history_survives_with_a_deleted_entry(
    session, admin_user, receptionist_user
):
    patient = patients.create_patient(
        session, full_name="Duplicate Entry", phone="0100000009", acting_user=receptionist_user
    )
    time.sleep(0.002)
    patients.delete_patient(session, patient_id=patient.id, acting_user=receptionist_user)

    entries = _history(session, "patients", patient.id, admin_user)

    assert [e.action for e in entries] == [ACTION_DELETED, ACTION_CREATED]
    assert {c.field: c.old for c in entries[0].changes}["full_name"] == "Duplicate Entry"


def test_history_only_includes_the_requested_record(session, admin_user, receptionist_user):
    a = patients.create_patient(
        session, full_name="Patient A", phone="0100000001", acting_user=receptionist_user
    )
    patients.create_patient(
        session, full_name="Patient B", phone="0100000002", acting_user=receptionist_user
    )

    assert len(_history(session, "patients", a.id, admin_user)) == 1


def test_receptionist_cannot_view_history(session, receptionist_user):
    patient = patients.create_patient(
        session, full_name="Mona Youssef", phone="0100000001", acting_user=receptionist_user
    )
    with pytest.raises(PermissionDeniedError):
        _history(session, "patients", patient.id, receptionist_user)


def test_deactivated_admin_cannot_view_history(session, admin_user, receptionist_user):
    patient = patients.create_patient(
        session, full_name="Mona Youssef", phone="0100000001", acting_user=receptionist_user
    )
    admin_user.active = False
    with pytest.raises(PermissionDeniedError):
        _history(session, "patients", patient.id, admin_user)
