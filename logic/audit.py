"""
Audit logging (task plan 2.3).

The single rule this module exists to enforce: every write to a patient
or doctor record goes through `update_and_log`, so the audit_log table
is a complete, trustworthy history of "who changed what, and when"
(design doc Section 5.1). No model in data/models/ should ever be
mutated and committed directly from another logic module — always
route through here.

Transactions are the one deliberate exception (data/models/transaction.py
docstring, task plan 2.3 last item): they are append-only and never pass
through update_and_log's "edit" path. `record_creation` below covers the
*creation* half (used for patients, and could be reused for transactions'
own creation logging if that's ever wanted), but nothing in this module
offers an update/delete path for a Transaction, deliberately.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from data.models.audit_log import AuditLog
from data.models.transaction import Transaction
from logic.errors import LogicError


def _json_safe(value: Any) -> Any:
    """
    Convert a single field value into something the JSONB column can
    store. SQLAlchemy models here use UUID, Decimal, and date/datetime
    types that aren't JSON-serializable by default — this normalizes
    them to strings the same way across every old/new value we log.
    """
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _safe_dict(values: dict[str, Any] | None) -> dict[str, Any] | None:
    if values is None:
        return None
    return {key: _json_safe(val) for key, val in values.items()}


def log_change(
    session: Session,
    *,
    table_name: str,
    record_id: uuid.UUID,
    changed_by: uuid.UUID,
    old_values: dict[str, Any] | None,
    new_values: dict[str, Any],
) -> AuditLog:
    """
    Write one audit_log row. Low-level building block — most callers
    should use `update_and_log` or `record_creation` instead of calling
    this directly, so the old/new value diffing stays consistent.

    Does NOT commit; the caller's transaction (usually the enclosing
    logic-layer function) is responsible for committing so the record
    change and its audit entry are saved atomically.
    """
    entry = AuditLog(
        table_name=table_name,
        record_id=record_id,
        changed_by=changed_by,
        old_values=_safe_dict(old_values),
        new_values=_safe_dict(new_values),
    )
    session.add(entry)
    return entry


def record_creation(
    session: Session,
    *,
    instance: Any,
    changed_by: uuid.UUID,
    fields: list[str],
) -> AuditLog:
    """
    Log the creation of a new row (old_values=None, new_values = a
    snapshot of `fields` as they were saved). Use right after
    session.flush() so `instance.id` is populated.
    """
    table_name = instance.__tablename__
    new_values = {field: getattr(instance, field) for field in fields}
    return log_change(
        session,
        table_name=table_name,
        record_id=instance.id,
        changed_by=changed_by,
        old_values=None,
        new_values=new_values,
    )


def update_and_log(
    session: Session,
    *,
    instance: Any,
    changes: dict[str, Any],
    changed_by: uuid.UUID,
) -> AuditLog | None:
    """
    Apply `changes` (field_name -> new_value) to `instance`, and write a
    single audit_log entry capturing only the fields that actually
    changed (comparing old vs. new value; a "change" that sets a field to
    its current value is not logged).

    Returns the created AuditLog entry, or None if nothing actually
    changed (in which case nothing is written or modified).

    Does NOT commit — the caller commits, so the record update and its
    audit entry are saved in the same transaction.

    This is the ONLY sanctioned way to mutate an existing patient or
    doctor row anywhere in the logic layer (task plan 2.3). Never call
    `session.add`/set attributes directly on an existing row elsewhere.

    Raises LogicError immediately, before touching `instance`, if called
    on a Transaction — transactions are append-only (task plan 2.3's
    last item, data/models/transaction.py) and must never pass through
    an "edit" path, enforced here rather than left as convention alone.
    """
    if isinstance(instance, Transaction):
        raise LogicError(
            "Transactions are immutable and can never be modified via update_and_log "
            "(see task plan 2.3 and data/models/transaction.py). There is deliberately "
            "no update path for a saved transaction anywhere in the logic layer."
        )

    old_values: dict[str, Any] = {}
    new_values: dict[str, Any] = {}

    for field, new_value in changes.items():
        old_value = getattr(instance, field)
        if old_value == new_value:
            continue
        old_values[field] = old_value
        new_values[field] = new_value
        setattr(instance, field, new_value)

    if not new_values:
        return None

    return log_change(
        session,
        table_name=instance.__tablename__,
        record_id=instance.id,
        changed_by=changed_by,
        old_values=old_values,
        new_values=new_values,
    )


def get_history(session: Session, *, table_name: str, record_id: uuid.UUID) -> list[AuditLog]:
    """
    Fetch the full audit trail for one record, oldest first — the data
    source for the Phase 4 "edit history" view. Deliberately not
    paginated: per-record history for this clinic's scale is expected to
    stay small (individual patient/doctor edit counts, not the whole log).
    """
    return (
        session.query(AuditLog)
        .filter(AuditLog.table_name == table_name, AuditLog.record_id == record_id)
        .order_by(AuditLog.created_at.asc())
        .all()
    )