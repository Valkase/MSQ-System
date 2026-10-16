"""
Phase 6: a saved transaction (or adjustment) can't be edited or deleted
through ANY code path. Three layers: no such function exists, the generic
edit path refuses these models, and real operations elsewhere never change
a saved row.
"""

import ast
import importlib
import inspect
import pkgutil
from decimal import Decimal
from pathlib import Path

import pytest

import logic
from data.models.adjustment import Adjustment
from data.models.audit_log import AuditLog
from data.models.transaction import Transaction
from logic import adjustments, doctors, patients, transactions
from logic.audit import get_history, update_and_log
from logic.errors import LogicError

ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN_PREFIXES = ("update", "edit", "delete", "remove", "modify", "set_", "change")


def _logic_modules():
    for info in pkgutil.iter_modules(logic.__path__):
        yield importlib.import_module(f"logic.{info.name}")


def _public_functions(module):
    return [
        name
        for name, obj in inspect.getmembers(module, inspect.isfunction)
        if obj.__module__ == module.__name__ and not name.startswith("_")
    ]


# --- layer 1: no mutating function exists ------------------------------------------


@pytest.mark.parametrize("module", [transactions, adjustments])
def test_money_modules_expose_no_mutating_functions(module):
    bad = [n for n in _public_functions(module) if n.startswith(FORBIDDEN_PREFIXES)]
    assert bad == []


def test_no_logic_function_mutates_a_transaction_or_adjustment():
    offenders = []
    for module in _logic_modules():
        for name in _public_functions(module):
            if name.startswith(FORBIDDEN_PREFIXES) and ("transaction" in name or "adjustment" in name):
                offenders.append(f"{module.__name__}.{name}")
    assert offenders == []


def test_models_have_no_updated_at_column():
    assert not hasattr(Transaction, "updated_at")
    assert not hasattr(Adjustment, "updated_at")


def test_only_delete_patient_ever_deletes_rows():
    """No other logic/GUI code may call .delete(...) — rows are deleted in exactly one place."""
    allowed = {ROOT / "logic" / "patients.py"}
    offenders = []
    for folder in ("logic", "gui"):
        for path in (ROOT / folder).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "delete"
                    and path not in allowed
                ):
                    offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []


# --- layer 2: the generic edit path refuses them -----------------------------------


def _setup(session, admin, receptionist):
    doctor = doctors.create_doctor(
        session, name="Dr. Ahmed Smith", standard_percentage=Decimal("60.00"), acting_user=admin
    )
    patient = patients.create_patient(
        session, full_name="Mona Youssef", phone="0100000001", acting_user=receptionist
    )
    txn = transactions.record_transaction(
        session,
        patient_id=patient.id,
        doctor_id=doctor.id,
        total_amount=Decimal("500.00"),
        acting_user=receptionist,
    )
    return doctor, patient, txn


def test_update_and_log_refuses_a_transaction(session, admin_user, receptionist_user):
    _, _, txn = _setup(session, admin_user, receptionist_user)
    with pytest.raises(LogicError):
        update_and_log(
            session, instance=txn, changes={"total_amount": Decimal("1.00")}, changed_by=admin_user.id
        )
    session.refresh(txn)
    assert txn.total_amount == Decimal("500.00")


def test_update_and_log_refuses_an_adjustment(session, admin_user, receptionist_user):
    _, _, txn = _setup(session, admin_user, receptionist_user)
    adj = adjustments.record_adjustment(
        session,
        transaction_id=txn.id,
        amount_change=Decimal("-10"),
        reason="typo",
        acting_user=admin_user,
    )
    with pytest.raises(LogicError):
        update_and_log(session, instance=adj, changes={"reason": "changed"}, changed_by=admin_user.id)
    session.refresh(adj)
    assert adj.reason == "typo"


def test_update_and_log_refuses_an_audit_log_row(session, admin_user, receptionist_user):
    _, patient, _ = _setup(session, admin_user, receptionist_user)
    entry = get_history(session, table_name="patients", record_id=patient.id)[0]
    assert isinstance(entry, AuditLog)
    with pytest.raises(LogicError):
        update_and_log(
            session, instance=entry, changes={"table_name": "tampered"}, changed_by=admin_user.id
        )


# --- layer 3: other real operations never touch a saved transaction ----------------


def test_rate_change_voids_and_patient_edits_leave_the_original_untouched(
    session, admin_user, receptionist_user
):
    doctor, patient, txn = _setup(session, admin_user, receptionist_user)
    before = {
        c.name: getattr(txn, c.name) for c in Transaction.__table__.columns
    }

    doctors.update_doctor_percentage(
        session, doctor_id=doctor.id, new_percentage=Decimal("90.00"), acting_user=admin_user
    )
    doctors.deactivate_doctor(session, doctor_id=doctor.id, acting_user=admin_user)
    patients.edit_patient(
        session, patient_id=patient.id, acting_user=receptionist_user, address="New address"
    )
    patients.deactivate_patient(session, patient_id=patient.id, acting_user=receptionist_user)
    adjustments.record_adjustment(
        session,
        transaction_id=txn.id,
        amount_change=Decimal("-500"),  # full void
        reason="mistake",
        acting_user=admin_user,
    )

    session.expire_all()
    after = session.get(Transaction, txn.id)
    assert {c.name: getattr(after, c.name) for c in Transaction.__table__.columns} == before