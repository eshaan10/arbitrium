"""Shared pytest fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture
def db_session():
    """A Session bound to a transaction that is ALWAYS rolled back.

    Lets DB-touching tests (e.g. dual-key merge) insert/flush and query freely
    without polluting the real append-only tables. Requires a reachable database,
    so these tests run in the container, not the local sandbox.
    """
    from sqlalchemy.orm import Session

    from arbitrium.db.engine import engine

    conn = engine.connect()
    trans = conn.begin()
    session = Session(bind=conn)
    try:
        yield session
    finally:
        session.close()
        trans.rollback()
        conn.close()
