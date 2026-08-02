"""Adaptive poll pacing, so a fixed API budget is spent where it buys information.

The Odds API bills per request that returns events (empty responses are free) and
the plan allows 500 credits/month — about 16/day. A flat 15-minute interval costs
~96/day and exhausts the month in five days, which is exactly how the Phase 2
poller was configured.

Rather than slow everything down uniformly, pace each sport by how close its next
game is. Prices weeks from kickoff barely move, and closing-line value is measured
against the CLOSING line, so credits spent hours before kickoff buy real signal
while credits spent three weeks out buy almost none. Same total budget, far more
of it where the data matters.

The next kickoff comes from ``events.scheduled_start``, which we already store and
index — deciding how often to call the API costs no API calls.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from marketedge.config import settings
from marketedge.db.models import Event

logger = logging.getLogger(__name__)


def poll_interval_for(next_kickoff: datetime | None, *, now: datetime | None = None) -> int:
    """Seconds until this sport should next be polled.

    ``next_kickoff`` is the soonest upcoming game, or None when the sport has no
    scheduled games at all. Tiers are inclusive of their upper bound so a game
    exactly 24h out already counts as near.

    A kickoff in the PAST is treated as near: a game currently in progress is
    precisely when the closing line is being set, and it is also when a result
    becomes available.
    """
    if next_kickoff is None:
        return settings.odds_poll_far_seconds

    moment = now or datetime.now(timezone.utc)
    until = next_kickoff - moment

    if until <= timedelta(seconds=settings.odds_poll_near_horizon_seconds):
        return settings.odds_poll_near_seconds
    if until <= timedelta(seconds=settings.odds_poll_mid_horizon_seconds):
        return settings.odds_poll_mid_seconds
    return settings.odds_poll_far_seconds


def next_kickoff(session: Session, sports: list[str] | None = None) -> datetime | None:
    """Soonest upcoming kickoff across the given sports (all sports if None).

    Looks slightly into the past so a game underway still counts as upcoming —
    its line is still moving and its result is about to exist.
    """
    lookback = datetime.now(timezone.utc) - timedelta(
        seconds=settings.odds_poll_near_horizon_seconds
    )
    stmt = select(func.min(Event.scheduled_start)).where(Event.scheduled_start >= lookback)
    if sports:
        stmt = stmt.where(Event.sport.in_(sports))
    return session.execute(stmt).scalar()


def odds_poll_interval(session: Session, sports: list[str] | None = None) -> int:
    """Current poll interval for the Odds API, from the schedule we already hold."""
    interval = poll_interval_for(next_kickoff(session, sports))
    logger.debug("Odds API poll interval resolved to %ss", interval)
    return interval


def projected_daily_credits(interval_seconds: int, paid_sports: int = 1) -> float:
    """Credits/day at a given interval — used to prove the budget actually fits.

    Only sports returning events are billed, so ``paid_sports`` is the count of
    IN-SEASON sports, not the size of the registry.
    """
    return (86400 / interval_seconds) * paid_sports
