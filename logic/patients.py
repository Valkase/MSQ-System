"""
Patient logic (task plan 2.1, now gated by task plan 2.4's access control).

Every function here takes an already-open SQLAlchemy `session` (from
data.database.get_session) rather than opening its own — this keeps a
GUI action's "read, validate, write, log" sequence inside one
transaction, and makes these functions straightforward to unit test with
a throwaway session/in-memory DB. Each function commits on success and
rolls back on failure; callers don't need to commit themselves.

Every WRITE function takes `acting_user: User` (not a bare uuid) as its
first keyword argument and calls logic.permissions.require_permission as
its first line — before any validation, reads, or writes. `acting_user`
is also the source of the audit trail's `changed_by`/`uploaded_by`, so
there's exactly one "who is doing this" value per call, not a separate
id the caller could accidentally mismatch against a different user.
Read-only functions (get_patient, search_patients, list_attachments)
stay open to any caller — task plan 2.4 only calls out *sensitive*
actions for gating, and both roles need to look patients up as part of
routine front-desk work.
"""

import uuid
from datetime import date

from sqlalchemy import or_
from sqlalchemy.orm import Session

from data.models.attachment import Attachment
from data.models.patient import Patient
from data.models.transaction import Transaction
from data.models.user import User
from i18n import t
from logic.audit import log_change, record_creation, update_and_log
from logic.errors import NotFoundError, PatientHasTransactionsError, ValidationError
from logic.permissions import Permission, require_permission
from logic.validation import (
    validate_email,
    validate_optional_text,
    validate_phone,
    validate_required_text,
)

# Fields captured in the "created" audit snapshot and available for edit.
_EDITABLE_FIELDS = ("full_name", "phone", "email", "date_of_birth", "address")


def _get_patient_or_raise(session: Session, patient_id: uuid.UUID) -> Patient:
    patient = session.get(Patient, patient_id)
    if patient is None:
        raise NotFoundError(t("patients.not_found", patient_id=patient_id))
    return patient


