"""Recording predictions and grading them once outcomes exist.

Two separate bodies of evidence, deliberately never merged:

**Source reliability** — when Kalshi says 60%, does it happen 60% of the time?
Same question for the sportsbook consensus. Computed on demand from append-only
snapshots plus ``events.winner_team``; it needs no recording at all, because
every resolved game already carries both sources' prices in history. This is what
tests the project's central premise, that the books are the better estimate.

**Recommendation track record** — when we said "buy X", did X win? This one must
be recorded, because a recommendation is a decision the system made at a moment
in time, and it cannot be re-derived without knowing what the system would have
done. That is ``calibration_history``.

ORIGIN IS LOAD-BEARING. A 'live' row was written before the game from data
available then. A 'reconstructed' row was derived afterwards from snapshot
history — legitimate, since it reads only pre-kickoff prices, and the only way to
build a usable sample in a first season, but it is a BACKTEST. The two are stored
separately and reported separately; blending them would let hindsight-adjacent
evidence borrow the credibility of a genuine prospective record.

ONE ROW PER GAME PER ORIGIN, enforced by a unique index. The two sides of a
two-way market are one bet, and counting both would shrink every confidence
interval by sqrt(2) for free.

KNOWN LIMITATION — book count can go stale. The dedup trigger (migration 0002)
suppresses a snapshot whose implied_probability is unchanged, keyed on price
ALONE. So if the consensus median stays put while more bookmakers join, the new
row is dropped and ``n_books`` remains at its old value. An event can therefore
sit below ``min_consensus_books`` in our history even after enough books have
actually quoted it, which suppresses both live recommendations and reconstructed
calls. Surfaced by a test that had to move the price to make a second row land.
Fixing it means widening the trigger's comparison beyond price, which changes
established dedup semantics and so is not being done unilaterally.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from marketedge.calibration import clv as clv_mod
from marketedge.config import settings
from marketedge.db.models import CalibrationHistory, Event, OddsSnapshot
from marketedge.divergence.engine import (
    CONSENSUS_SOURCE,
    KALSHI_SOURCE,
    OutcomeQuote,
    kalshi_recommendation,
)

logger = logging.getLogger(__name__)

ORIGIN_LIVE = "live"
ORIGIN_RECONSTRUCTED = "reconstructed"
STATUS_FINAL = "final"


# ---------------------------------------------------------------------------
# Source reliability — no recording required
# ---------------------------------------------------------------------------


def source_reliability_pairs(
    session: Session, source: str, *, at_close: bool = True
) -> list[tuple[float, bool]]:
    """(stated probability, did it happen) for every resolved game, one per game.

    Grades the HOME side only. The choice is arbitrary but must be consistent:
    grading both sides would double the sample with perfectly anti-correlated
    observations, which is not more evidence — it is the same evidence twice.

    ``at_close`` takes each game's last pre-kickoff price, the source's most
    informed statement about it.
    """
    events = session.execute(
        select(Event.id, Event.home_team, Event.winner_team, Event.scheduled_start)
        .where(Event.status == STATUS_FINAL, Event.winner_team.isnot(None))
    ).all()

    pairs: list[tuple[float, bool]] = []
    for ev in events:
        row = session.execute(
            select(OddsSnapshot.implied_probability)
            .where(
                OddsSnapshot.event_id == ev.id,
                OddsSnapshot.team == ev.home_team,
                OddsSnapshot.source == source,
                OddsSnapshot.snapshot_time < ev.scheduled_start,
            )
            .order_by(
                OddsSnapshot.snapshot_time.desc() if at_close
                else OddsSnapshot.snapshot_time.asc()
            )
            .limit(1)
        ).scalar()
        if row is None:
            continue  # that source never priced this game
        pairs.append((float(row), ev.winner_team == ev.home_team))
    return pairs


# ---------------------------------------------------------------------------
# Reconstructing what the system would have said
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReconstructedCall:
    """A recommendation the system would have made, at the moment it could first make it."""

    event: Event
    team: str
    side: str
    entry_prob: float
    fair_value: float
    edge: float
    n_books: int
    at: datetime


def _quotes_at(session: Session, event_id, moment: datetime) -> tuple[list, list]:
    """Latest Kalshi and consensus quotes as of ``moment`` — no look-ahead.

    Every snapshot considered is strictly at or before ``moment``, so a
    reconstruction can never see a price that did not exist yet.
    """
    rows = session.execute(
        select(
            OddsSnapshot.source, OddsSnapshot.outcome, OddsSnapshot.team,
            OddsSnapshot.implied_probability, OddsSnapshot.snapshot_time,
            OddsSnapshot.order_book_depth,
        )
        .where(OddsSnapshot.event_id == event_id, OddsSnapshot.snapshot_time <= moment)
        .order_by(OddsSnapshot.snapshot_time, OddsSnapshot.id)
    ).all()

    latest: dict[tuple[str, str], object] = {}
    for r in rows:
        latest[(r.source, r.team or r.outcome)] = r

    def build(source: str) -> list[OutcomeQuote]:
        out = []
        for (src, _key), r in latest.items():
            if src != source:
                continue
            depth = r.order_book_depth if isinstance(r.order_book_depth, dict) else {}
            out.append(OutcomeQuote(
                outcome=r.outcome, team=r.team,
                implied_probability=float(r.implied_probability),
                snapshot_time=r.snapshot_time,
                n_books=depth.get("n_books"),
                bid=_f(depth.get("yes_bid")), ask=_f(depth.get("yes_ask")),
                bid_size=_f(depth.get("yes_bid_size")), ask_size=_f(depth.get("yes_ask_size")),
                book_prices=depth.get("books_american"),
            ))
        return out

    return build(KALSHI_SOURCE), build(CONSENSUS_SOURCE)


def _f(v) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def reconstruct_first_call(session: Session, event: Event) -> ReconstructedCall | None:
    """The EARLIEST pre-kickoff moment the system would have recommended something.

    Earliest rather than latest on purpose. The last pre-kickoff price is the most
    informed, but entering there leaves no room for the market to move, so closing
    -line value would be ~0 by construction. The first actionable moment is also
    the honest one: it is when a user could actually have acted.
    """
    times = session.execute(
        select(OddsSnapshot.snapshot_time)
        .where(
            OddsSnapshot.event_id == event.id,
            OddsSnapshot.snapshot_time < event.scheduled_start,
        )
        .order_by(OddsSnapshot.snapshot_time)
        .distinct()
    ).scalars().all()

    for moment in times:
        kalshi, consensus = _quotes_at(session, event.id, moment)
        if not kalshi or not consensus:
            continue
        books = min((q.n_books for q in consensus if q.n_books is not None), default=0)
        if books < settings.min_consensus_books:
            continue  # the gate the live engine applies, applied identically here
        rec = kalshi_recommendation(kalshi, consensus)
        if rec is None:
            continue
        return ReconstructedCall(
            event=event, team=rec.team, side=rec.side, entry_prob=rec.price,
            fair_value=rec.fair_value, edge=rec.edge, n_books=books, at=moment,
        )
    return None


# ---------------------------------------------------------------------------
# Writing and grading
# ---------------------------------------------------------------------------


def confidence_band(n_books: int, contracts: float | None) -> str:
    """The 4-tier band, matching what the UI shows. Books AND depth, never edge size."""
    size = contracts or 0
    book_score = 2 if n_books >= 9 else 1.5 if n_books >= 5 else 1 if n_books >= 3 else 0
    depth_score = 2 if size >= 500 else 1.5 if size >= 100 else 1 if size >= 25 else 0.5 if size > 0 else 0
    bars = max(1, min(4, round(book_score + depth_score)))
    return ["", "weak", "moderate", "good", "strong"][bars]


def record_prediction(
    session: Session,
    *,
    event_id,
    subject_team: str,
    predicted_prob: float,
    divergence_score: float,
    band: str,
    entry_prob: float,
    flagged_at: datetime,
    origin: str,
    first_wins: bool = False,
) -> bool:
    """Write one prediction. ONE ROW PER (event, origin) — never per team.

    ``first_wins`` is the difference between the two origins, and it matters:

    * LIVE recording sets it. The recommended side genuinely moves as prices
      drift, and a track record must preserve what was FIRST said rather than
      quietly revising toward whatever looked best closest to kickoff. Later
      passes leave the row untouched.
    * RECONSTRUCTION leaves it False and upserts. It is deterministic — the same
      history yields the same call — so re-running should refresh rather than
      calcify a value computed by older logic.

    Returns True when a row was actually written.
    """
    values = dict(
        event_id=event_id,
        subject_team=subject_team,
        predicted_prob=predicted_prob,
        divergence_score=divergence_score,
        confidence_band=band,
        entry_prob=entry_prob,
        flagged_at=flagged_at,
        origin=origin,
    )
    stmt = pg_insert(CalibrationHistory).values(**values)
    if first_wins:
        stmt = stmt.on_conflict_do_nothing(index_elements=["event_id", "origin"])
    else:
        stmt = stmt.on_conflict_do_update(
            index_elements=["event_id", "origin"],
            set_={k: v for k, v in values.items() if k not in ("event_id", "origin")},
        )
    # RETURNING, not rowcount. psycopg reports rowcount = -1 for ON CONFLICT
    # inserts whether or not a row landed, so a rowcount test silently reports
    # zero writes on a pass that wrote everything — precisely the
    # attempted-versus-written confusion that hid a week-long outage. With
    # RETURNING, a skipped insert yields no row and an accepted one yields its id.
    return session.execute(stmt.returning(CalibrationHistory.id)).first() is not None


def grade_pending(session: Session, *, now: datetime | None = None) -> int:
    """Fill in outcomes and CLV for predictions whose games have now resolved.

    Grades against ``winner_team`` — a canonical name — rather than home/away, so
    a later re-labelling cannot silently flip a graded result.
    """
    moment = now or datetime.now(timezone.utc)
    rows = session.execute(
        select(CalibrationHistory, Event)
        .join(Event, Event.id == CalibrationHistory.event_id)
        .where(
            CalibrationHistory.outcome_correct.is_(None),
            Event.status == STATUS_FINAL,
        )
    ).all()

    graded = 0
    for record, event in rows:
        # A draw is neither correct nor incorrect for a "team wins" call; leaving
        # it ungraded is more honest than scoring it as a loss.
        if event.winner_team is None:
            continue
        record.outcome_correct = event.winner_team == record.subject_team
        record.graded_at = moment

        if record.closing_prob is None and record.entry_prob is not None:
            obs = clv_mod.observe(
                session, event, team=record.subject_team,
                side="yes",  # entry_prob is always what we paid for the chosen side
                entry_prob=float(record.entry_prob), entry_at=record.flagged_at,
            )
            if obs is not None:
                record.closing_prob = obs.closing_prob
                record.clv = obs.clv
        graded += 1
    return graded


def record_live_recommendations(session: Session, *, now: datetime | None = None) -> int:
    """Write a 'live' row for every upcoming event the system currently recommends.

    This is the genuinely prospective record — written BEFORE the game, from data
    available now, with no hindsight of any kind. It is the only evidence that can
    honestly be called a track record, which is why it is worth starting to
    accumulate immediately even though nothing can be reported from it for months.

    First call wins. The recommended side drifts with prices, and revising the
    recorded call as kickoff approaches would quietly select the version that had
    the most information — a track record graded on its best moment is not a track
    record.
    """
    moment = now or datetime.now(timezone.utc)
    events = session.execute(
        select(Event).where(
            Event.status == "scheduled",
            Event.scheduled_start > moment,
        )
    ).scalars().all()

    written = 0
    for event in events:
        kalshi, consensus = _quotes_at(session, event.id, moment)
        if not kalshi or not consensus:
            continue
        books = min((q.n_books for q in consensus if q.n_books is not None), default=0)
        if books < settings.min_consensus_books:
            continue
        rec = kalshi_recommendation(kalshi, consensus)
        if rec is None:
            continue
        if record_prediction(
            session,
            event_id=event.id,
            subject_team=rec.team,
            predicted_prob=rec.fair_value,
            divergence_score=abs(rec.fair_value - rec.price),
            band=confidence_band(books, rec.max_contracts),
            entry_prob=rec.price,
            flagged_at=moment,
            origin=ORIGIN_LIVE,
            first_wins=True,
        ):
            written += 1
    return written


def run_calibration(session_factory=None) -> dict:
    """One calibration pass: record live calls, then grade whatever has resolved.

    Ordered that way deliberately — recording is time-critical (a call not written
    before kickoff can never be written), while grading only needs to happen
    eventually.
    """
    from marketedge.db.engine import get_session

    session = (session_factory or get_session)()
    counts = {"live_recorded": 0, "graded": 0}
    try:
        counts["live_recorded"] = record_live_recommendations(session)
        counts["graded"] = grade_pending(session)
        session.commit()
    finally:
        session.close()
    logger.info("Calibration pass: %s", counts)
    return counts


def backfill_reconstructions(session: Session) -> int:
    """Reconstruct calls for every past event that has none recorded.

    Marked ``reconstructed`` so it is never mistaken for a live record.
    """
    events = session.execute(
        select(Event).where(Event.scheduled_start < datetime.now(timezone.utc))
    ).scalars().all()

    written = 0
    for event in events:
        call = reconstruct_first_call(session, event)
        if call is None:
            continue
        record_prediction(
            session,
            event_id=event.id,
            subject_team=call.team,
            predicted_prob=call.fair_value,
            divergence_score=abs(call.fair_value - call.entry_prob),
            band=confidence_band(call.n_books, None),
            entry_prob=call.entry_prob,
            flagged_at=call.at,
            origin=ORIGIN_RECONSTRUCTED,
        )
        written += 1
    return written
