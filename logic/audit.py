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
*creation* half (used for patients), but nothing in this module offers an
update/delete path for a Transaction, deliberately.

Reading history: `get_history` returns raw AuditLog rows (oldest first).
`list_history_entries` is what the Phase 4 edit-history view uses: it is
permission-gated (VIEW_HISTORY), joins in the username, and returns plain
frozen dataclasses that are safe to use after the DB session closes.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from data.models.audit_log import AuditLog
from data.models.transaction import Transaction
from data.models.user import User
from logic.errors import LogicError
from logic.permissions import Permission, require_permission

ACTION_CREATED = "created"
ACTION_EDITED = "edited"
ACTION_DELETED = "deleted"


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
    Fetch the full audit trail for one record, oldest first. Raw, ungated
    building block; the GUI should use `list_history_entries` instead.
    Deliberately not paginated: per-record history for this clinic's scale
    is expected to stay small (one patient's/doctor's edit count).
    """
    return (
        session.query(AuditLog)
        .filter(AuditLog.table_name == table_name, AuditLog.record_id == record_id)
        .order_by(AuditLog.created_at.asc())
        .all()
    )


# --- edit-history view support (task plan Phase 4) ---------------------------------


@dataclass(frozen=True)
class FieldChange:
    """One field's before/after. Values are JSON-safe (Decimal/date arrive as strings)."""

    field: str
    old: Any
    new: Any


@dataclass(frozen=True)
class HistoryEntry:
    """One audit_log row, flattened for display."""

    id: uuid.UUID
    created_at: datetime
    action: str  # ACTION_CREATED / ACTION_EDITED / ACTION_DELETED
    changed_by_name: str
    changes: tuple[FieldChange, ...]


def _to_entry(log: AuditLog, username: str) -> HistoryEntry:
    old = log.old_values or {}
    new = log.new_values or {}

    if new == {"deleted": True}:
        # Delete convention (logic/patients.py): old_values is the removed row's snapshot.
        action = ACTION_DELETED
        changes = tuple(FieldChange(k, v, None) for k, v in old.items())
    elif log.old_values is None and "password_changed" not in new:
        action = ACTION_CREATED
        changes = tuple(FieldChange(k, None, v) for k, v in new.items())
    else:
        action = ACTION_EDITED
        changes = tuple(FieldChange(k, old.get(k), v) for k, v in new.items())

    return HistoryEntry(
        id=log.id,
        created_at=log.created_at,
        action=action,
        changed_by_name=username,
        changes=changes,
    )


def list_history_entries(
    session: Session,
    *,
    table_name: str,
    record_id: uuid.UUID,
    acting_user: User,
) -> list[HistoryEntry]:
    """
    Newest-first edit history for one record, with the editing user's
    username joined in. Requires VIEW_HISTORY (admin-only).
    """
    require_permission(acting_user, Permission.VIEW_HISTORY)

    rows = (
        session.query(AuditLog, User.username)
        .join(User, User.id == AuditLog.changed_by)
        .filter(AuditLog.table_name == table_name, AuditLog.record_id == record_id)
        .order_by(AuditLog.created_at.desc())
        .all()
    )
    return [_to_entry(log, username) for log, username in rows]
