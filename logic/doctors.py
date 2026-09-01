"""
Doctor logic — creating doctors and updating their standard_percentage.

Rate changes are the one part of task plan 2.2 that lives here rather
than in transactions.py: "Write a function to update a doctor's
standard_percentage (goes through the update-and-log function, so rate
changes are auditable)". Everything else about a doctor (name, active
flag) is ordinary record management, so it's grouped in the same module.
"""

import uuid

from sqlalchemy.orm import Session

from data.models.doctor import Doctor
from logic.audit import record_creation, update_and_log
from logic.errors import NotFoundError
from logic.validation import validate_percentage, validate_required_text

_CREATE_FIELDS = ("name", "standard_percentage", "active")


def _get_doctor_or_raise(session: Session, doctor_id: uuid.UUID) -> Doctor:
    doctor = session.get(Doctor, doctor_id)
    if doctor is None:
        raise NotFoundError(f"No doctor found with id {doctor_id}.")
    return doctor


def create_doctor(
    session: Session,
    *,
    name: str,
    standard_percentage,
    created_by: uuid.UUID,
) -> Doctor:
    """Add a new doctor with their standing split rate. Logged as a creation."""
    clean_name = validate_required_text(name, "Doctor name", max_length=120)
    clean_pct = validate_percentage(standard_percentage, "Standard percentage")

    doctor = Doctor(name=clean_name, standard_percentage=clean_pct, active=True)
    session.add(doctor)
    try:
        session.flush()
        record_creation(
            session, instance=doctor, changed_by=created_by, fields=list(_CREATE_FIELDS)
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return doctor


def get_doctor(session: Session, doctor_id: uuid.UUID) -> Doctor:
    return _get_doctor_or_raise(session, doctor_id)


def list_doctors(session: Session, *, include_inactive: bool = False) -> list[Doctor]:
    q = session.query(Doctor)
    if not include_inactive:
        q = q.filter(Doctor.active.is_(True))
    return q.order_by(Doctor.name.asc()).all()


def update_doctor_percentage(
    session: Session,
    *,
    doctor_id: uuid.UUID,
    new_percentage,
    changed_by: uuid.UUID,
) -> Doctor:
    """
    Update a doctor's standing split rate (task plan 2.2). Routed through
    update_and_log so the change (old % -> new %, who, when) is captured
    in audit_log — this is the ONLY sanctioned way to change
    standard_percentage; never set it directly on the model elsewhere.

    Per Doctor's docstring / Transaction's docstring: this never
    retroactively touches existing transactions, since those store their
    own copied percentage from the time they were created.
    """
    doctor = _get_doctor_or_raise(session, doctor_id)
    clean_pct = validate_percentage(new_percentage, "Standard percentage")
    try:
        update_and_log(
            session,
            instance=doctor,
            changes={"standard_percentage": clean_pct},
            changed_by=changed_by,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return doctor


def rename_doctor(
    session: Session, *, doctor_id: uuid.UUID, new_name: str, changed_by: uuid.UUID
) -> Doctor:
    """Correct/update a doctor's display name. Routed through update_and_log like any edit."""
    doctor = _get_doctor_or_raise(session, doctor_id)
    clean_name = validate_required_text(new_name, "Doctor name", max_length=120)
    try:
        update_and_log(
            session, instance=doctor, changes={"name": clean_name}, changed_by=changed_by
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return doctor


def deactivate_doctor(session: Session, *, doctor_id: uuid.UUID, changed_by: uuid.UUID) -> Doctor:
    """Soft-disable a doctor no longer practicing at the center (design doc Section 6)."""
    doctor = _get_doctor_or_raise(session, doctor_id)
    try:
        update_and_log(session, instance=doctor, changes={"active": False}, changed_by=changed_by)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return doctor


def reactivate_doctor(session: Session, *, doctor_id: uuid.UUID, changed_by: uuid.UUID) -> Doctor:
    doctor = _get_doctor_or_raise(session, doctor_id)
    try:
        update_and_log(session, instance=doctor, changes={"active": True}, changed_by=changed_by)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return doctor