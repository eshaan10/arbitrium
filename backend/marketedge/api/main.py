"""FastAPI application.

Phase 2 adds /divergences. Remaining endpoints (/performance, /combos,
/events/{id}/history) land in Phase 3 and later.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, Query
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from marketedge.config import settings
from marketedge.db.engine import SessionLocal, engine
from marketedge.divergence.engine import DivergenceStatus, compute_divergences

app = FastAPI(title="MarketEdge API", version="0.2.0")


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Throwaway sanity-check UI (replaced by the Next.js dashboard in Phase 5).
_STATIC_DIR = Path(__file__).parent / "static"


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness + database connectivity check."""
    db_ok = False
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # noqa: BLE001 - report degraded rather than crash
        db_ok = False
    return {"status": "ok", "database": "ok" if db_ok else "unavailable"}


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
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> dict:
    """Kalshi vs sportsbook-consensus divergence for each scheduled event.

    Unscoreable events are RETURNED WITH A STATUS, not filtered out: a game with
    one bookmaker or one source is a fact about our coverage, and hiding it would
    let a caller assume the game doesn't exist. Only ``scored`` events carry a
    ``divergence`` number — see marketedge.divergence.engine for why.
    """
    results = compute_divergences(
        db, sport=sport, status=status, min_divergence=min_divergence, limit=limit
    )
    counts: dict[str, int] = {}
    for r in results:
        counts[r.status.value] = counts.get(r.status.value, 0) + 1
    return {
        "min_consensus_books": settings.min_consensus_books,
        "count": len(results),
        "counts_by_status": counts,
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
                "max_abs_divergence": r.max_abs_divergence,
                "outcomes": [
                    {
                        "team": o.team,
                        "kalshi_probability": o.kalshi_probability,
                        "consensus_probability": o.consensus_probability,
                        "divergence": o.divergence,
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
