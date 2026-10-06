"""
Schema compatibility (task plan Phase 5 / design decision): every desk shares
ONE PostgreSQL database but updates itself independently, so the app must
notice when its code and the database schema disagree instead of running
against the wrong tables.

Policy: migrations are applied deliberately by an admin (alembic upgrade head),
never automatically by a receptionist PC. On startup the GUI should call
check_schema() and:
    OK              -> continue
    DB_BEHIND       -> tell the user the database must be upgraded by an admin
    DB_AHEAD        -> tell the user this app is out of date and must update
    NOT_INITIALIZED -> database has not been set up (run migrations)
"""

import enum

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from version import EXPECTED_SCHEMA_REVISION, SCHEMA_REVISIONS


class SchemaStatus(enum.Enum):
    OK = "ok"
    DB_BEHIND = "db_behind"
    DB_AHEAD = "db_ahead"
    NOT_INITIALIZED = "not_initialized"


def get_db_revision(engine: Engine) -> str | None:
    """The revision stored in alembic_version, or None if the table/row is absent.
    Connection problems are NOT swallowed (OperationalError propagates)."""
    if not inspect(engine).has_table("alembic_version"):
        return None
    with engine.connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()


def check_schema(engine: Engine, expected: str = EXPECTED_SCHEMA_REVISION) -> SchemaStatus:
    current = get_db_revision(engine)
    if current is None:
        return SchemaStatus.NOT_INITIALIZED
    if current == expected:
        return SchemaStatus.OK
    # A revision this build has never heard of can only come from a newer release.
    if current in SCHEMA_REVISIONS and expected in SCHEMA_REVISIONS:
        if SCHEMA_REVISIONS.index(current) < SCHEMA_REVISIONS.index(expected):
            return SchemaStatus.DB_BEHIND
    return SchemaStatus.DB_AHEAD