def create_patient(
    session: Session,
    *,
    full_name: str,
    phone: str,
    acting_user: User,
    email: str | None = None,
    date_of_birth: date | None = None,
    address: str | None = None,
) -> Patient:
    """
    Create a new patient after validating required fields and phone/email
    format (task plan 2.1). Logs the creation to the audit trail.
    """
    require_permission(acting_user, Permission.CREATE_PATIENT)

    clean_name = validate_required_text(full_name, "fields.full_name", max_length=150)
    clean_phone = validate_phone(phone)
    clean_email = validate_email(email)
    clean_address = validate_optional_text(address, "fields.address", max_length=255)

    patient = Patient(
        full_name=clean_name,
        phone=clean_phone,
        email=clean_email,
        date_of_birth=date_of_birth,
        address=clean_address,
        active=True,
    )
    session.add(patient)
    try:
        session.flush()  # populate patient.id for the audit entry below
        record_creation(
            session,
            instance=patient,
            changed_by=acting_user.id,
            fields=list(_EDITABLE_FIELDS) + ["active"],
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return patient


def get_patient(session: Session, patient_id: uuid.UUID) -> Patient:
    """Fetch a single patient by id, or raise NotFoundError."""
    return _get_patient_or_raise(session, patient_id)


def search_patients(
    session: Session, query: str, *, include_inactive: bool = False
) -> list[Patient]:
    """
    Search patients by (partial, case-insensitive) name or phone —
    task plan 2.1 "search by name or phone". Inactive/deactivated
    patients are excluded by default since the common case (front-desk
    lookup for an active patient) shouldn't surface deactivated records
    unless explicitly asked for.
    """
    cleaned = (query or "").strip()
    if not cleaned:
        return []

    like_pattern = f"%{cleaned}%"
    q = session.query(Patient).filter(
        or_(Patient.full_name.ilike(like_pattern), Patient.phone.ilike(like_pattern))
    )
    if not include_inactive:
        q = q.filter(Patient.active.is_(True))
    return q.order_by(Patient.full_name.asc()).all()


def edit_patient(
    session: Session,
    *,
    patient_id: uuid.UUID,
    acting_user: User,
    full_name: str | None = None,
    phone: str | None = None,
    email: str | None = ...,  # sentinel: distinguish "not provided" from "clear to None"
    date_of_birth: date | None = ...,
    address: str | None = ...,
) -> Patient:
    """
    Edit a patient profile. Only fields explicitly passed are validated
    and changed — omitted keyword args are left untouched. Routes through
    logic.audit.update_and_log (task plan 2.1 "must route through the
    update-and-log function") so every edit is captured in audit_log.

    Use Ellipsis (the default) to mean "leave unchanged" for the optional
    fields, since None is a legitimate value to set them to (e.g.
    clearing an address).
    """
    require_permission(acting_user, Permission.EDIT_PATIENT)

    patient = _get_patient_or_raise(session, patient_id)

    changes: dict[str, object] = {}
    if full_name is not None:
        changes["full_name"] = validate_required_text(full_name, "fields.full_name", max_length=150)
    if phone is not None:
        changes["phone"] = validate_phone(phone)
    if email is not ...:
        changes["email"] = validate_email(email)
    if date_of_birth is not ...:
        changes["date_of_birth"] = date_of_birth
    if address is not ...:
        changes["address"] = validate_optional_text(address, "fields.address", max_length=255)

    if not changes:
        return patient  # nothing to do, nothing to log

    try:
        update_and_log(session, instance=patient, changes=changes, changed_by=acting_user.id)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return patient


def deactivate_patient(session: Session, *, patient_id: uuid.UUID, acting_user: User) -> Patient:
    """
    Soft-disable a patient (task plan 2.1). This is the fallback whenever
    hard deletion isn't allowed (see delete_patient), and is also the
    normal path for a patient who's simply no longer active at the clinic.
    """
    require_permission(acting_user, Permission.DEACTIVATE_PATIENT)

    patient = _get_patient_or_raise(session, patient_id)
    try:
        update_and_log(
            session, instance=patient, changes={"active": False}, changed_by=acting_user.id
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return patient


def reactivate_patient(session: Session, *, patient_id: uuid.UUID, acting_user: User) -> Patient:
    """Reverse of deactivate_patient — reasonable companion action, same audit path."""
    require_permission(acting_user, Permission.DEACTIVATE_PATIENT)

    patient = _get_patient_or_raise(session, patient_id)
    try:
        update_and_log(
            session, instance=patient, changes={"active": True}, changed_by=acting_user.id
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return patient


def delete_patient(session: Session, *, patient_id: uuid.UUID, acting_user: User) -> None:
    """
    Permanently delete a patient — ONLY when they have zero transactions
    (design doc Section 2.1 / 9: deletion is for genuine data-entry
    mistakes, not a way to erase financial history). Raises
    PatientHasTransactionsError if any transaction references this
    patient; callers should catch this and offer deactivate_patient
    instead, per the design doc.

    Logs the deletion to audit_log as a special case: old_values is a
    snapshot of the row being removed, new_values is {"deleted": True}
    (new_values can't be null on the model, and there's no "after" state
    for a deleted row — this is the documented convention for delete
    entries in this table, distinct from a normal field edit).
    """
    require_permission(acting_user, Permission.DELETE_PATIENT)

    patient = _get_patient_or_raise(session, patient_id)

    has_transactions = (
        session.query(Transaction.id).filter(Transaction.patient_id == patient_id).first()
        is not None
    )
    if has_transactions:
        raise PatientHasTransactionsError(t("patients.delete_blocked_has_transactions"))

    old_values = {field: getattr(patient, field) for field in _EDITABLE_FIELDS + ("active",)}

    try:
        log_change(
            session,
            table_name=patient.__tablename__,
            record_id=patient.id,
            changed_by=acting_user.id,
            old_values=old_values,
            new_values={"deleted": True},
        )
        session.delete(patient)
        session.commit()
    except Exception:
        session.rollback()
        raise


def attach_file(
    session: Session,
    *,
    patient_id: uuid.UUID,
    file_path: str,
    acting_user: User,
    description: str | None = None,
) -> Attachment:
    """
    Attach a file *reference* to a patient (task plan 2.1) — stores the
    path only, never the file's bytes (see data/models/attachment.py).
    Confirms the patient exists first so a bad patient_id fails clearly
    rather than as an opaque FK violation.

    Not routed through update_and_log: attachments are their own table
    with their own uploaded_by/created_at, which already gives
    accountability for "who attached what, when" without needing a
    separate audit_log entry for what is itself a creation, not an edit
    to the patient row.
    """
    require_permission(acting_user, Permission.ATTACH_FILE)

    _get_patient_or_raise(session, patient_id)

    clean_path = validate_required_text(file_path, "fields.file_path", max_length=500)
    clean_description = validate_optional_text(description, "fields.description", max_length=2000)

    attachment = Attachment(
        patient_id=patient_id,
        file_path=clean_path,
        description=clean_description,
        uploaded_by=acting_user.id,
    )
    session.add(attachment)
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise
    return attachment


def list_attachments(session: Session, patient_id: uuid.UUID) -> list[Attachment]:
    """All attachments for a patient, newest first — backs the Phase 4 attachments list."""
    _get_patient_or_raise(session, patient_id)
    return (
        session.query(Attachment)
        .filter(Attachment.patient_id == patient_id)
        .order_by(Attachment.created_at.desc())
        .all()
    )