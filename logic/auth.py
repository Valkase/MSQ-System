"""
Authentication and user administration (task plan Phase 3).

Covers: admin-only user creation, login with throttling/lockout, change
password, admin password reset, and deactivate/reactivate/unlock.

Security notes:
- Passwords are hashed with argon2 (same PasswordHasher settings as
  scripts/create_first_admin.py). Plaintext is never stored, logged, or
  put into an exception message or audit entry.
- Unknown username and wrong password produce the SAME error, and a dummy
  hash is verified for unknown usernames so response time doesn't reveal
  which usernames exist.
- Lockout: MAX_FAILED_ATTEMPTS consecutive failures lock the account for
  LOCKOUT_DURATION. Counters live on the users row (shared by all desks).
  Lockout counters are security bookkeeping, not record edits, so they are
  set directly rather than via update_and_log (which would flood audit_log).
  Everything else that changes a user (active flag, password change) IS
  audited — but never with password hashes in old/new values.
"""

import math
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from data.models.user import VALID_ROLES, User
from i18n import t
from logic.app_session import current_session, utcnow
from logic.audit import log_change, record_creation, update_and_log
from logic.errors import (
    AccountLockedError,
    AuthenticationError,
    DuplicateError,
    NotFoundError,
    ValidationError,
)
from logic.permissions import Permission, require_permission
from logic.validation import validate_password, validate_required_text

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION = timedelta(minutes=15)

_hasher = PasswordHasher()


# --- internal helpers -----------------------------------------------------------


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    """Hash verified against when the username doesn't exist (timing equalizer)."""
    return _hasher.hash("dummy-password-for-timing-equalization")


def _verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def _aware(value: datetime) -> datetime:
    """Some DB backends (e.g. SQLite in tests) hand back naive datetimes; treat them as UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _commit(session: Session) -> None:
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise


def _find_by_username(session: Session, username: str) -> User | None:
    """Case-insensitive lookup, so 'Sara' and 'sara' can't both exist."""
    return (
        session.query(User)
        .filter(func.lower(User.username) == username.strip().lower())
        .first()
    )


def _get_user_or_raise(session: Session, user_id: uuid.UUID) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise NotFoundError(t("users.not_found", user_id=user_id))
    return user


def _locked_error(locked_until: datetime, now: datetime) -> AccountLockedError:
    remaining = max((locked_until - now).total_seconds(), 0)
    minutes = max(1, math.ceil(remaining / 60))
    return AccountLockedError(t("auth.account_locked", minutes=minutes), locked_until=locked_until)


def _clear_lockout(user: User) -> None:
    user.failed_login_attempts = 0
    user.locked_until = None


def _record_failed_attempt(
    session: Session, user: User, now: datetime, *, invalid_key: str = "auth.invalid_credentials"
) -> None:
    """Count a failure, lock the account if the limit is reached, commit, and ALWAYS raise."""
    user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
    if user.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
        user.locked_until = now + LOCKOUT_DURATION
        _commit(session)
        raise _locked_error(user.locked_until, now)
    _commit(session)
    raise AuthenticationError(t(invalid_key))


def _check_not_locked(user: User, now: datetime) -> None:
    """Raise if currently locked; if a previous lock has expired, start fresh."""
    if user.locked_until is None:
        return
    locked_until = _aware(user.locked_until)
    if locked_until > now:
        raise _locked_error(locked_until, now)
    _clear_lockout(user)


# --- login / logout -------------------------------------------------------------


def authenticate(
    session: Session, *, username: str, password: str, now: datetime | None = None
) -> User:
    """
    Verify credentials and return the User, WITHOUT starting an app
    session (use `login` for that). `now` exists so tests can exercise
    lockout expiry without sleeping.

    Raises AccountLockedError (locked), AuthenticationError (bad
    credentials, or correct credentials on a deactivated account).
    """
    now = now or utcnow()
    password = password or ""
    cleaned = (username or "").strip()

    user = None
    if cleaned:
        # with_for_update: two desks failing at once can't both read the same counter (PostgreSQL).
        user = (
            session.query(User)
            .filter(func.lower(User.username) == cleaned.lower())
            .with_for_update()
            .first()
        )

    if user is None:
        _verify_password(_dummy_hash(), password)
        raise AuthenticationError(t("auth.invalid_credentials"))

    _check_not_locked(user, now)

    if not _verify_password(user.password_hash, password):
        _record_failed_attempt(session, user, now)  # always raises

    # Password correct: reset throttling, opportunistically upgrade the hash.
    _clear_lockout(user)
    try:
        if _hasher.check_needs_rehash(user.password_hash):
            user.password_hash = _hasher.hash(password)
    except InvalidHashError:
        pass
    _commit(session)

    # Checked AFTER the password so deactivation status isn't leaked to guessers.
    if not user.active:
        raise AuthenticationError(t("auth.account_deactivated"))
    return user


def login(session: Session, *, username: str, password: str) -> User:
    """Authenticate and start the process-wide app session (what the login screen calls)."""
    user = authenticate(session, username=username, password=password)
    current_session.start(user)
    return user


