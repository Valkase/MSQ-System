"""Tests for logic.patients.list_recent_patients (backs the patient list's empty-search view)."""

from logic import patients


def _make(session, user, name, phone):
    return patients.create_patient(session, full_name=name, phone=phone, acting_user=user)


def test_list_recent_respects_limit(session, receptionist_user):
    for i in range(3):
        _make(session, receptionist_user, f"Patient {i}", f"010000000{i}1")
    assert len(patients.list_recent_patients(session, limit=2)) == 2


def test_list_recent_hides_inactive_unless_asked(session, receptionist_user):
    keep = _make(session, receptionist_user, "Active One", "01000000011")
    gone = _make(session, receptionist_user, "Inactive One", "01000000022")
    patients.deactivate_patient(session, patient_id=gone.id, acting_user=receptionist_user)

    visible = patients.list_recent_patients(session)
    assert [p.id for p in visible] == [keep.id]

    everyone = patients.list_recent_patients(session, include_inactive=True)
    assert {p.id for p in everyone} == {keep.id, gone.id}