"""
Database setup: engine, session factory, and the declarative Base
that every model in data/models/ inherits from.
"""

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from config import DATABASE_URL

# Single shared engine for the app. connect_timeout keeps the GUI from hanging
# for a minute when the database PC is off (psycopg2/libpq option, in seconds).
engine = create_engine(
    DATABASE_URL, echo=False, future=True, connect_args={"connect_timeout": 5}
)

# Session factory — call SessionLocal() to get a new session per operation/request
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

# Base class all ORM models inherit from
Base = declarative_base()


@contextmanager
def get_session():
    """
    Convenience helper for scripts and logic-layer callers:

        from data.database import get_session
        with get_session() as session:
            ...

    Yields a session and guarantees it's closed afterward. (The GUI uses
    gui.db.db_session, which does the same thing.)
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
