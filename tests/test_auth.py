"""
Unit tests for logic/auth.py and logic/app_session.py (task plan Phase 3):
user creation, login, lockout/throttling, change password, admin reset,
deactivation, and session handling.

argon2 is swapped for a cheap-parameter hasher in tests purely for speed;
production uses the library defaults.
"""

from datetime import datetime, timedelta, timezone

import pytest
from argon2 import PasswordHasher

from data.models.user import ROLE_RECEPTIONIST
from i18n import set_locale
from logic import auth
from logic.app_session import current_session
from logic.audit import get_history
from logic.auth import LOCKOUT_DURATION, MAX_FAILED_ATTEMPTS
from logic.errors import (
    AccountLockedError,
    AuthenticationError,
    DuplicateError,
    PermissionDeniedError,
    ValidationError,
)

PASSWORD = "correct-horse-1"
T0 = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _fast_hasher(monkeypatch):
    monkeypatch.setattr(auth, "_hasher", PasswordHasher(time_cost=1, memory_cost=8, parallelism=1))


def _create(session, admin, username="sara", password=PASSWORD, role=ROLE_RECEPTIONIST):
    return auth.create_user(
        session, username=username, password=password, role=role, acting_user=admin
    )


def _bad_login(session, username="sara", now=T0):
    return auth.authenticate(session, username=username, password="wrong-password", now=now)


# --- create_user -------------------------------------------------------------------


def test_admin_can_create_user_and_password_is_hashed(session, admin_user):
    user = _create(session, admin_user)
    assert user.password_hash != PASSWORD
    assert user.password_hash.startswith("$argon2")
    assert user.active is True


def test_receptionist_cannot_create_user(session, receptionist_user):
    with pytest.raises(PermissionDeniedError):
        _create(session, receptionist_user)


def test_duplicate_username_is_rejected_case_insensitively(session, admin_user):
    _create(session, admin_user, username="Sara")
    with pytest.raises(DuplicateError):
        _create(session, admin_user, username="sara")


def test_create_user_validates_role_and_password(session, admin_user):
    with pytest.raises(ValidationError):
        _create(session, admin_user, role="superuser")
    with pytest.raises(ValidationError):
        _create(session, admin_user, password="short")
    with pytest.raises(ValidationError):
        _create(session, admin_user, username="   ")


def test_creation_audit_entry_never_contains_the_password_hash(session, admin_user):
    user = _create(session, admin_user)
    history = get_history(session, table_name="users", record_id=user.id)
    assert len(history) == 1
    assert history[0].new_values == {"username": "sara", "role": ROLE_RECEPTIONIST, "active": True}


# --- login -------------------------------------------------------------------------


def test_login_succeeds_and_starts_session(session, admin_user):
    user = _create(session, admin_user)
    logged_in = auth.login(session, username="  SARA ", password=PASSWORD)

    assert logged_in.id == user.id
    assert current_session.get_user(session).id == user.id

    auth.logout()
    with pytest.raises(AuthenticationError):
        current_session.get_user(session)


def test_wrong_password_and_unknown_user_give_identical_errors(session, admin_user):
    _create(session, admin_user)
    with pytest.raises(AuthenticationError) as wrong_pw:
        _bad_login(session)
    with pytest.raises(AuthenticationError) as no_user:
        _bad_login(session, username="nobody")
    assert str(wrong_pw.value) == str(no_user.value)


def test_account_locks_after_max_failed_attempts_and_unlocks_after_duration(session, admin_user):
    user = _create(session, admin_user)

    for _ in range(MAX_FAILED_ATTEMPTS - 1):
        with pytest.raises(AuthenticationError) as exc:
            _bad_login(session)
        assert not isinstance(exc.value, AccountLockedError)

    with pytest.raises(AccountLockedError):
        _bad_login(session)

    # Even the CORRECT password is refused while locked.
    with pytest.raises(AccountLockedError):
        auth.authenticate(session, username="sara", password=PASSWORD, now=T0 + timedelta(minutes=1))

    after = T0 + LOCKOUT_DURATION + timedelta(seconds=1)
    assert auth.authenticate(session, username="sara", password=PASSWORD, now=after).id == user.id
    assert user.failed_login_attempts == 0
    assert user.locked_until is None


def test_successful_login_resets_failed_counter(session, admin_user):
    user = _create(session, admin_user)
    for _ in range(MAX_FAILED_ATTEMPTS - 1):
        with pytest.raises(AuthenticationError):
            _bad_login(session)
    auth.authenticate(session, username="sara", password=PASSWORD, now=T0)
    assert user.failed_login_attempts == 0

    # A fresh run of failures starts from zero again (not locked after 1 more).
    with pytest.raises(AuthenticationError) as exc:
        _bad_login(session)
    assert not isinstance(exc.value, AccountLockedError)


def test_lockout_message_is_localized(session, admin_user):
    _create(session, admin_user)
    set_locale("ar")
    for _ in range(MAX_FAILED_ATTEMPTS - 1):
        with pytest.raises(AuthenticationError):
            _bad_login(session)
    with pytest.raises(AccountLockedError) as exc:
        _bad_login(session)
    assert "??" not in str(exc.value)
    assert "15" in str(exc.value)


def test_deactivated_user_cannot_log_in(session, admin_user):
    user = _create(session, admin_user)
    auth.deactivate_user(session, user_id=user.id, acting_user=admin_user)
    with pytest.raises(AuthenticationError):
        auth.login(session, username="sara", password=PASSWORD)
    assert not current_session.is_logged_in()


