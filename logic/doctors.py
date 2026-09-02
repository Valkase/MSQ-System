"""
Doctor logic — creating doctors and updating their standard_percentage.
Every write here is admin-only (design doc Section 5.2, task plan 2.4:
"only admin manages users and doctor rates"), enforced via
logic.permissions.require_permission as the first line of every write
function.

Rate changes are the one part of task plan 2.2 that lives here rather
than in transactions.py: "Write a function to update a doctor's
standard_percentage (goes through the update-and-log function, so rate
changes are auditable)". Everything else about a doctor (name, active
flag) is ordinary record management, so it's grouped in the same module.
"""

import uuid

from sqlalchemy.orm import Session

from data.models.doctor import Doctor
from data.models.user import User
from i18n import t
from logic.audit import record_creation, update_and_log
from logic.errors import NotFoundError
from logic.permissions import Permission, require_permission
from logic.validation import validate_percentage, validate_required_text

_CREATE_FIELDS = ("name", "standard_percentage", "active")


def _get_doctor_or_raise(session: Session, doctor_id: uuid.UUID) -> Doctor:
    doctor = session.get(Doctor, doctor_id)
    if doctor is None:
        raise NotFoundError(t("doctors.not_found", doctor_id=doctor_id))
    return doctor


def create_doctor(
    session: Session,
    *,
    name: str,
    standard_percentage,
    acting_user: User,
) -> Doctor:
    """Add a new doctor with their standing split rate. Logged as a creation. Admin-only."""
    require_permission(acting_user, Permission.MANAGE_DOCTORS)

    clean_name = validate_required_text(name, "fields.doctor_name", max_length=120)
    clean_pct = validate_percentage(standard_percentage, "fields.standard_percentage")

    doctor = Doctor(name=clean_name, standard_percentage=clean_pct, active=True)
    session.add(doctor)
    try:
        session.flush()
        record_creation(
            session, instance=doctor, changed_by=acting_user.id, fields=list(_CREATE_FIELDS)
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
    acting_user: User,
) -> Doctor:
    """
    Update a doctor's standing split rate (task plan 2.2). Admin-only
    (task plan 2.4). Routed through update_and_log so the change (old %
    -> new %, who, when) is captured in audit_log — this is the ONLY
    sanctioned way to change standard_percentage; never set it directly
    on the model elsewhere.

    Per Doctor's docstring / Transaction's docstring: this never
    retroactively touches existing transactions, since those store their
    own copied percentage from the time they were created.
    """
    require_permission(acting_user, Permission.MANAGE_DOCTORS)

    doctor = _get_doctor_or_raise(session, doctor_id)
    clean_pct = validate_percentage(new_percentage, "fields.standard_percentage")
    try:
        update_and_log(
            session,
            instance=doctor,
            changes={"standard_percentage": clean_pct},
            changed_by=acting_user.id,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return doctor


def rename_doctor(session: Session, *, doctor_id: uuid.UUID, new_name: str, acting_user: User) -> Doctor:
    """Correct/update a doctor's display name. Admin-only, routed through update_and_log."""
    require_permission(acting_user, Permission.MANAGE_DOCTORS)

    doctor = _get_doctor_or_raise(session, doctor_id)
    clean_name = validate_required_text(new_name, "fields.doctor_name", max_length=120)
    try:
        update_and_log(
            session, instance=doctor, changes={"name": clean_name}, changed_by=acting_user.id
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return doctor


def deactivate_doctor(session: Session, *, doctor_id: uuid.UUID, acting_user: User) -> Doctor:
    """Soft-disable a doctor no longer practicing at the center (design doc Section 6). Admin-only."""
    require_permission(acting_user, Permission.MANAGE_DOCTORS)

    doctor = _get_doctor_or_raise(session, doctor_id)
    try:
        update_and_log(session, instance=doctor, changes={"active": False}, changed_by=acting_user.id)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return doctor


def reactivate_doctor(session: Session, *, doctor_id: uuid.UUID, acting_user: User) -> Doctor:
    require_permission(acting_user, Permission.MANAGE_DOCTORS)

    doctor = _get_doctor_or_raise(session, doctor_id)
    try:
        update_and_log(session, instance=doctor, changes={"active": True}, changed_by=acting_user.id)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return doctor