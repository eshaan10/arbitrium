"""FastAPI application.

Phase 2 adds /divergences. Remaining endpoints (/performance, /combos,
/events/{id}/history) land in Phase 3 and later.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.responses import FileResponse
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from arbitrium.calibration import grading
from arbitrium.calibration import model as cal_model
from arbitrium.calibration.clv import ClvObservation
from arbitrium.calibration.clv import summarise as summarise_clv
from arbitrium.calibration.sample import assess, brier_score, wilson_interval
from arbitrium.config import settings
from arbitrium.db.engine import SessionLocal, engine
from arbitrium.db.models import CalibrationHistory, Event, OddsSnapshot
from arbitrium.divergence.engine import DivergenceStatus, compute_divergences
from arbitrium.ingestion.polling import odds_poll_interval
from arbitrium.ingestion.resolution import PendingSummary, pending_resolution
from arbitrium.logging_config import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="Arbitrium API", version="0.2.0")


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Throwaway sanity-check UI (replaced by the Next.js dashboard in Phase 5).
_STATIC_DIR = Path(__file__).parent / "static"


# Fallback poll intervals, used when the caller does not supply live ones.
#
# Kalshi genuinely runs on a flat interval. Consensus DOES NOT: the Odds API
# poller is adaptive (see ingestion.polling), so the flat setting here is only a
# floor for callers without a session — anything judging a real gap must pass
# the interval actually in force. See staleness_report.
_SOURCE_INTERVALS = {
    "kalshi": lambda: settings.kalshi_poll_interval_seconds,
    "consensus": lambda: settings.odds_poll_interval_seconds,
}


def staleness_report(
    latest: dict[str, datetime | None],
    *,
    now: datetime | None = None,
    intervals: dict[str, int] | None = None,
) -> dict[str, dict]:
    """Turn per-source last-write times into a freshness verdict. Pure.

    Kept free of SQL so the policy — which interval applies, when a gap becomes
    alarming, what a never-written source reports — is testable without depending
    on whatever the live poller happens to have written to the shared table.

    ``intervals`` supplies the poll interval CURRENTLY in force per source. It
    matters because the Odds API schedule is adaptive: it drops to four times a
    day inside a week of kickoff and to daily beyond that, so judging it against
    the flat 15-minute setting reports a healthy poller as stale for most of the
    week — the monitor cries wolf and the one signal meant to catch a real
    outage stops meaning anything.
    """
    moment = now or datetime.now(timezone.utc)
    out: dict[str, dict] = {}
    for source, interval_fn in _SOURCE_INTERVALS.items():
        ts = latest.get(source)
        interval = (intervals or {}).get(source) or interval_fn()
        threshold = interval * settings.ingest_staleness_interval_multiple
        age = None if ts is None else int((moment - ts).total_seconds())
        out[source] = {
            "last_write_at": ts.isoformat() if ts else None,
            "age_seconds": age,
            # A source that has never written is stale, not absent — silence about
            # it would be the same blind spot this endpoint exists to remove.
            "stale": True if age is None else age > threshold,
            "stale_after_seconds": threshold,
            # Surfaced so a reader can tell a quiet schedule from a broken one.
            "poll_interval_seconds": interval,
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
    # The Odds API interval is adaptive, so read the one actually in force
    # rather than the flat setting — otherwise a poller running correctly on the
    # mid tier (4x/day) is reported stale against a 90-minute window.
    return staleness_report(
        {source: ts for source, ts in rows},
        intervals={"consensus": odds_poll_interval(db)},
    )


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
        verdict = "data_lost"  # past the window and not yet condemned
    elif countdown is not None and countdown <= poll_hours:
        verdict = "at_risk"  # fewer than one poll left to save it
    else:
        verdict = "healthy"

    return {
        "pending": summary.resolvable,
        "sports_pending": summary.sports,
        "hours_until_next_data_loss": None if countdown is None else round(countdown, 1),
        "unresolvable_pending_mark": summary.expired,
        # Losses already recorded. Kept visible after marking so a permanent
        # loss does not vanish from health the instant it is written down.
        "unresolvable_recorded": summary.unresolvable_recorded,
        "window_hours": settings.resolution_unresolvable_after_hours,
        "verdict": verdict,
    }


@app.get("/health")
def health(
    strict: bool = Query(
        False,
        description=(
            "Return HTTP 503 instead of 200 when status is not 'ok'. For uptime "
            "monitors, which alert on status codes rather than JSON bodies."
        ),
    ),
    response: Response = None,  # type: ignore[assignment]
    db: Session = Depends(get_db),
) -> dict:
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
    # A deployed API whose scheduler has died looks perfectly healthy from the
    # outside — that is exactly how the original week-long outage stayed
    # invisible for a week. `strict` turns a degraded verdict into a non-200 so
    # an external uptime monitor can page on it without parsing JSON, while the
    # default stays 200 so the dashboard can render the reason.
    if strict and not healthy and response is not None:
        response.status_code = 503

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
    ``divergence`` number — see arbitrium.divergence.engine for why.

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
                # Provenance: is home/away still Kalshi's provisional guess, or
                # confirmed against The Odds API?
                "home_away_source": r.home_away_source,
                "kalshi_event_ticker": r.kalshi_event_ticker,
                "odds_api_event_id": r.odds_api_event_id,
                "max_abs_divergence": _r(r.max_abs_divergence),
                "best_net_edge": _r(r.best_net_edge),
                "tradeable": r.tradeable,
                # The Kalshi-native directional view: one platform, one buy.
                # NOT guaranteed — see KalshiRecommendation on why this must
                # never share language with arbitrage.
                "recommendation": (
                    {
                        "team": r.recommendation.team,
                        "side": r.recommendation.side,          # 'yes' | 'no', both buys
                        "price": _r(r.recommendation.price, 4),
                        "fair_value": _r(r.recommendation.fair_value, 4),
                        "edge": _r(r.recommendation.edge, 4),
                        "wins_if": r.recommendation.wins_if,
                        "max_contracts": r.recommendation.max_contracts,
                        "max_stake": _r(r.recommendation.max_stake, 2),
                    }
                    if r.recommendation
                    else None
                ),
                "kalshi_series": r.kalshi_series,
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
                        # A Kalshi user cannot act on an arbitrage with no Kalshi
                        # leg without holding both named sportsbook accounts, so
                        # say so rather than implying it is available to them.
                        "venues": sorted({l.venue for l in r.arbitrage.legs}),
                        "includes_kalshi": any(l.venue == "kalshi" for l in r.arbitrage.legs),
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
                        "kalshi_bid": _r(o.kalshi_bid, 4),
                        "kalshi_ask": _r(o.kalshi_ask, 4),
                        "kalshi_ask_size": o.kalshi_ask_size,
                        "kalshi_bid_size": o.kalshi_bid_size,
                        "expected_value_at_depth": _r(o.expected_value_at_depth, 4),
                        # Raw per-book American odds, so "9 books" can be shown
                        # as nine named prices instead of an abstract count.
                        "books": o.book_prices,
                        "tradeable": o.tradeable,
                    }
                    for o in r.outcomes
                ],
            }
            for r in results
        ],
    }


@app.get("/events/{event_id}/history")
def event_history(
    event_id: uuid.UUID,
    limit: int = Query(400, ge=1, le=2000),
    db: Session = Depends(get_db),
) -> dict:
    """Append-only price history for one event, as a series per source and team.

    Deliberately a SEPARATE endpoint rather than a field on /divergences: history
    is only wanted when someone opens a single event, and inlining it would make
    the list response grow without bound as snapshots accumulate.

    Series are short right now, and honestly so — the dedup trigger records only
    genuine price CHANGES, and adaptive polling drops to daily when kickoff is
    weeks away. A flat series means the price genuinely did not move, not that
    collection failed; ``points`` is returned so a caller can say which.
    """
    ev = db.get(Event, event_id)
    if ev is None:
        raise HTTPException(status_code=404, detail="Unknown event")

    rows = db.execute(
        select(
            OddsSnapshot.source,
            OddsSnapshot.team,
            OddsSnapshot.implied_probability,
            OddsSnapshot.snapshot_time,
        )
        .where(OddsSnapshot.event_id == event_id)
        .order_by(OddsSnapshot.snapshot_time, OddsSnapshot.id)
        .limit(limit)
    ).all()

    series: dict[str, dict] = {}
    for r in rows:
        key = f"{r.source}|{r.team or 'draw'}"
        s = series.setdefault(
            key, {"source": r.source, "team": r.team, "points": []}
        )
        s["points"].append(
            {"t": r.snapshot_time.isoformat(), "p": float(r.implied_probability)}
        )

    return {
        "event_id": str(event_id),
        "home_team": ev.home_team,
        "away_team": ev.away_team,
        "series": list(series.values()),
        "total_points": len(rows),
    }


@app.get("/events/lookup")
def events_lookup(
    ids: str = Query(..., description="Comma-separated event ids."),
    db: Session = Depends(get_db),
) -> dict:
    """Basic records for specific events, REGARDLESS of status.

    /divergences deliberately scores only scheduled events, so a game that has
    kicked off disappears from it entirely. That is correct for a list of things
    you might act on, but it means a client holding a saved event id — a pinned
    matchup — has no way to find out what happened. This is that lookup.

    Returns what was actually recorded and nothing more: a winner only if one
    was resolved, scores only if they were collected, and the reason a game was
    declared unresolvable when that is what happened. An event id that does not
    exist is simply absent from the response rather than faked into a row.
    """
    wanted: list[uuid.UUID] = []
    for raw in ids.split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            wanted.append(uuid.UUID(raw))
        except ValueError:
            # A malformed id is a client bug, not a server error; skip it and
            # let the caller notice the row is missing.
            continue

    if not wanted:
        return {"events": [], "count": 0}

    rows = db.execute(
        select(Event).where(Event.id.in_(wanted[:200]))
    ).scalars().all()

    return {
        "count": len(rows),
        "events": [
            {
                "event_id": str(e.id),
                "sport": e.sport,
                "league": e.league,
                "home_team": e.home_team,
                "away_team": e.away_team,
                "scheduled_start": e.scheduled_start.isoformat(),
                "status": e.status,
                "winner_team": e.winner_team,
                "home_score": e.home_score,
                "away_score": e.away_score,
                "resolved_at": e.resolved_at.isoformat() if e.resolved_at else None,
                "resolution_source": e.resolution_source,
                # Set when the scoreboard window closed before an outcome could
                # be collected. The result is gone permanently, and saying so is
                # the only honest thing left to report.
                "unresolvable_reason": e.unresolvable_reason,
            }
            for e in rows
        ],
    }


@app.get("/activity")
def activity(
    hours: int = Query(24, ge=1, le=168, description="Look-back window."),
    limit: int = Query(40, ge=1, le=200, description="Max recent changes returned."),
    movers_limit: int = Query(5, ge=1, le=25),
    db: Session = Depends(get_db),
) -> dict:
    """Recent real price movement across the whole feed.

    Exists because neither /divergences (no timestamps of last change) nor
    /events/{id}/history (one event at a time) can answer "what just moved?"
    without N requests. Two shapes from one window:

    * ``changes`` — individual price moves, newest first, each with the price it
      moved FROM. Every row here is a genuine move: the dedup trigger only
      admits a snapshot when the price actually changed, so an unchanged re-poll
      cannot appear.
    * ``movers`` — the widest swing per event over the window.

    Deliberately NOT a record of arbitrage appearing. Arbitrage is computed on
    read and never stored, so there is no history of when one opened; claiming
    otherwise here would be inventing an event that was never observed.

    Cheap by construction: ``idx_snapshots_snapshot_time`` covers the window
    scan, and both queries measured under 2ms on the live table. No caching.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    # The price a row moved FROM. Partitioned per series and computed over all
    # history, not just the window, so the oldest change inside the window still
    # reports a real previous price instead of null.
    prev = func.lag(OddsSnapshot.implied_probability).over(
        partition_by=(OddsSnapshot.event_id, OddsSnapshot.source, OddsSnapshot.team),
        order_by=OddsSnapshot.snapshot_time,
    )
    windowed = (
        select(
            OddsSnapshot.event_id.label("event_id"),
            OddsSnapshot.source.label("source"),
            OddsSnapshot.team.label("team"),
            OddsSnapshot.implied_probability.label("to_p"),
            prev.label("from_p"),
            OddsSnapshot.snapshot_time.label("at"),
        ).subquery()
    )

    change_rows = db.execute(
        select(
            windowed.c.event_id, windowed.c.source, windowed.c.team,
            windowed.c.to_p, windowed.c.from_p, windowed.c.at,
            Event.home_team, Event.away_team, Event.sport,
        )
        .join(Event, Event.id == windowed.c.event_id)
        .where(windowed.c.at >= since, windowed.c.from_p.isnot(None))
        .order_by(windowed.c.at.desc())
        .limit(limit)
    ).all()

    changes = [
        {
            "event_id": str(r.event_id),
            "sport": r.sport,
            "home_team": r.home_team,
            "away_team": r.away_team,
            "source": r.source,
            "team": r.team,
            "from": _r(float(r.from_p), 4),
            "to": _r(float(r.to_p), 4),
            "delta": _r(float(r.to_p) - float(r.from_p), 4),
            "at": r.at.isoformat(),
        }
        for r in change_rows
    ]

    # Movement is measured on KALSHI only. The consensus polls on an adaptive
    # schedule that can be four times a day, so a "biggest mover" ranked across
    # both sources would mostly rank how often each source was sampled.
    swing = (func.max(OddsSnapshot.implied_probability)
             - func.min(OddsSnapshot.implied_probability)).label("swing")
    mover_rows = db.execute(
        select(
            OddsSnapshot.event_id, OddsSnapshot.team, swing,
            func.count().label("changes"),
            Event.home_team, Event.away_team, Event.sport,
        )
        .join(Event, Event.id == OddsSnapshot.event_id)
        .where(OddsSnapshot.source == "kalshi", OddsSnapshot.snapshot_time >= since)
        .group_by(
            OddsSnapshot.event_id, OddsSnapshot.team,
            Event.home_team, Event.away_team, Event.sport,
        )
        .having(func.count() > 1)
        .order_by(swing.desc())
        .limit(movers_limit)
    ).all()

    movers = [
        {
            "event_id": str(r.event_id),
            "sport": r.sport,
            "home_team": r.home_team,
            "away_team": r.away_team,
            "team": r.team,
            "swing": _r(float(r.swing), 4),
            "changes": r.changes,
        }
        for r in mover_rows
    ]

    return {
        "since": since.isoformat(),
        "window_hours": hours,
        "changes": changes,
        "movers": movers,
        # So a caller can distinguish "nothing moved" from "we stopped looking".
        "counts": {"changes": len(changes), "movers": len(movers)},
    }


