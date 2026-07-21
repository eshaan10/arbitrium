"""FastAPI application.

Phase 1 exposes only a health check. Data endpoints (/divergences, /sports,
/events/{id}/history, /performance, /combos) land in Phase 2 and later.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from sqlalchemy import text

from marketedge.db.engine import engine

app = FastAPI(title="MarketEdge API", version="0.1.0")

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


@app.get("/preview", include_in_schema=False)
def preview() -> FileResponse:
    """Serve the throwaway sanity-check UI. Replaced by Next.js in Phase 5."""
    return FileResponse(_STATIC_DIR / "preview.html")
