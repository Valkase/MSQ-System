"""
Unit tests for logic/audit.py (task plan 2.3 and Phase 6's "Unit tests
for the audit logging function" item).

Covers: old/new values are captured correctly, no-op edits produce no
audit entry, creation is logged as old_values=None, get_history returns
a record's entries oldest-first, JSONB-unsafe field types (UUID,
Decimal, date) round-trip correctly, and — the rule this module exists
to enforce — a Transaction can never pass through update_and_log.
"""

import time
import uuid
from datetime import date
from decimal import Decimal

import pytest

from data.models.doctor import Doctor
from data.models.patient import Patient
from data.models.transaction import Transaction
from logic.audit import get_history, log_change, record_creation, update_and_log
from logic.errors import LogicError


def _make_patient(session, **overrides) -> Patient:
    defaults = dict(full_name="Mona Youssef", phone="0100000001", active=True)
    defaults.update(overrides)
    patient = Patient(**defaults)
    session.add(patient)
    session.flush()
    return patient


def test_update_and_log_captures_only_changed_fields(session, admin_id):
    patient = _make_patient(session)
    session.commit()

    entry = update_and_log(
        session,
        instance=patient,
        changes={"full_name": "Mona Youssef", "address": "123 Nile St"},  # name unchanged
        changed_by=admin_id,
    )
    session.commit()

    assert entry is not None
    assert entry.old_values == {"address": None}
    assert entry.new_values == {"address": "123 Nile St"}
    assert patient.full_name == "Mona Youssef"
    assert patient.address == "123 Nile St"


def test_update_and_log_returns_none_and_logs_nothing_when_no_real_change(session, admin_id):
    patient = _make_patient(session, address="123 Nile St")
    session.commit()

    entry = update_and_log(
        session,
        instance=patient,
        changes={"address": "123 Nile St"},  # identical to current value
        changed_by=admin_id,
    )
    session.commit()

    assert entry is None
    history = get_history(session, table_name="patients", record_id=patient.id)
    assert history == []


def test_record_creation_logs_a_full_snapshot_with_no_old_values(session, admin_id):
    doctor = Doctor(name="Dr. Sara Lee", standard_percentage=Decimal("50.00"), active=True)
    session.add(doctor)
    session.flush()

    entry = record_creation(
        session,
        instance=doctor,
        changed_by=admin_id,
        fields=["name", "standard_percentage", "active"],
    )
    session.commit()

    assert entry.old_values is None
    assert entry.new_values == {
        "name": "Dr. Sara Lee",
        "standard_percentage": "50.00",  # Decimal -> str, see test below for why
        "active": True,
    }


def test_get_history_returns_oldest_first(session, admin_id):
    patient = _make_patient(session)
    session.commit()

    update_and_log(session, instance=patient, changes={"address": "First"}, changed_by=admin_id)
    session.commit()
    time.sleep(0.001)  # guarantee a distinct created_at from the first edit
    update_and_log(session, instance=patient, changes={"address": "Second"}, changed_by=admin_id)
    session.commit()

    history = get_history(session, table_name="patients", record_id=patient.id)

    assert [h.new_values["address"] for h in history] == ["First", "Second"]
    assert history[0].created_at <= history[1].created_at


def test_json_unsafe_field_types_are_normalized_to_strings(session, admin_id):
    """
    AuditLog.old_values/new_values are JSONB. Decimal, UUID, and date
    aren't natively JSON-serializable — confirm _json_safe (used by every
    audit write) converts them rather than raising or silently corrupting
    the stored value.
    """
    some_uuid = uuid.uuid4()
    some_date = date(2026, 1, 15)

    entry = log_change(
        session,
        table_name="doctors",
        record_id=uuid.uuid4(),
        changed_by=admin_id,
        old_values=None,
        new_values={
            "amount": Decimal("123.45"),
            "ref_id": some_uuid,
            "visit_date": some_date,
        },
    )
    session.commit()

    assert entry.new_values["amount"] == "123.45"
    assert entry.new_values["ref_id"] == str(some_uuid)
    assert entry.new_values["visit_date"] == some_date.isoformat()


def test_update_and_log_refuses_to_touch_a_transaction(session, admin_id):
    """
    The enforced half of task plan 2.3's last item: transactions must
    never go through the edit path, and that's a runtime guard, not just
    a docstring. Confirm the guard fires before any mutation happens.
    """
    patient = _make_patient(session)
    doctor = Doctor(name="Dr. Ahmed Smith", standard_percentage=Decimal("60.00"), active=True)
    session.add(doctor)
    session.flush()

    transaction = Transaction(
        patient_id=patient.id,
        doctor_id=doctor.id,
        recorded_by=admin_id,
        total_amount=Decimal("500.00"),
        doctor_percentage=Decimal("60.00"),
        center_percentage=Decimal("40.00"),
        doctor_amount=Decimal("300.00"),
        center_amount=Decimal("200.00"),
    )
    session.add(transaction)
    session.commit()

    with pytest.raises(LogicError):
        update_and_log(
            session,
            instance=transaction,
            changes={"total_amount": Decimal("999.00")},
            changed_by=admin_id,
        )

    # Nothing should have changed, and nothing should have been logged.
    session.refresh(transaction)
    assert transaction.total_amount == Decimal("500.00")
    assert get_history(session, table_name="transactions", record_id=transaction.id) == []