def _gated(pairs: list, label: str) -> dict:
    """Report a body of evidence, with the sample gate attached to every number.

    Nothing here is emitted without its verdict. A rate is withheld entirely
    below the floor rather than shown with a caveat, because a number that
    exists gets quoted regardless of the words next to it.
    """
    verdict = assess(len(pairs))
    out: dict = {
        "label": label,
        "n": verdict.n,
        "status": verdict.status.value,
        "reason": verdict.reason,
        "accuracy": None,
        "accuracy_95ci": None,
        "brier_score": None,
        "reliability_bins": [],
        "calibration_curve": None,
    }
    if not verdict.may_report_rate:
        return out

    hits = sum(1 for _, hit in pairs if hit)
    ci = wilson_interval(hits, len(pairs))
    out["accuracy"] = round(hits / len(pairs), 4)
    out["accuracy_95ci"] = None if ci is None else [round(ci[0], 4), round(ci[1], 4)]
    out["brier_score"] = round(brier_score(pairs), 4)
    out["reliability_bins"] = [
        {
            "range": [b.lower, b.upper], "n": b.n,
            "mean_predicted": None if b.mean_predicted is None else round(b.mean_predicted, 4),
            "observed_rate": None if b.observed_rate is None else round(b.observed_rate, 4),
            "gap": None if b.gap is None else round(b.gap, 4),
        }
        for b in cal_model.reliability_bins(pairs, settings.calibration_bins)
    ]

    fitted = cal_model.fit(pairs)
    if fitted.fitted:
        out["calibration_curve"] = [
            {"predicted": round(pt.predicted, 4), "calibrated": round(pt.calibrated, 4), "n": pt.n}
            for pt in fitted.points
        ]
    return out


