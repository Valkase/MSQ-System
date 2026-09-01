"""
Database setup: engine, session factory, and the declarative Base
that every model in data/models/ inherits from.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from config import DATABASE_URL

# Single shared engine for the app
engine = create_engine(DATABASE_URL, echo=False, future=True)

# Session factory — call SessionLocal() to get a new session per operation/request
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

# Base class all ORM models inherit from
Base = declarative_base()


def get_session():
    """
    Convenience helper for logic-layer functions:

        from data.database import get_session
        with get_session() as session:
            ...

    Yields a session and guarantees it's closed afterward.
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()