# --- change / reset password -------------------------------------------------------


def test_change_password_success_and_old_password_stops_working(session, admin_user):
    user = _create(session, admin_user)
    auth.change_password(
        session, acting_user=user, current_password=PASSWORD, new_password="brand-new-pass-2"
    )

    with pytest.raises(AuthenticationError):
        auth.authenticate(session, username="sara", password=PASSWORD, now=T0)
    assert auth.authenticate(session, username="sara", password="brand-new-pass-2", now=T0).id == user.id


def test_change_password_audit_entry_has_no_hash(session, admin_user):
    user = _create(session, admin_user)
    auth.change_password(
        session, acting_user=user, current_password=PASSWORD, new_password="brand-new-pass-2"
    )
    history = get_history(session, table_name="users", record_id=user.id)
    assert history[-1].new_values == {"password_changed": True}
    assert history[-1].old_values is None


def test_change_password_requires_correct_current_password(session, admin_user):
    user = _create(session, admin_user)
    with pytest.raises(AuthenticationError):
        auth.change_password(
            session, acting_user=user, current_password="nope-nope-nope", new_password="brand-new-pass-2"
        )
    assert user.failed_login_attempts == 1


def test_change_password_rejects_weak_or_unchanged_password(session, admin_user):
    user = _create(session, admin_user)
    with pytest.raises(ValidationError):
        auth.change_password(session, acting_user=user, current_password=PASSWORD, new_password="short")
    with pytest.raises(ValidationError):
        auth.change_password(session, acting_user=user, current_password=PASSWORD, new_password=PASSWORD)


def test_admin_can_reset_password_and_clears_lockout(session, admin_user):
    user = _create(session, admin_user)
    for _ in range(MAX_FAILED_ATTEMPTS):
        with pytest.raises(AuthenticationError):
            _bad_login(session)
    assert user.locked_until is not None

    auth.reset_user_password(
        session, user_id=user.id, new_password="reset-by-admin-3", acting_user=admin_user
    )
    assert auth.authenticate(session, username="sara", password="reset-by-admin-3", now=T0).id == user.id


def test_receptionist_cannot_reset_passwords_or_unlock(session, admin_user, receptionist_user):
    user = _create(session, admin_user)
    with pytest.raises(PermissionDeniedError):
        auth.reset_user_password(
            session, user_id=user.id, new_password="reset-by-admin-3", acting_user=receptionist_user
        )
    with pytest.raises(PermissionDeniedError):
        auth.unlock_user(session, user_id=user.id, acting_user=receptionist_user)


# --- deactivate / reactivate -------------------------------------------------------


def test_admin_cannot_deactivate_themselves(session, admin_user):
    with pytest.raises(ValidationError):
        auth.deactivate_user(session, user_id=admin_user.id, acting_user=admin_user)
    assert admin_user.active is True


def test_receptionist_cannot_deactivate_users(session, admin_user, receptionist_user):
    user = _create(session, admin_user)
    with pytest.raises(PermissionDeniedError):
        auth.deactivate_user(session, user_id=user.id, acting_user=receptionist_user)


def test_deactivate_and_reactivate_are_audited(session, admin_user):
    user = _create(session, admin_user)
    auth.deactivate_user(session, user_id=user.id, acting_user=admin_user)
    auth.reactivate_user(session, user_id=user.id, acting_user=admin_user)

    history = get_history(session, table_name="users", record_id=user.id)
    assert [h.new_values.get("active") for h in history[1:]] == [False, True]


def test_deactivating_a_logged_in_user_ends_their_session(session, admin_user):
    user = _create(session, admin_user)
    auth.login(session, username="sara", password=PASSWORD)
    auth.deactivate_user(session, user_id=user.id, acting_user=admin_user)

    with pytest.raises(AuthenticationError):
        current_session.get_user(session)
    assert not current_session.is_logged_in()


# --- session handling --------------------------------------------------------------


def test_session_expires_after_idle_timeout(session, admin_user):
    user = _create(session, admin_user)
    current_session.start(user, now=T0)

    # Activity inside the window keeps it alive and resets the clock.
    current_session.get_user(session, now=T0 + timedelta(minutes=20))
    current_session.get_user(session, now=T0 + timedelta(minutes=40))

    with pytest.raises(AuthenticationError):
        current_session.get_user(session, now=T0 + timedelta(minutes=80))
    assert not current_session.is_logged_in(now=T0 + timedelta(minutes=80))


def test_idle_timeout_can_be_disabled(session, admin_user):
    user = _create(session, admin_user)
    current_session.idle_timeout = None
    current_session.start(user, now=T0)
    assert current_session.get_user(session, now=T0 + timedelta(days=3)).id == user.id


def test_list_users_is_admin_only(session, admin_user, receptionist_user):
    _create(session, admin_user)
    assert len(auth.list_users(session, acting_user=admin_user)) >= 2
    with pytest.raises(PermissionDeniedError):
        auth.list_users(session, acting_user=receptionist_user)



def test_touch_extends_a_live_session_but_never_revives_an_expired_one(session, admin_user):
    user = _create(session, admin_user)
    current_session.start(user, now=T0)

    current_session.touch(now=T0 + timedelta(minutes=25))  # inside the window: clock resets
    assert current_session.is_logged_in(now=T0 + timedelta(minutes=50))

    current_session.touch(now=T0 + timedelta(minutes=120))  # already expired: ignored
    assert not current_session.is_logged_in(now=T0 + timedelta(minutes=121))