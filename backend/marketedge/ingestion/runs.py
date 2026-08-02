"""Durable job history for ingestion passes.

``IngestHealth`` (in-process) answers "is this pass failing right now?" but dies
with the process. ``/health`` freshness infers liveness from DATA, which cannot
distinguish a dead poller from a genuinely quiet market — a healthy poll of a
static market writes nothing, and so does a poller that stopped running.

``ingest_runs`` records the JOB rather than its output, which turns that
heuristic into a decision procedure:

===============  =========  ============  ==========================
last run         status     rows_written  verdict
===============  =========  ============  ==========================
recent           success    > 0           healthy
recent           success    0             quiet (correct, not broken)
recent           failure    -             failing (alive but broken)
stale / running  any        -             dead (passes never complete)
none             -          -             never_ran
===============  =========  ============  ==========================

Four properties this module must preserve, each learned the hard way:

1. **Its own session, committed immediately.** Sharing the ingest transaction
   would let a failed pass roll back the evidence of its own failure — exactly
   the blind spot the table exists to remove.
2. **Two phases.** A single row written at the end records nothing when the
   process is killed. A stranded ``running`` row with an old ``started_at`` is
   the only positive evidence of a crash-looping worker.
3. **It can never break ingestion.** Every function swallows its own errors and
   returns None. A telemetry table must not take down the pipeline it observes.
4. **``error_message`` goes through redact().** An Odds API ``HTTPStatusError``
   embeds the key in its message, and a database row is a far worse place to
   leak a credential than a log line — rows do not rotate.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from marketedge.db.engine import get_session
from marketedge.db.models import IngestRun
from marketedge.ingestion.result import IngestResult
from marketedge.logging_config import redact

logger = logging.getLogger(__name__)

RUNNING = "running"
SUCCESS = "success"
FAILURE = "failure"
ABANDONED = "abandoned"


def start_run(source: str) -> int | None:
    """Open a ``running`` row and commit it before the pass begins.

    Returns the row id, or None if recording failed — callers pass that None
    straight back into :func:`finish_run` / :func:`fail_run`, which no-op on it.
    """
    try:
        session = get_session()
        try:
            run = IngestRun(
                source=source, status=RUNNING, started_at=datetime.now(timezone.utc)
            )
            session.add(run)
            session.commit()
            return run.id
        finally:
            session.close()
    except Exception:  # noqa: BLE001 - telemetry must never break ingestion
        logger.warning("Could not open an ingest_runs row for %s", source, exc_info=True)
        return None


def finish_run(
    run_id: int | None, result: IngestResult, *, detail: dict | None = None
) -> None:
    """Close a run as successful, recording what it actually accomplished."""
    if run_id is None:
        return
    _close(
        run_id,
        status=SUCCESS,
        values={
            "events_seen": result.events_seen,
            "events_skipped": result.events_skipped,
            "rows_attempted": result.rows_attempted,
            "rows_written": result.rows_written,
            "detail": detail,
        },
    )


def fail_run(run_id: int | None, exc: BaseException) -> None:
    """Close a run as failed, with a REDACTED error message."""
    if run_id is None:
        return
    _close(
        run_id,
        status=FAILURE,
        values={
            "error_type": type(exc).__name__,
            # redact() is not optional here: this string is persisted.
            "error_message": redact(str(exc))[:2000],
        },
    )


def _close(run_id: int, *, status: str, values: dict) -> None:
    try:
        session = get_session()
        try:
            session.execute(
                update(IngestRun)
                .where(IngestRun.id == run_id)
                .values(status=status, finished_at=datetime.now(timezone.utc), **values)
            )
            session.commit()
        finally:
            session.close()
    except Exception:  # noqa: BLE001
        logger.warning("Could not close ingest_runs row %s", run_id, exc_info=True)


def sweep_abandoned_runs(*, older_than_seconds: int = 86_400) -> int:
    """Flip stranded ``running`` rows to ``abandoned``.

    Called once at scheduler start so a restart does not leave phantom in-flight
    runs that would read as "currently working" forever.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)
    try:
        session = get_session()
        try:
            result = session.execute(
                update(IngestRun)
                .where(IngestRun.status == RUNNING, IngestRun.started_at < cutoff)
                .values(status=ABANDONED, finished_at=datetime.now(timezone.utc))
            )
            session.commit()
            n = result.rowcount or 0
            if n:
                logger.warning(
                    "Marked %d abandoned ingest run(s) — the scheduler died mid-pass.", n
                )
            return n
        finally:
            session.close()
    except Exception:  # noqa: BLE001
        logger.warning("Could not sweep abandoned ingest runs", exc_info=True)
        return 0


def latest_runs(session) -> dict[str, IngestRun]:
    """Most recent run per source, for /health to judge liveness."""
    rows = session.execute(
        select(IngestRun).order_by(IngestRun.source, IngestRun.started_at.desc())
    ).scalars()
    out: dict[str, IngestRun] = {}
    for run in rows:
        out.setdefault(run.source, run)
    return out
