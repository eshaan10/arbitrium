"""DB-level event resolution shared by the Kalshi and Odds API ingestion paths.

Keeps the pure matcher (:mod:`arbitrium.matching`) free of DB concerns while
giving both sources one place to answer "does an ``events`` row for this game
already exist?" — so a single game is never split into two rows (dual-key merge).
"""

from __future__ import annotations

import uuid as uuid_mod
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from arbitrium.config import settings
from arbitrium.db.models import Event
from arbitrium.matching import EventKey, MatchCandidate, MatchStatus, match_event


def load_candidates(session: Session, sport: str, key: EventKey, window_days: int) -> list[MatchCandidate]:
    """Existing events for this sport whose start is within the match window.

    A cheap pre-filter on ``scheduled_start``; the matcher re-applies the precise
    window and team-pair check.
    """
    lo = key.start - timedelta(days=window_days)
    hi = key.start + timedelta(days=window_days)
    rows = session.execute(
        select(
            Event.id, Event.sport, Event.home_team, Event.away_team, Event.scheduled_start
        ).where(
            Event.sport == sport,
            Event.scheduled_start >= lo,
            Event.scheduled_start <= hi,
        )
    ).all()
    return [
        MatchCandidate(
            identifier=r.id,
            key=EventKey(r.sport, r.home_team, r.away_team, r.scheduled_start),
        )
        for r in rows
    ]


def find_event_by_match(
    session: Session, key: EventKey, *, window_days: int | None = None
) -> tuple[uuid_mod.UUID | None, MatchStatus]:
    """Find the existing event that ``key`` refers to, if any.

    Returns (event_id, status). MATCHED -> the id to merge into; UNMATCHED ->
    None (create a new row); AMBIGUOUS -> None (caller should skip and log rather
    than guess).
    """
    wd = window_days if window_days is not None else settings.event_match_window_days
    candidates = load_candidates(session, key.sport, key, wd)
    result = match_event(key, candidates, window_days=wd)
    if result.status is MatchStatus.MATCHED and result.candidate is not None:
        return result.candidate.identifier, result.status  # type: ignore[return-value]
    return None, result.status
