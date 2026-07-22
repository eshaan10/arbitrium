"""Divergence scoring: Kalshi vs sportsbook consensus, per outcome.

The comparison joins the two sources on TEAM identity, never on home/away.
Kalshi's home/away is provisional ticker ordering and can be flipped later by The
Odds API, while ``odds_snapshots.team`` is correct at write time and immutable
(see migration 0005) — so a row's team is the only thing that means the same
before and after an authoritative flip. 'draw' outcomes carry no team and are
keyed by outcome instead.

Nothing is silently dropped. Every event with at least one source is returned,
carrying an explicit status that says how much to trust it:

  * ``scored`` — both sources present and the consensus clears
    ``settings.min_consensus_books``. This is the only status with a divergence
    number.
  * ``single_source_no_divergence`` — only one source priced this game (e.g. NFL
    preseason, which Kalshi lists but The Odds API's regular-season key does not
    cover). There is nothing to diverge FROM; saying so is more honest than
    omitting the game and letting the caller assume it doesn't exist.
  * ``insufficient_consensus`` — both sources present, but the "consensus" is a
    median over fewer than ``min_consensus_books`` bookmakers. Far from kickoff
    most events have exactly one book quoting, and a divergence measured against
    one book is noise wearing a precise-looking number. The observed prices are
    still returned (they are real observations); the SCORE is withheld, because a
    number that exists will get used regardless of the badge next to it.
  * ``incomparable_outcomes`` — both sources present but their outcome keys don't
    line up (a team resolved differently on each side). A real data bug; flagged
    loudly rather than scored across mismatched outcomes.

Design principles 1 and 3 are the whole point of this module: uncertainty is
labelled, not filtered, and no probability is emitted without the context needed
to judge it.
"""

from __future__ import annotations

import uuid as uuid_mod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from sqlalchemy import select
from sqlalchemy.orm import Session

from marketedge.config import settings
from marketedge.db.models import Event, OddsSnapshot

KALSHI_SOURCE = "kalshi"
CONSENSUS_SOURCE = "consensus"


class DivergenceStatus(str, Enum):
    SCORED = "scored"
    SINGLE_SOURCE = "single_source_no_divergence"
    INSUFFICIENT_CONSENSUS = "insufficient_consensus"
    INCOMPARABLE = "incomparable_outcomes"


@dataclass(frozen=True)
class OutcomeQuote:
    """One source's latest observation for one outcome of one event."""

    outcome: str  # 'home' | 'away' | 'draw' (provisional for Kalshi)
    team: str | None  # canonical; None for 'draw'
    implied_probability: float
    snapshot_time: datetime
    n_books: int | None = None  # consensus only: bookmakers behind the median

    @property
    def join_key(self) -> str:
        """Team identity, falling back to outcome for team-less outcomes ('draw')."""
        return self.team if self.team is not None else f"__{self.outcome}__"


@dataclass(frozen=True)
class OutcomeDivergence:
    """Per-outcome comparison. ``divergence`` is None unless the event is scored."""

    join_key: str
    team: str | None
    kalshi_probability: float | None
    consensus_probability: float | None
    divergence: float | None  # kalshi - consensus; >0 = Kalshi prices it higher

    @property
    def abs_divergence(self) -> float | None:
        return None if self.divergence is None else abs(self.divergence)


@dataclass(frozen=True)
class EventDivergence:
    event_id: uuid_mod.UUID
    sport: str
    league: str
    home_team: str
    away_team: str
    scheduled_start: datetime
    status: DivergenceStatus
    reason: str
    sources: list[str]
    n_books: int | None
    max_abs_divergence: float | None
    outcomes: list[OutcomeDivergence]


def _consensus_book_count(quotes: list[OutcomeQuote]) -> int | None:
    """Bookmakers behind a consensus, taken as the MINIMUM across its outcomes.

    Both outcomes normally come from the same set of books, but if they ever
    differ the weaker side is what limits how much the comparison can be trusted.
    """
    counts = [q.n_books for q in quotes if q.n_books is not None]
    return min(counts) if counts else None


def score_event(
    *,
    kalshi_quotes: list[OutcomeQuote],
    consensus_quotes: list[OutcomeQuote],
    min_books: int | None = None,
) -> tuple[DivergenceStatus, str, int | None, list[OutcomeDivergence], float | None]:
    """Pure scoring for one event. DB-free so every branch is unit-testable.

    Returns (status, reason, n_books, per-outcome rows, max |divergence|).
    """
    floor = settings.min_consensus_books if min_books is None else min_books
    kalshi = {q.join_key: q for q in kalshi_quotes}
    consensus = {q.join_key: q for q in consensus_quotes}
    n_books = _consensus_book_count(consensus_quotes)

    def rows(scored: bool) -> list[OutcomeDivergence]:
        out = []
        for key in sorted(set(kalshi) | set(consensus)):
            k, c = kalshi.get(key), consensus.get(key)
            div = (
                k.implied_probability - c.implied_probability
                if scored and k is not None and c is not None
                else None
            )
            out.append(
                OutcomeDivergence(
                    join_key=key,
                    team=(k or c).team,  # type: ignore[union-attr]
                    kalshi_probability=k.implied_probability if k else None,
                    consensus_probability=c.implied_probability if c else None,
                    divergence=div,
                )
            )
        return out

    if not kalshi or not consensus:
        present = [
            name
            for name, qs in ((KALSHI_SOURCE, kalshi), (CONSENSUS_SOURCE, consensus))
            if qs
        ]
        return (
            DivergenceStatus.SINGLE_SOURCE,
            f"only {present[0] if present else 'no'} priced this event; "
            "nothing to compare against",
            n_books,
            rows(scored=False),
            None,
        )

    if set(kalshi) != set(consensus):
        return (
            DivergenceStatus.INCOMPARABLE,
            f"outcome keys differ between sources: kalshi={sorted(kalshi)} "
            f"consensus={sorted(consensus)}",
            n_books,
            rows(scored=False),
            None,
        )

    if n_books is None or n_books < floor:
        return (
            DivergenceStatus.INSUFFICIENT_CONSENSUS,
            f"consensus is a median over {n_books if n_books is not None else 0} "
            f"bookmaker(s), below the floor of {floor}; observed prices shown, "
            "divergence deliberately not scored",
            n_books,
            rows(scored=False),
            None,
        )

    scored_rows = rows(scored=True)
    max_abs = max(
        (r.abs_divergence for r in scored_rows if r.abs_divergence is not None),
        default=None,
    )
    return (
        DivergenceStatus.SCORED,
        f"both sources present; consensus over {n_books} bookmakers",
        n_books,
        scored_rows,
        max_abs,
    )


