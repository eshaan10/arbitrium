"""DB-level event resolution shared by the Kalshi and Odds API ingestion paths.

Keeps the pure matcher (:mod:`arbitrium.matching`) free of DB concerns while
giving both sources one place to answer "does an ``events`` row for this game
already exist?" — so a single game is never split into two rows (dual-key merge).
"""

from __future__ import annotations

import uuid as uuid_mod
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from arbitrium.db.models import Event
from arbitrium.matching import EventKey, MatchCandidate, MatchStatus, match_event, match_window

# The per-source key columns a caller may claim an event under. A row already
# holding a DIFFERENT value in the caller's own column is another game.
_CLAIM_COLUMNS: dict[str, InstrumentedAttribute] = {
    "kalshi": Event.kalshi_event_ticker,
    "odds_api": Event.odds_api_event_id,
}


def load_candidates(
    session: Session,
    sport: str,
    key: EventKey,
    window: timedelta,
    *,
    claimed: tuple[str, str] | None = None,
) -> list[MatchCandidate]:
    """Existing events for this sport whose start is within the match window.

    A cheap pre-filter on ``scheduled_start``; the matcher re-applies the precise
    window and team-pair check.

    ``claimed=(source, id)`` drops rows that source has already keyed to a
    different id. One game has exactly one Kalshi ticker and one Odds API id, so
    such a row is provably a different game — typically the other half of a
    repeat matchup a day or two away. Without this, that row is a perfectly good
    team-pair candidate and the nearer of the two simply wins.
    """
    lo = key.start - window
    hi = key.start + window
    stmt = select(
        Event.id, Event.sport, Event.home_team, Event.away_team, Event.scheduled_start
    ).where(
        Event.sport == sport,
        Event.scheduled_start >= lo,
        Event.scheduled_start <= hi,
    )
    if claimed is not None:
        source, ident = claimed
        col = _CLAIM_COLUMNS[source]
        stmt = stmt.where(or_(col.is_(None), col == ident))
    rows = session.execute(stmt).all()
    return [
        MatchCandidate(
            identifier=r.id,
            key=EventKey(r.sport, r.home_team, r.away_team, r.scheduled_start),
        )
        for r in rows
    ]


def find_event_by_match(
    session: Session,
    key: EventKey,
    *,
    window_days: int | None = None,
    claimed: tuple[str, str] | None = None,
) -> tuple[uuid_mod.UUID | None, MatchStatus]:
    """Find the existing event that ``key`` refers to, if any.

    Returns (event_id, status). MATCHED -> the id to merge into; UNMATCHED ->
    None (create a new row); AMBIGUOUS -> None (caller should skip and log rather
    than guess).

    The window defaults to the sport's own (:func:`arbitrium.matching.match_window`),
    so NBA's tight window applies to every caller without each one opting in.
    Pass ``claimed=(source, id)`` from an ingestion path — see
    :func:`load_candidates`.
    """
    window = timedelta(days=window_days) if window_days is not None else match_window(key.sport)
    candidates = load_candidates(session, key.sport, key, window, claimed=claimed)
    result = match_event(key, candidates, window=window)
    if result.status is MatchStatus.MATCHED and result.candidate is not None:
        return result.candidate.identifier, result.status  # type: ignore[return-value]
    return None, result.status