@app.get("/performance")
def performance(db: Session = Depends(get_db)) -> dict:
    """The system grading its own accuracy — with the sample size in front.

    Three separate bodies of evidence, never blended:

    * SOURCE RELIABILITY tests the project's premise, that sportsbook consensus
      is a better probability estimate than Kalshi's price. Derived from
      append-only snapshots plus recorded winners, so it needs no prior recording.
    * TRACK RECORD grades what the system actually recommended, split by origin:
      'live' is a genuine prospective record, 'reconstructed' is a backtest built
      from history. Reported apart so a backtest cannot borrow the credibility of
      a live record.
    * CLOSING-LINE VALUE needs no outcomes at all, only price history, so it is
      the one signal available before enough games resolve. It is evidence about
      the SIGNAL, not proof of profit.
    """
    sources = {
        src: _gated(grading.source_reliability_pairs(db, src), f"{src} closing price")
        for src in ("kalshi", "consensus")
    }

    track: dict[str, dict] = {}
    clv_by_origin: dict[str, dict] = {}
    for origin in (grading.ORIGIN_LIVE, grading.ORIGIN_RECONSTRUCTED):
        rows = db.execute(
            select(CalibrationHistory).where(
                CalibrationHistory.origin == origin,
                CalibrationHistory.outcome_correct.isnot(None),
            )
        ).scalars().all()
        track[origin] = _gated(
            [(float(r.predicted_prob), bool(r.outcome_correct)) for r in rows],
            f"recommendations ({origin})",
        )

        priced = db.execute(
            select(CalibrationHistory).where(
                CalibrationHistory.origin == origin,
                CalibrationHistory.clv.isnot(None),
            )
        ).scalars().all()
        summary = summarise_clv([
            ClvObservation(
                event_id=r.event_id, team=r.subject_team or "", side="yes",
                entry_prob=float(r.entry_prob), closing_prob=float(r.closing_prob),
                entry_at=r.flagged_at, closing_at=r.flagged_at,
            )
            for r in priced if r.entry_prob is not None and r.closing_prob is not None
        ])
        clv_by_origin[origin] = {
            "n": summary.n,
            "mean_clv": None if summary.mean_clv is None else round(summary.mean_clv, 4),
            "beat_close": summary.beat_close,
            "beat_rate": None if summary.beat_rate is None else round(summary.beat_rate, 4),
        }

    return {
        "thresholds": {
            "min_report_samples": settings.calibration_min_report_samples,
            "min_fit_samples": settings.calibration_min_fit_samples,
            "trusted_samples": settings.calibration_trusted_samples,
        },
        "source_reliability": sources,
        "track_record": track,
        "closing_line_value": clv_by_origin,
        "note": (
            "Counted in GAMES, not outcome rows: the two sides of a two-way market "
            "are one bet. A curve is refused below the fit floor rather than shown "
            "with a warning, and stays provisional for a full first season."
        ),
    }


@app.get("/preview", include_in_schema=False)
def preview() -> FileResponse:
    """Serve the throwaway sanity-check UI. Replaced by Next.js in Phase 5."""
    return FileResponse(_STATIC_DIR / "preview.html")
