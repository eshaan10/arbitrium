"""SQLAlchemy 2.0 engine and session factory."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from marketedge.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)

SessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False, future=True)


def get_session() -> Session:
    """Return a new session. Caller is responsible for closing / committing."""
    return SessionLocal()
