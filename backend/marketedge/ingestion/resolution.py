"""Outcome resolution: who actually won, from The Odds API scores endpoint.

This is the ground truth calibration is graded against, and it is the one
**perishable** job in the system. The scores endpoint caps ``daysFrom`` at 3
(4 returns HTTP 422) and there is no deeper history, so an outcome not collected
within ~3 days of the final whistle is permanently unavailable from this source.
Unlike odds — where a missed poll only thins price history — a missed resolution
is irreversible. Everything below is shaped by that.

Consequences worth naming:

* **The database is asked before a credit is spent.** ``run_resolution`` fetches
  nothing unless events are actually awaiting a result, and derives which sports
  to fetch from those events. Off-season the resolver costs literally zero.
* **Nothing is ever overwritten.** A differing result for an already-final event
  is a CONFLICT: logged loudly, never applied. Either our first read was wrong or
  the source corrected itself, and both are facts a human should adjudicate.
* **Permanent loss is recorded, not merely logged.** An event past the window
  becomes ``status='unresolvable'`` with a reason, so the calibration set knows
  it is missing ground truth rather than quietly training on a biased subsample.

Results are stored as ``winner_team`` (a canonical team name), never as
'home'/'away'. See migration 0007: home/away is provisional for Kalshi events and
gets corrected later, so a relative label would silently change meaning.

``IngestResult.rows_written`` here counts EVENT RESOLUTIONS, not snapshot rows —
resolution writes no snapshots. Resolution-specific counters live in
``ingest_runs.detail``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from marketedge.config import settings
from marketedge.db.engine import get_session
from marketedge.db.models import Event
from marketedge.ingestion.espn import fetch_results
from marketedge.ingestion.events import find_event_by_match
from marketedge.ingestion.odds_api import ODDS_SPORTS, OddsApiClient, OddsSport
from marketedge.ingestion.outcomes import ScoreExtract, coerce_score, decide_winner
from marketedge.ingestion.result import IngestResult
from marketedge.matching import EventKey, MatchStatus
from marketedge.reference.teams import resolve_by_name

logger = logging.getLogger(__name__)

SOURCE = "resolution"
RESOLUTION_SOURCE = "odds_api_scores"
ESPN_RESOLUTION_SOURCE = "espn_scoreboard"
CONFLICT_MARKER = "RESOLUTION_CONFLICT"
DATA_LOST_MARKER = "RESOLUTION_DATA_LOST"
RECOVERED_MARKER = "RESOLUTION_RECOVERED"

STATUS_SCHEDULED = "scheduled"
STATUS_FINAL = "final"
STATUS_UNRESOLVABLE = "unresolvable"

REASON_WINDOW_EXPIRED = "window_expired"


# ---------------------------------------------------------------------------
# Pure extraction
# ---------------------------------------------------------------------------


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def extract_score(payload: dict, sport_cfg: OddsSport) -> ScoreExtract | None:
    """Build a result from one scores-endpoint event. None => skip, always logged.

    Skips (never guesses) when the game is not completed, when any score is
    unparseable, when the two score entries do not match the payload's own team
    names, or when a team cannot be canonicalised.
    """
    event_id = payload.get("id")
    if not payload.get("completed"):
        return None  # upcoming or in progress; `scores` is null for these

    raw_scores = payload.get("scores")
    if not isinstance(raw_scores, list) or len(raw_scores) < 2:
        logger.warning("Scores event %s: completed but no usable scores; skipping", event_id)
        return None

    home_raw, away_raw = payload.get("home_team"), payload.get("away_team")
    # Map by NAME, never by array position — the API guarantees no ordering, and
    # a positional assumption is the same bug shape that produced home_away_source.
    by_name = {s.get("name"): coerce_score(s.get("score")) for s in raw_scores}
    home_score, away_score = by_name.get(home_raw), by_name.get(away_raw)
    if home_score is None or away_score is None:
        logger.warning(
            "Scores event %s: could not match scores %r to teams home=%r away=%r; skipping",
            event_id, raw_scores, home_raw, away_raw,
        )
        return None

    home = resolve_by_name(sport_cfg.league, home_raw or "")
    away = resolve_by_name(sport_cfg.league, away_raw or "")
    if home is None or away is None:
        logger.warning(
            "Scores event %s: unresolved team(s) home=%r away=%r; skipping "
            "(registry gap — extend reference/teams.py)",
            event_id, home_raw, away_raw,
        )
        return None

    if home_score == 0 and away_score == 0:
        # For the sports supported today (NFL/NBA) a completed 0-0 is effectively
        # impossible, so this is far more likely a premature `completed` flag than
        # a real result. Skipping costs one more pass inside the window; recording
        # it would write a fabricated outcome into calibration ground truth.
        # REVISIT when soccer is enabled — there 0-0 is a legitimate common draw.
        logger.warning(
            "Scores event %s: completed with 0-0, which is implausible for %s; "
            "skipping rather than recording a likely-false result",
            event_id, sport_cfg.league,
        )
        return None

    return ScoreExtract(
        odds_api_event_id=event_id,
        home_team=home.name,
        away_team=away.name,
        home_score=home_score,
        away_score=away_score,
        winner_team=decide_winner(home.name, away.name, home_score, away_score),
        commence_time=_parse_iso(payload.get("commence_time")),
        sport=sport_cfg.sport,
    )


# ---------------------------------------------------------------------------
# Per-event write
# ---------------------------------------------------------------------------


class ResolutionOutcome(str, Enum):
    RESOLVED = "resolved"
    UNCHANGED = "unchanged"  # already resolved, identical data — safe re-run
    CONFLICT = "conflict"  # already resolved, DIFFERENT data — never overwritten
    NOT_FOUND = "not_found"  # a game we never ingested
    AMBIGUOUS = "ambiguous"


def _find_event_id(session: Session, extract: ScoreExtract):
    """Locate the event this result belongs to.

    Fast path is the odds event id, which the scores endpoint reuses verbatim
    (verified: 100/100 overlap). Kalshi-only events have no such id, so they fall
    back to the same matcher both ingestion paths use — otherwise every
    single-source event would be permanently ungradeable.
    """
    # The truthiness guard is load-bearing. SQLAlchemy renders `== None` as
    # `IS NULL`, so an extract with no odds id (every ESPN one) would otherwise
    # match an arbitrary Kalshi-only event and resolve the WRONG game.
    if extract.odds_api_event_id:
        event_id = session.execute(
            select(Event.id).where(Event.odds_api_event_id == extract.odds_api_event_id)
        ).scalar_one_or_none()
        if event_id is not None:
            return event_id, MatchStatus.MATCHED

    if extract.commence_time is None:
        return None, MatchStatus.UNMATCHED
    key = EventKey(extract.sport, extract.home_team, extract.away_team, extract.commence_time)
    return find_event_by_match(session, key)


def resolve_event(
    session: Session, extract: ScoreExtract, *, source: str = RESOLUTION_SOURCE
) -> ResolutionOutcome:
    """Record one result. Idempotent; never overwrites a differing result.

    ``source`` records WHICH provider supplied the outcome, so a value recovered
    from the fallback is distinguishable from one collected on time.
    """
    event_id, status = _find_event_id(session, extract)
    if status is MatchStatus.AMBIGUOUS:
        logger.warning(
            "Scores event %s: ambiguous match; skipping rather than resolving the wrong game",
            extract.odds_api_event_id,
        )
        return ResolutionOutcome.AMBIGUOUS
    if event_id is None:
        return ResolutionOutcome.NOT_FOUND

    # Only an unresolved row is ever written. Guarding in SQL rather than with a
    # read-then-write avoids a race between concurrent passes.
    result = session.execute(
        update(Event)
        # != FINAL, so an 'unresolvable' row can still be recovered by the
        # fallback; a genuinely final result is never overwritten.
        .where(Event.id == event_id, Event.status != STATUS_FINAL)
        .values(
            home_score=extract.home_score,
            away_score=extract.away_score,
            winner_team=extract.winner_team,
            status=STATUS_FINAL,
            # OUR observation time, not the game's end time. `scores[].last_update`
            # is the closest available proxy for the latter if ever needed.
            resolved_at=func.now(),
            resolution_source=source,
            unresolvable_reason=None,
            updated_at=func.now(),
        )
    )
    if result.rowcount == 1:
        return ResolutionOutcome.RESOLVED

    stored = session.execute(
        select(Event.home_score, Event.away_score, Event.winner_team).where(Event.id == event_id)
    ).one()
    if (stored.home_score, stored.away_score, stored.winner_team) == (
        extract.home_score, extract.away_score, extract.winner_team,
    ):
        return ResolutionOutcome.UNCHANGED

    logger.error(
        "%s: event %s already final as %s-%s (winner=%s) but the source now reports "
        "%s-%s (winner=%s). NOTHING was written — a human must adjudicate.",
        CONFLICT_MARKER, event_id, stored.home_score, stored.away_score, stored.winner_team,
        extract.home_score, extract.away_score, extract.winner_team,
    )
    return ResolutionOutcome.CONFLICT


# ---------------------------------------------------------------------------
# The pass, gated on cost
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PendingSummary:
    """What is awaiting a result, and how long before it can never be had."""

    resolvable: int
    sports: list[str]
    oldest_pending_start: datetime | None
    expired: int
    # Losses ALREADY recorded. Counted separately because `expired` only sees
    # rows still marked 'scheduled' — once a loss is condemned it drops out of
    # that count, and /health would otherwise forget the loss the moment it was
    # recorded, which defeats the point of recording it.
    unresolvable_recorded: int = 0

    @property
    def hours_until_next_data_loss(self) -> float | None:
        """Countdown on the oldest still-resolvable event. None if nothing pends.

        The headline health number: it converts "something is wrong" into
        "you have N hours to fix it".
        """
        if self.oldest_pending_start is None:
            return None
        deadline = self.oldest_pending_start + timedelta(
            hours=settings.resolution_unresolvable_after_hours
        )
        return (deadline - datetime.now(timezone.utc)).total_seconds() / 3600


def _window_bounds(now: datetime) -> tuple[datetime, datetime]:
    """(earliest still-resolvable kickoff, latest kickoff worth asking about)."""
    return (
        now - timedelta(hours=settings.resolution_unresolvable_after_hours),
        now - timedelta(minutes=settings.resolution_grace_minutes),
    )


def pending_resolution(session: Session, *, now: datetime | None = None) -> PendingSummary:
    """Events awaiting a result, plus those already past saving."""
    moment = now or datetime.now(timezone.utc)
    floor, ceiling = _window_bounds(moment)

    rows = session.execute(
        select(Event.sport, Event.scheduled_start).where(
            Event.status == STATUS_SCHEDULED,
            Event.scheduled_start <= ceiling,
            Event.scheduled_start >= floor,
        )
    ).all()
    expired = session.execute(
        select(func.count()).select_from(Event).where(
            Event.status == STATUS_SCHEDULED, Event.scheduled_start < floor
        )
    ).scalar() or 0

    recorded = session.execute(
        select(func.count()).select_from(Event).where(Event.status == STATUS_UNRESOLVABLE)
    ).scalar() or 0

    return PendingSummary(
        resolvable=len(rows),
        sports=sorted({r.sport for r in rows}),
        oldest_pending_start=min((r.scheduled_start for r in rows), default=None),
        expired=expired,
        unresolvable_recorded=recorded,
    )


def sport_keys_for(sports: list[str]) -> list[str]:
    """Odds API sport_keys covering the given canonical sports."""
    return sorted(k for k, cfg in ODDS_SPORTS.items() if cfg.sport in sports)


def backfill_targets(session: Session, *, now: datetime | None = None) -> list[tuple[str, datetime]]:
    """(sport, kickoff) pairs ESPN should try — everything the primary did not get.

    Includes rows already marked ``unresolvable``: with a source that has years
    of history, condemnation is no longer permanent, and recovering an outcome we
    merely failed to COLLECT restores real ground truth to the calibration set.
    """
    moment = now or datetime.now(timezone.utc)
    ceiling = moment - timedelta(minutes=settings.resolution_grace_minutes)
    rows = session.execute(
        select(Event.sport, Event.scheduled_start).where(
            Event.status.in_([STATUS_SCHEDULED, STATUS_UNRESOLVABLE]),
            Event.scheduled_start <= ceiling,
        )
    ).all()
    return [(r.sport, r.scheduled_start) for r in rows]


def mark_unresolvable(session: Session, *, now: datetime | None = None) -> int:
    """Condemn events past the window. Permanent data loss, recorded as such.

    Runs at the END of a pass, after the fetch, so an event resolved on its last
    chance is never wrongly condemned.
    """
    moment = now or datetime.now(timezone.utc)
    floor, _ = _window_bounds(moment)

    doomed = session.execute(
        select(Event.id, Event.home_team, Event.away_team, Event.scheduled_start).where(
            Event.status == STATUS_SCHEDULED, Event.scheduled_start < floor
        )
    ).all()
    if not doomed:
        return 0

    for e in doomed:
        logger.error(
            "%s: %s vs %s (kickoff %s) is %.1fh past the %dh resolution window. Its "
            "outcome is permanently unavailable and it can never be graded.",
            DATA_LOST_MARKER, e.away_team, e.home_team, e.scheduled_start,
            (moment - e.scheduled_start).total_seconds() / 3600,
            settings.resolution_unresolvable_after_hours,
        )
    session.execute(
        update(Event)
        .where(Event.id.in_([e.id for e in doomed]))
        .values(
            status=STATUS_UNRESOLVABLE,
            unresolvable_reason=REASON_WINDOW_EXPIRED,
            updated_at=func.now(),
        )
    )
    return len(doomed)


def _resolve_from_odds_api(session: Session, keys: list[str], counts: dict) -> int:
    """Primary pass: exact-ID join against The Odds API. Returns events seen."""
    undeclared = [k for k in keys if k not in ODDS_SPORTS]
    if undeclared:
        raise ValueError(
            f"Undeclared Odds API sport keys: {undeclared}. Add each to ODDS_SPORTS."
        )
    seen = 0
    with OddsApiClient() as client:
        for sport_key in keys:
            payloads = client.get_scores(sport_key)
            seen += len(payloads)
            for payload in payloads:
                extract = extract_score(payload, ODDS_SPORTS[sport_key])
                if extract is None:
                    continue
                counts[resolve_event(session, extract).value] += 1
        counts["quota_remaining"] = client.quota_remaining
    return seen


def _backfill_from_espn(session: Session, counts: dict) -> int:
    """Fallback pass. Returns the number of events RECOVERED from a lost state.

    Never raises: ESPN is undocumented and best-effort, and a failure here must
    not take down a pass the primary already served.
    """
    targets = backfill_targets(session)
    if not targets:
        return 0
    try:
        extracts = fetch_results(targets)
    except Exception:  # noqa: BLE001
        logger.warning("ESPN backfill failed; primary results are unaffected", exc_info=True)
        return 0

    recovered = 0
    for extract in extracts:
        was_condemned = session.execute(
            select(Event.id).where(
                Event.status == STATUS_UNRESOLVABLE,
                Event.home_team.in_([extract.home_team, extract.away_team]),
                Event.away_team.in_([extract.home_team, extract.away_team]),
            )
        ).first() is not None
        outcome = resolve_event(session, extract, source=ESPN_RESOLUTION_SOURCE)
        counts[outcome.value] = counts.get(outcome.value, 0) + 1
        if outcome is ResolutionOutcome.RESOLVED and was_condemned:
            recovered += 1
            logger.warning(
                "%s: recovered a previously unresolvable outcome from ESPN — "
                "%s %d, %s %d. It is graded again.",
                RECOVERED_MARKER, extract.home_team, extract.home_score,
                extract.away_team, extract.away_score,
            )
    return recovered


def run_resolution(sport_keys: list[str] | None = None) -> tuple[IngestResult, dict]:
    """Resolve everything awaiting a result. Returns (result, detail counters).

    Spends nothing when nothing is pending — the single most important cost
    decision here, since the resolver would otherwise burn 2 credits per sport
    per pass all off-season for no possible benefit.
    """
    counts = {k.value: 0 for k in ResolutionOutcome}
    counts["unresolvable_marked"] = 0
    session = get_session()
    try:
        pending = pending_resolution(session)
        keys = sport_keys if sport_keys is not None else sport_keys_for(pending.sports)

        seen = 0
        if pending.resolvable and keys:
            seen = _resolve_from_odds_api(session, keys, counts)
        else:
            logger.info(
                "Resolution: nothing awaiting a result; skipped the scores call (0 credits)."
            )

        # ESPN second, on whatever the primary could not supply — including rows
        # already condemned, which it can now un-condemn. Free, so breadth costs
        # nothing; mark_unresolvable runs only AFTER this, so nothing is declared
        # lost before both sources have tried.
        counts["recovered"] = _backfill_from_espn(session, counts)

        counts["unresolvable_marked"] = mark_unresolvable(session)
        session.commit()
    finally:
        session.close()

    resolved = counts[ResolutionOutcome.RESOLVED.value]
    result = IngestResult(
        source=SOURCE,
        events_seen=seen,
        events_skipped=counts[ResolutionOutcome.NOT_FOUND.value],
        rows_attempted=resolved,
        rows_written=resolved,  # event resolutions, not snapshot rows
    )
    logger.info("Resolution complete: %s | %s", result, counts)
    return result, counts
