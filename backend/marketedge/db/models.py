"""SQLAlchemy 2.0 ORM models.

NOTE: The Alembic migrations in ``db/migrations`` are the source of truth for the
schema (they carry the dedup trigger and other raw-SQL bits). These models mirror
that schema for the query/API layer; keep them in sync with the migrations by hand.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Integer,
    Numeric,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Event(Base):
    """One real-world event (a game), plus its resolution once known."""

    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    sport: Mapped[str] = mapped_column(String, nullable=False)
    league: Mapped[str] = mapped_column(String, nullable=False)
    home_team: Mapped[str] = mapped_column(String, nullable=False)
    away_team: Mapped[str] = mapped_column(String, nullable=False)
    scheduled_start: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default=text("'scheduled'"))

    home_score: Mapped[int | None] = mapped_column(Integer)
    away_score: Mapped[int | None] = mapped_column(Integer)
    winner: Mapped[str | None] = mapped_column(String)  # 'home' | 'away' | 'draw' | NULL
    resolved_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    kalshi_event_ticker: Mapped[str | None] = mapped_column(String, unique=True)
    odds_api_event_id: Mapped[str | None] = mapped_column(String, unique=True)

    # 'kalshi_provisional' until Phase 2 confirms authoritative home/away from
    # The Odds API, then 'odds_api'. NULL for events created by other sources.
    home_away_source: Mapped[str | None] = mapped_column(String)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")
    )

    snapshots: Mapped[list["OddsSnapshot"]] = relationship(back_populates="event")


class OddsSnapshot(Base):
    """Append-only price observation. Never updated, never deleted.

    A BEFORE INSERT trigger (see migration 0002) suppresses rows whose
    implied_probability is unchanged since the latest observation for the same
    (event_id, source, outcome).
    """

    __tablename__ = "odds_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id"), nullable=False
    )
    source: Mapped[str] = mapped_column(String, nullable=False)  # 'kalshi' | 'consensus' | ...
    outcome: Mapped[str] = mapped_column(String, nullable=False)  # 'home' | 'away' | 'draw'
    # Canonical team name — the STABLE divergence join anchor (NULL for 'draw').
    # home/away can be re-labelled authoritatively at the event level; team never
    # changes for a written row, so joins on team stay correct. See migration 0005.
    team: Mapped[str | None] = mapped_column(String)

    implied_probability: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)
    raw_price: Mapped[float | None] = mapped_column(Numeric(8, 4))
    price_format: Mapped[str] = mapped_column(String, nullable=False)  # probability|american|decimal
    liquidity_score: Mapped[float | None] = mapped_column(Numeric(8, 2))
    # none_as_null: a market with no depth stores SQL NULL (queryable via IS NULL),
    # not a JSON 'null' literal — so Phase 2 depth filters behave correctly.
    order_book_depth: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))

    ingested_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")
    )
    snapshot_time: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")
    )

    event: Mapped["Event"] = relationship(back_populates="snapshots")


class CalibrationHistory(Base):
    """Grading record for a flagged divergence. Populated in Phase 3."""

    __tablename__ = "calibration_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id"), nullable=False
    )
    divergence_score: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)
    predicted_prob: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)
    confidence_band: Mapped[str] = mapped_column(String, nullable=False)
    outcome_correct: Mapped[bool | None] = mapped_column()  # NULL until resolved
    flagged_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    graded_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