def _latest_quotes(session: Session, event_ids: list[uuid_mod.UUID]) -> dict[
    tuple[uuid_mod.UUID, str], list[OutcomeQuote]
]:
    """Latest snapshot per (event, source, outcome/team), as {(event_id, source): quotes}.

    ``odds_snapshots`` is append-only, so "current price" is always the newest row
    rather than a mutated one. DISTINCT ON does that in one pass; the id tiebreak
    keeps it deterministic when two rows share a snapshot_time.
    """
    if not event_ids:
        return {}
    stmt = (
        select(
            OddsSnapshot.event_id,
            OddsSnapshot.source,
            OddsSnapshot.outcome,
            OddsSnapshot.team,
            OddsSnapshot.implied_probability,
            OddsSnapshot.snapshot_time,
            OddsSnapshot.order_book_depth,
        )
        .where(OddsSnapshot.event_id.in_(event_ids))
        .distinct(
            OddsSnapshot.event_id,
            OddsSnapshot.source,
            OddsSnapshot.outcome,
            OddsSnapshot.team,
        )
        .order_by(
            OddsSnapshot.event_id,
            OddsSnapshot.source,
            OddsSnapshot.outcome,
            OddsSnapshot.team,
            OddsSnapshot.snapshot_time.desc(),
            OddsSnapshot.id.desc(),
        )
    )
    out: dict[tuple[uuid_mod.UUID, str], list[OutcomeQuote]] = {}
    for r in session.execute(stmt).all():
        depth = r.order_book_depth or {}
        n_books = depth.get("n_books") if isinstance(depth, dict) else None
        out.setdefault((r.event_id, r.source), []).append(
            OutcomeQuote(
                outcome=r.outcome,
                team=r.team,
                implied_probability=float(r.implied_probability),
                snapshot_time=r.snapshot_time,
                n_books=n_books,
            )
        )
    return out


def compute_divergences(
    session: Session,
    *,
    sport: str | None = None,
    status: DivergenceStatus | None = None,
    min_divergence: float | None = None,
    limit: int = 200,
) -> list[EventDivergence]:
    """Score every scheduled event, newest kickoff first among the biggest gaps.

    Filters are applied AFTER scoring so that a filter can never turn "we don't
    trust this" into "this doesn't exist" — an event excluded by ``status`` was
    still evaluated and still says why.
    """
    ev_stmt = select(
        Event.id,
        Event.sport,
        Event.league,
        Event.home_team,
        Event.away_team,
        Event.scheduled_start,
    ).where(Event.status == "scheduled")
    if sport:
        ev_stmt = ev_stmt.where(Event.sport == sport)
    events = session.execute(ev_stmt.order_by(Event.scheduled_start)).all()

    quotes = _latest_quotes(session, [e.id for e in events])

    results: list[EventDivergence] = []
    for e in events:
        st, reason, n_books, rows, max_abs = score_event(
            kalshi_quotes=quotes.get((e.id, KALSHI_SOURCE), []),
            consensus_quotes=quotes.get((e.id, CONSENSUS_SOURCE), []),
        )
        results.append(
            EventDivergence(
                event_id=e.id,
                sport=e.sport,
                league=e.league,
                home_team=e.home_team,
                away_team=e.away_team,
                scheduled_start=e.scheduled_start,
                status=st,
                reason=reason,
                sources=sorted(
                    s for s in (KALSHI_SOURCE, CONSENSUS_SOURCE) if quotes.get((e.id, s))
                ),
                n_books=n_books,
                max_abs_divergence=max_abs,
                outcomes=rows,
            )
        )

    if status is not None:
        results = [r for r in results if r.status is status]
    if min_divergence is not None:
        # Only scored events carry a number, so this implicitly selects them —
        # by design: you cannot filter by a magnitude we refused to compute.
        results = [
            r for r in results
            if r.max_abs_divergence is not None and r.max_abs_divergence >= min_divergence
        ]

    results.sort(
        key=lambda r: (r.max_abs_divergence is not None, r.max_abs_divergence or 0.0),
        reverse=True,
    )
    return results[:limit]
