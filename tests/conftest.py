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