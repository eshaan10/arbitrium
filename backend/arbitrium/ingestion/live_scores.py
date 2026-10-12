"""ESPN live-scoreboard ingestion.

Polls ESPN's public scoreboard, matches each event to an ``events`` row via the
same team-pair matcher used by Kalshi<->Odds-API merging, and UPSERTS the
latest state into ``event_live_state``. One ESPN call per sport returns the
entire slate, so records, venue and broadcast come from the same call that
delivers scores.

CADENCE is DB-gated, not clock-guessed:

* 30s while any event of this sport is in its live window (kickoff - 15m
  through final + 30m).
* 15m when the sport has scheduled games today but none live (records,
  venue and TV refresh).
* Never otherwise.

A second, slower pass covers the days ahead. The sweep above only reaches
yesterday and today, so a game later in the week had no row and the UI had
nothing but the event to show. Hourly, while the sport has a game in the next
``UPCOMING_DAYS``, it fetches that week from ESPN and writes ``scheduled`` rows
(records, venue, TV). It never overwrites a row that has moved past
``scheduled``: in-progress and final state belong to the fast pass.

The scheduler runs this pass unconditionally; the pass itself consults the DB
first and returns ``events_seen=0`` without making an HTTP call when there is
nothing to poll. That keeps the "no calls otherwise" guarantee visible in one
place and testable by stubbing the HTTP client.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from arbitrium.db.engine import SessionLocal
from arbitrium.db.models import Event, EventLiveState
from arbitrium.ingestion.espn import (
    ESPN_SPORTS,
    EspnClient,
    LIVE_STATUS_FINAL,
    LIVE_STATUS_IN_PROGRESS,
    LIVE_STATUS_HALFTIME,
    LIVE_STATUS_POSTPONED,
    LIVE_STATUS_SCHEDULED,
    LiveState,
    fetch_live_states,
    fetch_upcoming_states,
)
from arbitrium.ingestion.result import IngestResult
from arbitrium.matching import (
    EventKey,
    MatchCandidate,
    MatchStatus,
    match_event,
    match_window,
)

logger = logging.getLogger(__name__)

LIVE_WINDOW_PRE_KICKOFF = timedelta(minutes=15)
LIVE_WINDOW_POST_FINAL = timedelta(minutes=30)
# Fail-safe backstop: assume a game can run at most this long after kickoff
# before we stop treating it as "in a live window" purely on the strength of
# its scheduled start (used when ESPN has never written a live_state row).
MAX_GAME_DURATION = timedelta(hours=6)

CADENCE_LIVE_SECONDS = 30
CADENCE_SCHEDULED_SECONDS = 900
CADENCE_IDLE_SECONDS = 3600

UPCOMING_DAYS = 7
CADENCE_UPCOMING_SECONDS = 3600


_ACTIVE_STATUSES = (
    LIVE_STATUS_SCHEDULED,
    LIVE_STATUS_IN_PROGRESS,
    LIVE_STATUS_HALFTIME,
    LIVE_STATUS_POSTPONED,
)


def _has_live_window(db: Session, sport: str, now: datetime) -> bool:
    """True if any event of ``sport`` is inside its live window right now."""
    window_start = now - MAX_GAME_DURATION
    rows = db.execute(
        select(Event.id, EventLiveState.status, EventLiveState.updated_at)
        .join(EventLiveState, EventLiveState.event_id == Event.id, isouter=True)
        .where(
            Event.sport == sport,
            Event.scheduled_start - LIVE_WINDOW_PRE_KICKOFF <= now,
            or_(
                EventLiveState.status.is_(None),
                EventLiveState.status.in_(_ACTIVE_STATUSES),
                and_(
                    EventLiveState.status == LIVE_STATUS_FINAL,
                    EventLiveState.updated_at + LIVE_WINDOW_POST_FINAL >= now,
                ),
            ),
            # Pre-ESPN rows (no live_state) age out at MAX_GAME_DURATION so a
            # game from last week whose live_state we never recorded does not
            # keep the poller running forever.
            or_(
                EventLiveState.status.isnot(None),
                Event.scheduled_start >= window_start,
            ),
        )
        .limit(1)
    ).all()
    return bool(rows)


def _has_scheduled_today(db: Session, sport: str, now: datetime) -> bool:
    """True if the sport has any scheduled game within the next 24h."""
    row = db.execute(
        select(Event.id).where(
            Event.sport == sport,
            Event.scheduled_start >= now,
            Event.scheduled_start < now + timedelta(hours=24),
        ).limit(1)
    ).first()
    return row is not None


def compute_cadence_seconds(db: Session, sport: str, *, now: datetime | None = None) -> int | None:
    """Pick the poll cadence for ``sport`` based on current DB state.

    Returns one of ``CADENCE_LIVE_SECONDS``, ``CADENCE_SCHEDULED_SECONDS``, or
    ``None`` when the sport has nothing to poll (idle).
    """
    moment = now or datetime.now(timezone.utc)
    if _has_live_window(db, sport, moment):
        return CADENCE_LIVE_SECONDS
    if _has_scheduled_today(db, sport, moment):
        return CADENCE_SCHEDULED_SECONDS
    return None


def _has_upcoming(db: Session, sport: str, now: datetime) -> bool:
    """True if the sport has any game between now and ``UPCOMING_DAYS`` ahead."""
    row = db.execute(
        select(Event.id).where(
            Event.sport == sport,
            Event.scheduled_start >= now,
            Event.scheduled_start < now + timedelta(days=UPCOMING_DAYS + 1),
        ).limit(1)
    ).first()
    return row is not None


def _match_candidates(
    db: Session, sport: str, now: datetime, *, ahead: timedelta = timedelta(0),
) -> list[MatchCandidate]:
    """All sport events within the match window of today (both directions),
    extended ``ahead`` into the future for the upcoming pass."""
    window = match_window(sport)
    rows = db.execute(
        select(Event).where(
            Event.sport == sport,
            Event.scheduled_start >= now - window - timedelta(days=1),
            Event.scheduled_start <= now + window + timedelta(days=1) + ahead,
        )
    ).scalars().all()
    return [
        MatchCandidate(
            identifier=e.id,
            key=EventKey(
                sport=e.sport,
                home_team=e.home_team,
                away_team=e.away_team,
                start=e.scheduled_start,
            ),
        )
        for e in rows
    ]


def _upsert(db: Session, event_id, state: LiveState) -> None:
    stmt = pg_insert(EventLiveState).values(
        event_id=event_id,
        status=state.status,
        period=state.period,
        clock=state.clock,
        detail=state.detail,
        home_score=state.home_score,
        away_score=state.away_score,
        home_record=state.home_record,
        away_record=state.away_record,
        venue=state.venue,
        broadcast=state.broadcast,
        possession_side=state.possession_side,
        down_distance=state.down_distance,
        last_play=state.last_play,
        linescore=state.linescore,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[EventLiveState.event_id],
        set_={
            "status": stmt.excluded.status,
            "period": stmt.excluded.period,
            "clock": stmt.excluded.clock,
            "detail": stmt.excluded.detail,
            "home_score": stmt.excluded.home_score,
            "away_score": stmt.excluded.away_score,
            "home_record": stmt.excluded.home_record,
            "away_record": stmt.excluded.away_record,
            "venue": stmt.excluded.venue,
            "broadcast": stmt.excluded.broadcast,
            "possession_side": stmt.excluded.possession_side,
            "down_distance": stmt.excluded.down_distance,
            "last_play": stmt.excluded.last_play,
            "linescore": stmt.excluded.linescore,
        },
    )
    db.execute(stmt)


def _upsert_scheduled(db: Session, event_id, state: LiveState) -> bool:
    """Write a scheduled row's metadata. True if a row was inserted or updated.

    The conflict update only fires while the stored row is still ``scheduled``,
    so an hourly fetch can never roll a live or final game back.
    """
    stmt = pg_insert(EventLiveState).values(
        event_id=event_id,
        status=LIVE_STATUS_SCHEDULED,
        detail=state.detail,
        home_record=state.home_record,
        away_record=state.away_record,
        venue=state.venue,
        broadcast=state.broadcast,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[EventLiveState.event_id],
        set_={
            "detail": stmt.excluded.detail,
            "home_record": stmt.excluded.home_record,
            "away_record": stmt.excluded.away_record,
            "venue": stmt.excluded.venue,
            "broadcast": stmt.excluded.broadcast,
            "updated_at": func.now(),
        },
        where=EventLiveState.status == LIVE_STATUS_SCHEDULED,
    ).returning(EventLiveState.event_id)
    # RETURNING, not rowcount: a conflict the WHERE turns away returns no row.
    return db.execute(stmt).first() is not None


def _match(state: LiveState, candidates: list[MatchCandidate]) -> tuple[object | None, str]:
    """The event id an ESPN state belongs to, or None with why (logged)."""
    if state.commence_time is None:
        logger.warning(
            "ESPN event %s: missing commence_time; skipping live upsert",
            state.espn_event_id,
        )
        return None, "unmatched"
    target = EventKey(
        sport=state.sport,
        home_team=state.home_team,
        away_team=state.away_team,
        start=state.commence_time,
    )
    result = match_event(target, candidates)
    if result.status == MatchStatus.MATCHED and result.candidate is not None:
        return result.candidate.identifier, "matched"
    if result.status == MatchStatus.AMBIGUOUS:
        logger.warning(
            "ESPN event %s (%s vs %s @ %s): ambiguous match; skipping",
            state.espn_event_id, state.home_team, state.away_team,
            state.commence_time.isoformat(),
        )
        return None, "ambiguous"
    logger.warning(
        "ESPN event %s (%s vs %s @ %s): no matching event row; skipping",
        state.espn_event_id, state.home_team, state.away_team,
        state.commence_time.isoformat(),
    )
    return None, "unmatched"


def run_pass(
    sport: str,
    *,
    session_factory=SessionLocal,
    client: EspnClient | None = None,
    now: datetime | None = None,
) -> IngestResult:
    """One live-scores pass for one sport.

    DB-gates: if no live window and no scheduled-today, makes zero HTTP calls
    and returns an empty :class:`IngestResult`. Otherwise fetches the full
    sport slate from ESPN, matches each event, and upserts the live state.
    """
    moment = now or datetime.now(timezone.utc)
    source_name = f"live_scores_{sport}"
    start = time.monotonic()

    with session_factory() as db:
        cadence = compute_cadence_seconds(db, sport, now=moment)
        if cadence is None:
            logger.info(
                "live_scores sport=%s window=idle games_updated=0 unmatched=0 took=0ms",
                sport,
            )
            return IngestResult(source=source_name)

        states = fetch_live_states(sport, now=moment, client=client)
        candidates = _match_candidates(db, sport, moment)

        updated = 0
        unmatched = 0
        ambiguous = 0
        for state in states:
            event_id, outcome = _match(state, candidates)
            if event_id is not None:
                _upsert(db, event_id, state)
                updated += 1
            elif outcome == "ambiguous":
                ambiguous += 1
            else:
                unmatched += 1
        db.commit()

    took_ms = int((time.monotonic() - start) * 1000)
    window_label = "live" if cadence == CADENCE_LIVE_SECONDS else "scheduled"
    logger.info(
        "live_scores sport=%s window=%s games_updated=%d unmatched=%d ambiguous=%d took=%dms",
        sport, window_label, updated, unmatched, ambiguous, took_ms,
    )

    return IngestResult(
        source=source_name,
        events_seen=len(states),
        events_skipped=unmatched + ambiguous,
        rows_attempted=updated + unmatched + ambiguous,
        rows_written=updated,
    )


def run_upcoming_pass(
    sport: str,
    *,
    session_factory=SessionLocal,
    client: EspnClient | None = None,
    now: datetime | None = None,
) -> IngestResult:
    """Write ``scheduled`` rows for the sport's next ``UPCOMING_DAYS`` of games.

    DB-gated like :func:`run_pass`: no game in that span, no HTTP call. ESPN
    states that are not ``scheduled`` (today's live and final games) are
    skipped; the fast pass owns those.
    """
    moment = now or datetime.now(timezone.utc)
    source_name = f"live_scores_upcoming_{sport}"
    start = time.monotonic()

    with session_factory() as db:
        if not _has_upcoming(db, sport, moment):
            logger.info("live_scores_upcoming sport=%s window=idle games_updated=0", sport)
            return IngestResult(source=source_name)

        states = [
            s for s in fetch_upcoming_states(sport, days=UPCOMING_DAYS, now=moment, client=client)
            if s.status == LIVE_STATUS_SCHEDULED
        ]
        candidates = _match_candidates(
            db, sport, moment, ahead=timedelta(days=UPCOMING_DAYS)
        )

        written = 0
        matched = 0
        for state in states:
            event_id, _ = _match(state, candidates)
            if event_id is None:
                continue
            matched += 1
            if _upsert_scheduled(db, event_id, state):
                written += 1
        db.commit()

    took_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "live_scores_upcoming sport=%s games_updated=%d skipped=%d took=%dms",
        sport, written, len(states) - matched, took_ms,
    )
    return IngestResult(
        source=source_name,
        events_seen=len(states),
        events_skipped=len(states) - matched,
        rows_attempted=matched,
        rows_written=written,
    )


def pass_fn_for(sport: str):
    """Factory: closure the scheduler can call for this sport."""

    def _pass() -> IngestResult:
        return run_pass(sport)

    return _pass


def interval_fn_for(sport: str):
    """Factory: scheduler interval callable that re-queries the DB each tick."""

    def _interval() -> int:
        try:
            with SessionLocal() as db:
                cadence = compute_cadence_seconds(db, sport)
        except Exception:  # noqa: BLE001 - pacing must never kill the loop
            return CADENCE_IDLE_SECONDS
        return cadence if cadence is not None else CADENCE_IDLE_SECONDS

    return _interval


def upcoming_pass_fn_for(sport: str):
    """Factory: the hourly upcoming-games pass for this sport."""

    def _pass() -> IngestResult:
        return run_upcoming_pass(sport)

    return _pass
