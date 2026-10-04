"""
Shared pytest fixtures for the test suite.

Tests run against an in-memory SQLite database rather than the real
PostgreSQL instance, so they're fast and need no local DB setup. The one
wrinkle: AuditLog.old_values/new_values use PostgreSQL's JSONB type,
which SQLite doesn't know how to render — the `@compiles` hook below
teaches SQLAlchemy to treat JSONB as plain JSON when the target dialect
is sqlite. This is purely a test-time shim; production still uses real
PostgreSQL/JSONB via data/database.py, this file is never imported by
application code.
"""

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker


@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json_for_sqlite(element, compiler, **kw):
    return "JSON"


@pytest.fixture()
def session():
    """A fresh in-memory SQLite session with all tables created, per test."""
    # Imported here (not at module scope) so the @compiles hook above is
    # registered before any table metadata gets compiled against sqlite.
    import data.models  # noqa: F401  (registers all models on Base.metadata)
    from data.database import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db_session = Session()
    try:
        yield db_session
    finally:
        db_session.close()


@pytest.fixture()
def admin_id() -> uuid.UUID:
    """A stand-in 'changed_by' user id — no actual User row is needed for these tests."""
    return uuid.uuid4()


def _make_user(session, *, username: str, role: str, active: bool = True):
    from data.models.user import User

    user = User(username=username, password_hash="x", role=role, active=active)
    session.add(user)
    session.flush()  # populate user.id
    return user


@pytest.fixture()
def admin_user(session):
    """A persisted, active admin User — for logic functions that take `acting_user`."""
    from data.models.user import ROLE_ADMIN

    return _make_user(session, username="admin1", role=ROLE_ADMIN)


@pytest.fixture()
def receptionist_user(session):
    """A persisted, active receptionist User."""
    from data.models.user import ROLE_RECEPTIONIST

    return _make_user(session, username="reception1", role=ROLE_RECEPTIONIST)


@pytest.fixture()
def inactive_receptionist_user(session):
    """A persisted but deactivated receptionist User — should have zero permissions."""
    from data.models.user import ROLE_RECEPTIONIST

    return _make_user(session, username="reception_deactivated", role=ROLE_RECEPTIONIST, active=False)


@pytest.fixture(autouse=True)
def _reset_locale():
    """
    i18n's active locale is a process-wide global (see i18n/translator.py).
    Reset it to the default after every test so a test that switches to
    Arabic can never leak into the next test, regardless of test order.
    """
    from i18n import DEFAULT_LOCALE, set_locale

    yield
    set_locale(DEFAULT_LOCALE)


@pytest.fixture(autouse=True)
def _reset_app_session():
    """
    logic.app_session.current_session is process-wide state (like the i18n
    locale). Make sure a login in one test never leaks into the next.
    """
    from logic.app_session import DEFAULT_IDLE_TIMEOUT, current_session

    current_session.end()
    current_session.idle_timeout = DEFAULT_IDLE_TIMEOUT
    yield
    current_session.end()
    current_session.idle_timeout = DEFAULT_IDLE_TIMEOUT