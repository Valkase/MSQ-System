"""
DB session helper for the GUI layer.

One short-lived SQLAlchemy session per GUI operation, always closed
afterwards. Don't hold a session open for the life of a window: a cached
User row would hide an admin deactivating that account from another desk.

Don't touch ORM attributes after the `with` block ends — objects are
detached (and expired after any commit) once the session is closed. Read
what you need inside the block.
"""

from contextlib import contextmanager

from data.database import SessionLocal


@contextmanager
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()