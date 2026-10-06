"""Tests for data/schema_check.py and the SCHEMA_REVISIONS bookkeeping in version.py."""

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from data.schema_check import SchemaStatus, check_schema, get_db_revision
from version import EXPECTED_SCHEMA_REVISION, SCHEMA_REVISIONS

ROOT = Path(__file__).resolve().parent.parent


def _engine_with_revision(revision):
    engine = create_engine("sqlite:///:memory:")
    if revision is not None:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
            conn.execute(text("INSERT INTO alembic_version VALUES (:r)"), {"r": revision})
    return engine


def test_schema_revisions_match_the_real_alembic_chain():
    """Fails when someone adds a migration but forgets version.SCHEMA_REVISIONS."""
    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    chain = tuple(rev.revision for rev in reversed(list(script.walk_revisions())))
    assert chain == SCHEMA_REVISIONS
    assert script.get_current_head() == EXPECTED_SCHEMA_REVISION


def test_matching_revision_is_ok():
    assert check_schema(_engine_with_revision(EXPECTED_SCHEMA_REVISION)) is SchemaStatus.OK


def test_older_database_is_behind():
    assert check_schema(_engine_with_revision(SCHEMA_REVISIONS[0])) is SchemaStatus.DB_BEHIND


def test_unknown_revision_means_database_is_ahead():
    assert check_schema(_engine_with_revision("ffffffffffff")) is SchemaStatus.DB_AHEAD


def test_missing_alembic_table_is_not_initialized():
    engine = _engine_with_revision(None)
    assert get_db_revision(engine) is None
    assert check_schema(engine) is SchemaStatus.NOT_INITIALIZED
