"""Glue between the plan, the governor, and the paid Odds API call.

Each replan reads three free sources:

1. **The Kalshi gate (DB).** Kalshi is polled every five minutes for free, and
   that pass stores every open game it can resolve. A sport is considered only
   if Kalshi lists a game for it starting within the gate horizon and the
   Kalshi poller has succeeded recently. No Kalshi market means nothing to
   compare a sportsbook price against, so a credit there buys nothing. The
   gate reads what the Kalshi poller stored rather than calling Kalshi again.
2. **The Odds API /events listing (free).** Exact start times. Kalshi events
   carry only a date parsed from the ticker, and a T-10m checkpoint needs the
   minute.
3. **odds_checkpoints (DB).** What has already been captured or skipped.

Those produce :class:`~arbitrium.ingestion.polling.GameSlot` rows for games that
are both Kalshi-backed and exactly timed; :func:`polling.plan_passes` turns them
into passes, and :func:`governor.admit` decides which ones spend.

Nothing here runs from a user-facing request. The API reads only the database.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from arbitrium.config import settings
from arbitrium.db.engine import get_session
from arbitrium.db.models import Event, IngestRun, OddsCheckpoint, OddsSnapshot
from arbitrium.ingestion import governor, odds_api
from arbitrium.ingestion.events import find_event_by_match
from arbitrium.ingestion.odds_api import OddsApiClient
from arbitrium.ingestion.polling import (
    GameSlot,
    PlannedPass,
    SportPolling,
    active_sports,
    plan_passes,
    utc_day_start,
)
from arbitrium.ingestion.result import IngestResult
from arbitrium.matching import EventKey, MatchStatus
from arbitrium.reference.teams import resolve_by_name

logger = logging.getLogger(__name__)

KALSHI_SOURCE = "kalshi"
STATUS_CAPTURED = "captured"
STATUS_SKIPPED = "skipped_budget"


# ---------------------------------------------------------------------------
# Free inputs
# ---------------------------------------------------------------------------


def kalshi_fresh(session: Session, *, now: datetime) -> bool:
    """Whether the Kalshi poller has succeeded recently enough to trust the gate."""
    last = session.execute(
        select(func.max(IngestRun.started_at)).where(
            IngestRun.source == KALSHI_SOURCE, IngestRun.status == "success"
        )
    ).scalar()
    if last is None:
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return now - last <= timedelta(seconds=settings.kalshi_gate_max_age_seconds)


def kalshi_gate_open(session: Session, sport: str, *, now: datetime) -> bool:
    """Whether Kalshi lists a game in ``sport`` that could start within the horizon.

    Kalshi-only rows hold midnight UTC of the game's US date, which can sit up to
    a day before the real start, hence the one-day lookback. The exact check
    happens later, against /events.
    """
    horizon = now + timedelta(hours=settings.kalshi_gate_horizon_hours)
    return session.execute(
        select(func.count()).select_from(Event).where(
            Event.sport == sport,
            Event.status == "scheduled",
            Event.kalshi_event_ticker.is_not(None),
            Event.scheduled_start >= now - timedelta(days=1),
            Event.scheduled_start <= horizon,
        )
    ).scalar() > 0


@dataclass
class EventsCache:
    """The free /events listing per sport key, refreshed on a timer."""

    ttl: float = field(default_factory=lambda: float(settings.odds_events_refresh_seconds))
    _entries: dict[str, tuple[float, list[dict]]] = field(default_factory=dict)

    def get(self, client: OddsApiClient, sport_key: str, *, clock=time.monotonic) -> list[dict]:
        hit = self._entries.get(sport_key)
        if hit is not None and clock() - hit[0] < self.ttl:
            return hit[1]
        try:
            events = client.get_events(sport_key)
        except Exception:
            if hit is None:
                raise
            # Start times rarely move; a stale listing beats an empty plan.
            logger.warning("Odds /events %s refresh failed; using the cached listing",
                           sport_key, exc_info=True)
            return hit[1]
        self._entries[sport_key] = (clock(), events)
        return events


_EVENTS = EventsCache()


def _parse_start(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _kalshi_event_id(session: Session, listing: dict, polling: SportPolling):
    """The Kalshi-backed event this /events entry is, or None."""
    odds_id = listing.get("id")
    if odds_id:
        row = session.execute(
            select(Event.id, Event.kalshi_event_ticker).where(Event.odds_api_event_id == odds_id)
        ).first()
        if row is not None:
            return row.id if row.kalshi_event_ticker else None

    home = resolve_by_name(polling.league, listing.get("home_team") or "")
    away = resolve_by_name(polling.league, listing.get("away_team") or "")
    start = _parse_start(listing.get("commence_time"))
    if home is None or away is None or start is None:
        return None
    event_id, status = find_event_by_match(
        session,
        EventKey(polling.sport, home.name, away.name, start),
        # Same rule as the ingest path: a row keyed to another Odds API id is
        # another game, so a repeat matchup cannot borrow its checkpoints.
        claimed=("odds_api", odds_id) if odds_id else None,
    )
    if status is not MatchStatus.MATCHED or event_id is None:
        return None
    ticker = session.execute(
        select(Event.kalshi_event_ticker).where(Event.id == event_id)
    ).scalar()
    return event_id if ticker else None


def _liquidity(session: Session, event_ids: list) -> dict:
    """Deepest resting Kalshi book per event over the last day, in dollars."""
    if not event_ids:
        return {}
    rows = session.execute(
        select(OddsSnapshot.event_id, func.max(OddsSnapshot.liquidity_score))
        .where(
            OddsSnapshot.event_id.in_(event_ids),
            OddsSnapshot.source == KALSHI_SOURCE,
            OddsSnapshot.ingested_at >= func.now() - timedelta(days=1),
        )
        .group_by(OddsSnapshot.event_id)
    ).all()
    return {eid: (float(liq) if liq is not None else None) for eid, liq in rows}


def upcoming_games(
    session: Session,
    client: OddsApiClient,
    polling: SportPolling,
    *,
    now: datetime,
    cache: EventsCache | None = None,
) -> list[GameSlot]:
    """Kalshi-backed, exactly-timed games in one sport within the gate horizon."""
    cache = cache or _EVENTS
    horizon = now + timedelta(hours=settings.kalshi_gate_horizon_hours)
    found: list[tuple[object, str, datetime]] = []
    for sport_key in polling.keys_in_season(now.date()):
        for listing in cache.get(client, sport_key):
            start = _parse_start(listing.get("commence_time"))
            if start is None or start > horizon or start < now - timedelta(hours=1):
                continue
            event_id = _kalshi_event_id(session, listing, polling)
            if event_id is not None:
                found.append((event_id, sport_key, start))
    liquidity = _liquidity(session, [eid for eid, _, _ in found])
    return [
        GameSlot(eid, polling.sport, key, start, liquidity.get(eid))
        for eid, key, start in found
    ]


def _done(session: Session, event_ids: list) -> set[tuple[object, str]]:
    if not event_ids:
        return set()
    rows = session.execute(
        select(OddsCheckpoint.event_id, OddsCheckpoint.checkpoint).where(
            OddsCheckpoint.event_id.in_(event_ids)
        )
    ).all()
    return {(r.event_id, r.checkpoint) for r in rows}


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------


def build_plan(
    session: Session, client: OddsApiClient, *, now: datetime, cache: EventsCache | None = None
) -> list[PlannedPass]:
    """Every outstanding pass for every gated sport, in time order."""
    if not kalshi_fresh(session, now=now):
        logger.info("Odds plan: Kalshi poller is not fresh; no sport is gated open.")
        return []
    games: list[GameSlot] = []
    for polling in active_sports(now.date()):
        if not kalshi_gate_open(session, polling.sport, now=now):
            continue
        games.extend(upcoming_games(session, client, polling, now=now, cache=cache))
    return plan_passes(games, _done(session, [g.event_id for g in games]), now=now)


def seconds_until_next_pass(*, now: datetime | None = None) -> float | None:
    """For the scheduler: how long until a pass is due, or None if none is planned."""
    moment = now or datetime.now(timezone.utc)
    if not settings.odds_api_key:
        return None
    session = get_session()
    try:
        with OddsApiClient() as client:
            plan = build_plan(session, client, now=moment)
    finally:
        session.close()
    if not plan:
        return None
    return max(0.0, (plan[0].at - moment).total_seconds())


def _record_checkpoints(session: Session, p: PlannedPass, status: str, reason: str | None) -> None:
    session.add_all(
        OddsCheckpoint(
            event_id=game.event_id,
            sport=game.sport,
            checkpoint=cp.name,
            status=status,
            reason=reason,
        )
        for game, cp in p.covers
    )
    session.commit()


def _later_today(plan: list[PlannedPass], current: PlannedPass) -> list[PlannedPass]:
    midnight = utc_day_start(current.at) + timedelta(days=1)
    return [p for p in plan if p is not current and p.sport == current.sport and p.at < midnight]


def run_due_passes(*, now: datetime | None = None) -> IngestResult:
    """Run (or deliberately skip) every pass due now. The scheduler's odds pass.

    A skipped pass is recorded as ``skipped_budget`` for each checkpoint it
    covered, so it is not re-planned and a missing close is explained in the
    table rather than left as a hole.
    """
    moment = now or datetime.now(timezone.utc)
    if not settings.odds_api_key:
        logger.warning("ODDS_API_KEY is not set; skipping Odds API ingest.")
        return IngestResult(source="odds_api")

    seen = skipped = attempted = written = 0
    session = get_session()
    try:
        with OddsApiClient() as client:
            plan = build_plan(session, client, now=moment)
        due = [p for p in plan if p.at <= moment]
        if not due:
            logger.info("Odds plan: nothing due (next at %s).", plan[0].at if plan else None)
        polling = {p.sport: p for p in active_sports(moment.date())}
        for p in due:
            decision = governor.admit(
                p,
                governor.load_budget(session, now=moment),
                cap=polling[p.sport].passes_per_day,
                non_close_calls_today=governor.non_close_odds_calls_today(
                    session, p.sport, now=moment
                ),
                later_today=_later_today(plan, p),
            )
            if not decision.admitted:
                logger.warning(
                    "Odds pass %s @ %s skipped (%s): %d checkpoint(s), top=%s",
                    p.sport, p.at, decision.reason, len(p.covers), p.top_checkpoint.name,
                )
                _record_checkpoints(session, p, STATUS_SKIPPED, decision.reason)
                continue
            logger.info(
                "Odds pass %s @ %s (%s): keys=%s, %d checkpoint(s), top=%s",
                p.sport, p.at, decision.reason, p.sport_keys, len(p.covers),
                p.top_checkpoint.name,
            )
            result = odds_api.run_ingest(p.sport_keys, checkpoint=p.top_checkpoint.name)
            _record_checkpoints(session, p, STATUS_CAPTURED, None)
            seen += result.events_seen
            skipped += result.events_skipped
            attempted += result.rows_attempted
            written += result.rows_written
    finally:
        session.close()

    return IngestResult(
        source="odds_api",
        events_seen=seen,
        events_skipped=skipped,
        rows_attempted=attempted,
        rows_written=written,
    )
