"""FastAPI application.

Phase 2 adds /divergences. Remaining endpoints (/performance, /combos,
/events/{id}/history) land in Phase 3 and later.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from marketedge.config import settings
from marketedge.db.engine import SessionLocal, engine
from marketedge.db.models import OddsSnapshot
from marketedge.divergence.engine import DivergenceStatus, compute_divergences
from marketedge.ingestion.resolution import PendingSummary, pending_resolution
from marketedge.logging_config import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="MarketEdge API", version="0.2.0")


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Throwaway sanity-check UI (replaced by the Next.js dashboard in Phase 5).
_STATIC_DIR = Path(__file__).parent / "static"


# Per-source poll intervals, for judging whether a gap in writes is alarming.
_SOURCE_INTERVALS = {
    "kalshi": lambda: settings.kalshi_poll_interval_seconds,
    "consensus": lambda: settings.odds_poll_interval_seconds,
}


def staleness_report(
    latest: dict[str, datetime | None], *, now: datetime | None = None
) -> dict[str, dict]:
    """Turn per-source last-write times into a freshness verdict. Pure.

    Kept free of SQL so the policy — which interval applies, when a gap becomes
    alarming, what a never-written source reports — is testable without depending
    on whatever the live poller happens to have written to the shared table.
    """
    moment = now or datetime.now(timezone.utc)
    out: dict[str, dict] = {}
    for source, interval_fn in _SOURCE_INTERVALS.items():
        ts = latest.get(source)
        threshold = interval_fn() * settings.ingest_staleness_interval_multiple
        age = None if ts is None else int((moment - ts).total_seconds())
        out[source] = {
            "last_write_at": ts.isoformat() if ts else None,
            "age_seconds": age,
            # A source that has never written is stale, not absent — silence about
            # it would be the same blind spot this endpoint exists to remove.
            "stale": True if age is None else age > threshold,
            "stale_after_seconds": threshold,
        }
    return out


def _ingestion_freshness(db: Session) -> dict[str, dict]:
    """Per-source write recency, derived from the append-only table itself.

    Layer 3 of ingest failure visibility. Unlike the scheduler's in-process
    counters this survives a restart or a crash loop — if the poller dies, this
    keeps reporting a growing age. One grouped aggregate, no new table.

    ``stale`` is a heuristic, not proof of breakage: the dedup trigger legitimately
    suppresses writes in a quiet market, so a stale source means "look at this",
    not "this is definitely broken".
    """
    rows = db.execute(
        select(OddsSnapshot.source, func.max(OddsSnapshot.ingested_at)).group_by(
            OddsSnapshot.source
        )
    ).all()
    return staleness_report({source: ts for source, ts in rows})


def resolution_report(summary: PendingSummary, *, now: datetime | None = None) -> dict:
    """Outcome-collection health. Pure, so the policy is testable in isolation.

    ``hours_until_next_data_loss`` is the number that matters. Resolution is the
    one irreversible job in the system — the scores endpoint only reaches back 3
    days — so this converts "something is wrong" into "you have N hours to fix it
    before an outcome is gone permanently".
    """
    countdown = summary.hours_until_next_data_loss
    poll_hours = settings.resolution_poll_interval_seconds / 3600

    if summary.expired:
        verdict = "data_lost"  # already unrecoverable
    elif countdown is not None and countdown <= poll_hours:
        verdict = "at_risk"  # fewer than one poll left to save it
    else:
        verdict = "healthy"

    return {
        "pending": summary.resolvable,
        "sports_pending": summary.sports,
        "hours_until_next_data_loss": None if countdown is None else round(countdown, 1),
        "unresolvable_total": summary.expired,
        "window_hours": settings.resolution_unresolvable_after_hours,
        "verdict": verdict,
    }


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    """Liveness, database connectivity, ingestion freshness, and resolution risk.

    The freshness block exists because a silently broken ingest previously looked
    identical to a healthy one for a week. The resolution block exists because a
    missed outcome cannot be recovered at all — freshness tells you data stopped
    arriving, this tells you how long until that becomes permanent.
    """
    db_ok = False
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # noqa: BLE001 - report degraded rather than crash
        db_ok = False

    ingestion: dict[str, dict] = {}
    resolution: dict = {}
    if db_ok:
        try:
            ingestion = _ingestion_freshness(db)
        except Exception:  # noqa: BLE001 - health must never 500
            logger.exception("Failed to compute ingestion freshness")
        try:
            resolution = resolution_report(pending_resolution(db))
        except Exception:  # noqa: BLE001
            logger.exception("Failed to compute resolution health")

    healthy = (
        db_ok
        and not any(v["stale"] for v in ingestion.values())
        and resolution.get("verdict", "healthy") == "healthy"
    )
    return {
        "status": "ok" if healthy else "degraded",
        "database": "ok" if db_ok else "unavailable",
        "ingestion": ingestion,
        "resolution": resolution,
    }


def _r(value: float | None, places: int = 6) -> float | None:
    """Round a probability for output.

    Purely cosmetic: subtracting floats produces artifacts like
    0.010000000000000009 for a 1-cent spread. Six decimal places is ~1e-4 of a
    percentage point — far finer than any price we store — so nothing meaningful
    is lost.
    """
    return None if value is None else round(value, places)


@app.get("/divergences")
def divergences(
    sport: str | None = Query(None, description="Filter to one sport, e.g. 'nfl'."),
    status: DivergenceStatus | None = Query(
        None, description="Filter to one status. Omit to see everything, including untrusted."
    ),
    min_divergence: float | None = Query(
        None, ge=0.0, le=1.0,
        description="Minimum |kalshi - consensus|. Only scored events carry a number, "
                    "so this necessarily excludes unscored ones.",
    ),
    tradeable_only: bool = Query(
        False,
        description="Only events where some edge survives crossing the Kalshi spread. "
                    "Off by default: an untradeable divergence is still a real "
                    "measurement and is still reported.",
    ),
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> dict:
    """Kalshi vs sportsbook-consensus divergence for each scheduled event.

    Unscoreable events are RETURNED WITH A STATUS, not filtered out: a game with
    one bookmaker or one source is a fact about our coverage, and hiding it would
    let a caller assume the game doesn't exist. Only ``scored`` events carry a
    ``divergence`` number — see marketedge.divergence.engine for why.

    Each outcome reports two independent numbers: ``divergence`` (how far apart
    the sources' beliefs are) and ``net_edge_after_spread`` (what is actually
    capturable after crossing Kalshi's book). A large divergence with a negative
    net edge is real and worth nothing; both are shown so neither can be mistaken
    for the other.
    """
    results = compute_divergences(
        db, sport=sport, status=status, min_divergence=min_divergence,
        tradeable_only=tradeable_only, limit=limit,
    )
    counts: dict[str, int] = {}
    for r in results:
        counts[r.status.value] = counts.get(r.status.value, 0) + 1
    return {
        "min_consensus_books": settings.min_consensus_books,
        "count": len(results),
        "counts_by_status": counts,
        "tradeable_count": sum(1 for r in results if r.tradeable),
        "arbitrage_count": sum(1 for r in results if r.is_arbitrage),
        "divergences": [
            {
                "event_id": str(r.event_id),
                "sport": r.sport,
                "league": r.league,
                "home_team": r.home_team,
                "away_team": r.away_team,
                "scheduled_start": r.scheduled_start.isoformat(),
                "status": r.status.value,
                "reason": r.reason,
                "sources": r.sources,
                "n_books": r.n_books,
                "max_abs_divergence": _r(r.max_abs_divergence),
                "best_net_edge": _r(r.best_net_edge),
                "tradeable": r.tradeable,
                "best_expected_value": _r(r.best_expected_value, 4),
                # Risk-free, and therefore NOT a kind of net edge: an arbitrage
                # pays regardless of outcome, while a net edge only pays if the
                # sportsbook consensus is the better estimate. Own field, own
                # meaning, never folded into the edge numbers.
                "is_arbitrage": r.is_arbitrage,
                "arbitrage": (
                    {
                        "total_cost": _r(r.arbitrage.total_cost),
                        # GROSS: no fees, no execution risk. An upper bound, not a return.
                        "gross_profit": _r(r.arbitrage.gross_profit),
                        "limiting_depth": r.arbitrage.limiting_depth,
                        "legs": [
                            {
                                "team": leg.team,
                                "venue": leg.venue,
                                "implied_price": _r(leg.implied_price),
                            }
                            for leg in r.arbitrage.legs
                        ],
                    }
                    if r.arbitrage
                    else None
                ),
                # The single best fill. Outcome rows are alternative executions of
                # one directional view, not independent bets, so callers must act
                # on this rather than summing per-outcome edges.
                "best_trade": (
                    {
                        "team": r.best_trade.team,
                        "side": r.best_trade.trade_side,
                        "net_edge_after_spread": _r(r.best_trade.net_edge_after_spread),
                        "resting_depth": r.best_trade.resting_depth,
                    }
                    if r.best_trade
                    else None
                ),
                "outcomes": [
                    {
                        "team": o.team,
                        "kalshi_probability": _r(o.kalshi_probability),
                        "consensus_probability": _r(o.consensus_probability),
                        "divergence": _r(o.divergence),
                        "net_edge_after_spread": _r(o.net_edge_after_spread),
                        "trade_side": o.trade_side,
                        "spread": _r(o.spread),
                        "resting_depth": o.resting_depth,
                        "expected_value_at_depth": _r(o.expected_value_at_depth, 4),
                        "tradeable": o.tradeable,
                    }
                    for o in r.outcomes
                ],
            }
            for r in results
        ],
    }


@app.get("/preview", include_in_schema=False)
def preview() -> FileResponse:
    """Serve the throwaway sanity-check UI. Replaced by Next.js in Phase 5."""
    return FileResponse(_STATIC_DIR / "preview.html")
