"""
Access control (task plan 2.4).

Two roles only (design doc Section 5.2 / 9): receptionist and admin.
Permissions are modeled as an explicit enum + role -> permissions
mapping here, rather than scattered `if user.role == "admin"` checks
through every logic module — one place to look to answer "who can do
X", and one place to change if a role's capabilities change later.

`require_permission()` is "a permission-check function used before
sensitive actions" (task plan 2.4, item 2) — every sensitive function
in the logic layer calls it as its first line, before touching the
database. A user without permission gets PermissionDeniedError
immediately and nothing is read, written, or logged — the same family of
exceptions as NotFoundError/ValidationError, so the GUI has one set of
exceptions to translate into an on-screen message.
"""

from enum import Enum, auto

from data.models.user import ROLE_ADMIN, ROLE_RECEPTIONIST, User
from i18n import t
from logic.errors import PermissionDeniedError


class Permission(Enum):
    """One entry per distinct sensitive action gated by role."""

    CREATE_PATIENT = auto()
    EDIT_PATIENT = auto()
    DELETE_PATIENT = auto()
    DEACTIVATE_PATIENT = auto()
    ATTACH_FILE = auto()
    RECORD_TRANSACTION = auto()
    VIEW_REPORTS = auto()
    MANAGE_DOCTORS = auto()
    MANAGE_USERS = auto()
    ADJUST_TRANSACTION = auto()
    VIEW_HISTORY = auto()


# Receptionists: day-to-day patient and transaction entry (design doc
# Section 5.2). Deleting a patient is included here, not admin-gated: it
# exists to correct a receptionist's own data-entry mistake (a duplicate,
# a typo), and is already constrained at the logic layer to patients with
# zero transactions (see logic/patients.py).
_RECEPTIONIST_PERMISSIONS = frozenset(
    {
        Permission.CREATE_PATIENT,
        Permission.EDIT_PATIENT,
        Permission.DELETE_PATIENT,
        Permission.DEACTIVATE_PATIENT,
        Permission.ATTACH_FILE,
        Permission.RECORD_TRANSACTION,
        Permission.VIEW_REPORTS,
    }
)

# Admin-only. Admins are a superset of receptionists (see ROLE_PERMISSIONS).
# VIEW_HISTORY is admin-only because the audit trail is an accountability
# tool: reviewing "who changed what" is an admin duty. To let receptionists
# see it too, move VIEW_HISTORY into _RECEPTIONIST_PERMISSIONS above.
_ADMIN_ONLY_PERMISSIONS = frozenset(
    {
        Permission.MANAGE_DOCTORS,
        Permission.MANAGE_USERS,
        Permission.ADJUST_TRANSACTION,
        Permission.VIEW_HISTORY,
    }
)

ROLE_PERMISSIONS: dict[str, frozenset] = {
    ROLE_RECEPTIONIST: _RECEPTIONIST_PERMISSIONS,
    ROLE_ADMIN: _RECEPTIONIST_PERMISSIONS | _ADMIN_ONLY_PERMISSIONS,
}

# Maps each Permission to the message key describing that action in plain
# language, so the denial message is fully localized (task plan 2.5).
_ACTION_KEYS: dict[Permission, str] = {
    Permission.CREATE_PATIENT: "permissions.actions.create_patient",
    Permission.EDIT_PATIENT: "permissions.actions.edit_patient",
    Permission.DELETE_PATIENT: "permissions.actions.delete_patient",
    Permission.DEACTIVATE_PATIENT: "permissions.actions.deactivate_patient",
    Permission.ATTACH_FILE: "permissions.actions.attach_file",
    Permission.RECORD_TRANSACTION: "permissions.actions.record_transaction",
    Permission.VIEW_REPORTS: "permissions.actions.view_reports",
    Permission.MANAGE_DOCTORS: "permissions.actions.manage_doctors",
    Permission.MANAGE_USERS: "permissions.actions.manage_users",
    Permission.ADJUST_TRANSACTION: "permissions.actions.adjust_transaction",
    Permission.VIEW_HISTORY: "permissions.actions.view_history",
}


def has_permission(user: User, permission: Permission) -> bool:
    """
    Non-raising check — for the GUI layer to decide whether to show or
    enable an action without catching an exception just to ask a yes/no
    question. A deactivated user has no permissions at all, regardless of
    their stored role.
    """
    if not user.active:
        return False
    return permission in ROLE_PERMISSIONS.get(user.role, frozenset())


def require_permission(user: User, permission: Permission) -> None:
    """
    Raise PermissionDeniedError if `user` may not perform `permission`;
    otherwise return None and let the caller proceed. Always call this
    as the FIRST line of a sensitive logic-layer function, before any
    validation, reads, or writes.
    """
    if not user.active:
        raise PermissionDeniedError(t("permissions.user_deactivated", username=user.username))
    if permission not in ROLE_PERMISSIONS.get(user.role, frozenset()):
        action = t(_ACTION_KEYS.get(permission, permission.name))
        raise PermissionDeniedError(t("permissions.denied", action=action))
