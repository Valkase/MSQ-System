"""
Shared exception types for the business logic layer.

The GUI layer is expected to catch these (never raw SQLAlchemy exceptions)
and translate them into user-facing, localized messages. Logic-layer
functions should never let a raw IntegrityError/etc. escape uncaught —
catch it, roll back, and raise one of these instead.
"""


class LogicError(Exception):
    """Base class for all business-logic errors."""


class ValidationError(LogicError):
    """Input failed a field-level validation rule (format, required, etc.)."""


class NotFoundError(LogicError):
    """A referenced record (by id) does not exist."""


class PermissionDeniedError(LogicError):
    """The acting user's role does not permit this action (see logic/permissions.py)."""


class PatientHasTransactionsError(LogicError):
    """
    Raised when hard-deleting a patient is attempted but the patient has
    one or more transactions on record. Per the design doc (Section 2.1 /
    9): deletion is only for genuine data-entry mistakes with zero
    financial history. Callers should catch this and prompt the user to
    deactivate the patient instead.
    """


class DuplicateError(LogicError):
    """A uniqueness constraint would be violated (e.g. username already taken)."""


class AuthenticationError(LogicError):
    """
    Login failed, or the caller isn't (or is no longer) logged in: bad
    credentials, deactivated account, expired/missing session.
    """


class AccountLockedError(AuthenticationError):
    """
    Too many failed login attempts. `locked_until` (timezone-aware UTC) lets
    the GUI show when the user can try again.
    """

    def __init__(self, message: str, *, locked_until):
        super().__init__(message)
        self.locked_until = locked_until

class AttachmentNotFoundError(NotFoundError):
    """The attachment's stored file path doesn't resolve (moved, deleted, or attached from another PC)."""


class AttachmentOpenError(LogicError):
    """The file exists but the operating system could not open it."""