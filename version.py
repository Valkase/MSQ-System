"""
Single source of truth for the app version and the database schema it expects.

Release checklist: bump __version__ here, commit, tag the commit "v<version>",
and run scripts/build_release.py (it refuses to build if the tag and this
constant disagree).

SCHEMA_REVISIONS lists every Alembic revision, oldest first. Add the new
revision id to the END whenever you add a migration; tests/test_schema_check.py
fails if this tuple drifts from the real migration chain.
"""

__version__ = "1.0.0"

SCHEMA_REVISIONS = (
    "21409c91c206",  # users
    "7efa53a632bf",  # doctors
    "4c1a80d15898",  # patients
    "d369d36d1ad9",  # transactions
    "9da1262da4b3",  # attachments, audit_logs
    "c84aa5948943",  # login lockout columns
    "8bd5cca79952",  # adjustments
)

# The database revision this build of the app requires.
EXPECTED_SCHEMA_REVISION = SCHEMA_REVISIONS[-1]
