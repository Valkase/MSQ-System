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
    Login failed — invalid username/password, or the account is
    deactivated (logic/auth.py's login()). Deliberately a single generic
    error type covering all failure cases: the message shown to the user
    never reveals which specific case occurred (unknown username vs.
    wrong password vs. deactivated account), so login failures can't be
    used to enumerate valid usernames or account status.
    """

class AuthenticationLockedError(AuthenticationError):
    """
    Login was attempted against an account that is currently locked out
    due to too many recent failed attempts (logic/auth.py's login() and
    User.locked_until). Subclasses AuthenticationError so any caller
    that only catches the parent still handles this safely, but the GUI
    can catch this specifically to show a "locked, try again in N
    minutes" message instead of the generic invalid-credentials one.
    """



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