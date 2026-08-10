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
    Computed,
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
    # Canonical winning team — the STABLE result anchor (NULL for a draw, and
    # also NULL while unresolved; `status` discriminates). Never home/away: those
    # are provisional for Kalshi events and get corrected later. See migration 0007.
    winner_team: Mapped[str | None] = mapped_column(String)
    # Derived by Postgres from winner_team + home/away, so it CANNOT drift when
    # home/away is corrected. Read-only: Computed marks it non-writable.
    winner_side: Mapped[str | None] = mapped_column(
        String,
        Computed(
            "CASE WHEN status <> 'final' THEN NULL "
            "WHEN winner_team IS NULL THEN 'draw' "
            "WHEN winner_team = home_team THEN 'home' "
            "WHEN winner_team = away_team THEN 'away' END",
            persisted=True,
        ),
    )
    resolution_source: Mapped[str | None] = mapped_column(String)  # 'odds_api_scores'
    unresolvable_reason: Mapped[str | None] = mapped_column(String)
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

    # 'live' = written before the game from data available then (a genuine
    # prospective record). 'reconstructed' = derived afterwards from append-only
    # snapshots (legitimate, but a backtest). Never blended in a headline number.
    origin: Mapped[str] = mapped_column(String, nullable=False, server_default=text("'live'"))
    # Canonical team the prediction is ABOUT, so the row stays auditable after a
    # home/away re-label. See migration 0008.
    subject_team: Mapped[str | None] = mapped_column(String)
    # Closing-line value: what Kalshi charged when the call was made vs its last
    # price before kickoff. Needs no outcome, so it reports months earlier.
    entry_prob: Mapped[float | None] = mapped_column(Numeric(6, 4))
    closing_prob: Mapped[float | None] = mapped_column(Numeric(6, 4))
    clv: Mapped[float | None] = mapped_column(Numeric(7, 4))
    flagged_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    graded_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class IngestRun(Base):
    """One ingestion pass. Records the JOB, not its output.

    Freshness of DATA cannot distinguish a dead poller from a genuinely quiet
    market; this can. See marketedge.ingestion.runs for the verdict matrix and
    for why rows are written in their own committed transaction.
    """

    __tablename__ = "ingest_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String, nullable=False)  # job name
    status: Mapped[str] = mapped_column(String, nullable=False)  # running|success|failure|abandoned
    started_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")
    )
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    events_seen: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    events_skipped: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    rows_attempted: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    rows_written: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    error_type: Mapped[str | None] = mapped_column(String)
    # ALWAYS written through redact() — a persisted credential is worse than a
    # logged one, because rows do not rotate.
    error_message: Mapped[str | None] = mapped_column(String)
    detail: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