def logout() -> None:
    current_session.end()


# --- user administration (admin-only) -------------------------------------------


def create_user(
    session: Session, *, username: str, password: str, role: str, acting_user: User
) -> User:
    """Create a receptionist/admin account. Admin-only (MANAGE_USERS). Logged as a creation."""
    require_permission(acting_user, Permission.MANAGE_USERS)

    clean_username = validate_required_text(username, "fields.username", max_length=50)
    clean_password = validate_password(password)
    if role not in VALID_ROLES:
        raise ValidationError(t("validation.role_invalid", roles=", ".join(VALID_ROLES)))
    if _find_by_username(session, clean_username) is not None:
        raise DuplicateError(t("auth.username_taken", username=clean_username))

    user = User(
        username=clean_username,
        password_hash=_hasher.hash(clean_password),
        role=role,
        active=True,
    )
    session.add(user)
    try:
        session.flush()
        # password_hash deliberately NOT in the logged fields.
        record_creation(
            session, instance=user, changed_by=acting_user.id, fields=["username", "role", "active"]
        )
        session.commit()
    except IntegrityError as exc:  # lost a race on the unique username index
        session.rollback()
        raise DuplicateError(t("auth.username_taken", username=clean_username)) from exc
    except Exception:
        session.rollback()
        raise
    return user


def list_users(session: Session, *, acting_user: User, include_inactive: bool = True) -> list[User]:
    """All accounts for the admin screen. Admin-only."""
    require_permission(acting_user, Permission.MANAGE_USERS)
    q = session.query(User)
    if not include_inactive:
        q = q.filter(User.active.is_(True))
    return q.order_by(User.username.asc()).all()


def deactivate_user(session: Session, *, user_id: uuid.UUID, acting_user: User) -> User:
    """
    Soft-disable an account (never hard-delete — history references users).
    Admin-only. An admin can't deactivate themselves, so the system can't
    end up with nobody able to manage accounts.
    """
    require_permission(acting_user, Permission.MANAGE_USERS)
    if user_id == acting_user.id:
        raise ValidationError(t("users.cannot_deactivate_self"))

    user = _get_user_or_raise(session, user_id)
    try:
        update_and_log(session, instance=user, changes={"active": False}, changed_by=acting_user.id)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return user


def reactivate_user(session: Session, *, user_id: uuid.UUID, acting_user: User) -> User:
    """Reverse of deactivate_user; also clears any lockout. Admin-only."""
    require_permission(acting_user, Permission.MANAGE_USERS)

    user = _get_user_or_raise(session, user_id)
    try:
        update_and_log(session, instance=user, changes={"active": True}, changed_by=acting_user.id)
        _clear_lockout(user)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return user


def unlock_user(session: Session, *, user_id: uuid.UUID, acting_user: User) -> User:
    """Let an admin lift a lockout early instead of waiting it out. Admin-only."""
    require_permission(acting_user, Permission.MANAGE_USERS)

    user = _get_user_or_raise(session, user_id)
    _clear_lockout(user)
    _commit(session)
    return user


# --- passwords ------------------------------------------------------------------


def _set_password_and_log(session: Session, user: User, new_password: str, changed_by: uuid.UUID) -> None:
    user.password_hash = _hasher.hash(new_password)
    _clear_lockout(user)
    # Marker only — never the hash itself (audit_log is readable in the edit-history view).
    log_change(
        session,
        table_name=user.__tablename__,
        record_id=user.id,
        changed_by=changed_by,
        old_values=None,
        new_values={"password_changed": True},
    )


def change_password(
    session: Session,
    *,
    acting_user: User,
    current_password: str,
    new_password: str,
    now: datetime | None = None,
) -> None:
    """
    A user changes THEIR OWN password. Needs the current password, so an
    unattended logged-in desk can't be used to take over the account.
    Wrong current-password attempts count toward the same lockout as login.
    """
    now = now or utcnow()
    if not acting_user.active:
        raise AuthenticationError(t("auth.account_deactivated"))
    _check_not_locked(acting_user, now)

    if not _verify_password(acting_user.password_hash, current_password or ""):
        _record_failed_attempt(session, acting_user, now, invalid_key="auth.wrong_current_password")

    clean_new = validate_password(new_password)
    if clean_new == current_password:
        raise ValidationError(t("validation.password_unchanged"))

    try:
        _set_password_and_log(session, acting_user, clean_new, changed_by=acting_user.id)
        session.commit()
    except Exception:
        session.rollback()
        raise


def reset_user_password(
    session: Session, *, user_id: uuid.UUID, new_password: str, acting_user: User
) -> User:
    """
    Admin sets a new password for someone who forgot theirs. Admin-only.
    Also clears any lockout. (There's no email/self-service reset: this is
    an offline desktop app, so the admin is the recovery path.)
    """
    require_permission(acting_user, Permission.MANAGE_USERS)

    user = _get_user_or_raise(session, user_id)
    clean_new = validate_password(new_password)
    try:
        _set_password_and_log(session, user, clean_new, changed_by=acting_user.id)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return user