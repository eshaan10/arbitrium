"""Prefect flows for scheduled ingestion.

Two sources on independent intervals: Kalshi (fast — a live order book) and The
Odds API (slower, and every call costs quota). Poll ORDER is irrelevant: both
ingestion paths run the shared matcher before inserting, so whichever source
reaches a game first creates the ``events`` row and the other merges into it.

Each pass reports what it actually WROTE, not what it attempted, and feeds an
:class:`~scheduler.health.IngestHealth` tracker that escalates on consecutive
failures or prolonged silence. Before that existed, a broken ingest looked
exactly like a healthy quiet one for a week.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from prefect import flow, task

from marketedge.calibration import grading
from marketedge.config import settings
from marketedge.db.engine import get_session
from marketedge.ingestion import kalshi, odds_api, resolution
from marketedge.ingestion.polling import odds_poll_interval
from marketedge.ingestion.result import IngestResult
from marketedge.ingestion.runs import fail_run, finish_run, start_run, sweep_abandoned_runs
from marketedge.logging_config import configure_logging
from scheduler.health import IngestHealth

configure_logging()
logger = logging.getLogger(__name__)


def _odds_interval() -> int:
    """Current adaptive Odds API interval, read from the schedule we already hold."""
    session = get_session()
    try:
        return odds_poll_interval(session)
    finally:
        session.close()


@task(retries=3, retry_delay_seconds=30)
def ingest_kalshi_task() -> IngestResult:
    # retries here cover transient network / API failures only. Non-transient
    # parse failures are skip-and-logged inside run_ingest and never reach here,
    # so a malformed market can no longer burn retries.
    return kalshi.run_ingest()


@task(retries=3, retry_delay_seconds=30)
def ingest_odds_task() -> IngestResult:
    return odds_api.run_ingest()


@task(retries=1, retry_delay_seconds=60)
def resolve_outcomes_task() -> IngestResult:
    # Only ONE retry, unlike the ingest tasks. Each scores call costs 2 credits,
    # and a game gets ~14 resolution chances inside its window anyway, so extra
    # retries buy almost nothing and spend a budget that outcome collection
    # cannot afford to run out of.
    result, _detail = resolution.run_resolution()
    return result


@flow(name="kalshi-ingest")
def kalshi_ingest_flow() -> IngestResult:
    """Single ingest pass over the configured Kalshi sports series."""
    return ingest_kalshi_task()


@flow(name="odds-api-ingest")
def odds_ingest_flow() -> IngestResult:
    """Single ingest pass over the configured Odds API sports."""
    return ingest_odds_task()


@task(retries=1, retry_delay_seconds=60)
def calibration_task() -> IngestResult:
    # Purely database-side: records the recommendations currently standing and
    # grades whatever has resolved. No external API, so no quota and no retries
    # worth spending.
    counts = grading.run_calibration()
    return IngestResult(
        source="calibration",
        rows_attempted=counts["live_recorded"] + counts["graded"],
        rows_written=counts["live_recorded"] + counts["graded"],
    )


@flow(name="calibration")
def calibration_flow() -> IngestResult:
    """Record live recommendations, then grade resolved ones."""
    return calibration_task()


@flow(name="outcome-resolution")
def resolution_flow() -> IngestResult:
    """Single resolution pass. Costs nothing when nothing awaits a result."""
    return resolve_outcomes_task()


class _Source:
    """One polled source: its flow, its pacing, and its health tracker."""

    def __init__(
        self,
        name: str,
        flow_fn,
        interval: int | Callable[[], int],
        *,
        health: IngestHealth | None = None,
    ) -> None:
        self.name = name
        self.flow_fn = flow_fn
        # A callable lets a source re-pace itself between passes — the Odds API
        # polls hourly near kickoff and daily when the next game is weeks away,
        # which is what keeps it inside the monthly credit budget.
        self._interval = interval
        self.health = health or IngestHealth(name)
        self.next_run_at = 0.0

    @property
    def interval(self) -> int:
        try:
            return self._interval() if callable(self._interval) else self._interval
        except Exception:  # noqa: BLE001 - pacing must never kill the loop
            logger.warning("%s: interval lookup failed; using the far tier", self.name)
            return settings.odds_poll_far_seconds

    def due(self, now: float) -> bool:
        return now >= self.next_run_at

    def run(self, now: float) -> None:
        # Recorded in ingest_runs BEFORE the pass, in its own committed
        # transaction: if it shared the ingest transaction, a failed pass would
        # roll back the very evidence that it failed.
        run_id = start_run(self.name)
        try:
            result = self.flow_fn()
            self.health.record_success(result)
            finish_run(run_id, result)
        except Exception as exc:  # noqa: BLE001 - keep the loop alive
            # Logged by the tracker (with escalation); the traceback still goes
            # out at debug level for diagnosis.
            self.health.record_failure(exc)
            fail_run(run_id, exc)
            logger.debug("%s ingest traceback", self.name, exc_info=True)
        finally:
            self.next_run_at = now + self.interval


def run_forever() -> None:
    """Naive multi-source polling loop for Phases 1-2.

    Phase 6 replaces this with proper Prefect deployments + schedules; for local
    development this keeps the scheduler service alive and polling. Sources are
    checked on a short tick and each runs on its own interval, so a slow Odds API
    pass never delays a Kalshi one.
    """
    # A restart leaves 'running' rows stranded; without this they read as
    # "currently working" forever and mask a crash loop.
    sweep_abandoned_runs()

    sources = [
        _Source("kalshi", kalshi_ingest_flow, settings.kalshi_poll_interval_seconds),
        # Adaptive: hourly near kickoff, daily when the next game is weeks out.
        # A flat 15-minute interval burned the entire monthly credit budget in
        # five days; this spends it where prices actually move.
        _Source("odds_api", odds_ingest_flow, _odds_interval),
        _Source(
            "calibration",
            calibration_flow,
            settings.calibration_poll_interval_seconds,
            # Like resolution, this legitimately writes nothing for long stretches
            # (no new recommendations, nothing newly resolved), so the generic
            # zero-write alarm is the wrong signal.
            health=IngestHealth(
                "calibration",
                zero_write_warn_seconds=settings.resolution_zero_write_warn_seconds,
                zero_write_error_seconds=settings.resolution_zero_write_error_seconds,
            ),
        ),
        _Source(
            "resolution",
            resolution_flow,
            settings.resolution_poll_interval_seconds,
            # Resolution legitimately writes nothing for months in the off-season,
            # so the generic zero-write alarm is the WRONG signal — it would
            # scream all summer and stay silent during the week it matters. The
            # real alarm is `hours_until_next_data_loss` in /health.
            health=IngestHealth(
                "resolution",
                zero_write_warn_seconds=settings.resolution_zero_write_warn_seconds,
                zero_write_error_seconds=settings.resolution_zero_write_error_seconds,
            ),
        ),
    ]
    logger.info(
        "Starting ingest loop: %s",
        ", ".join(f"{s.name} every {s.interval}s" for s in sources),
    )
    while True:
        now = time.monotonic()
        for source in sources:
            if source.due(now):
                source.run(now)
        time.sleep(5)


if __name__ == "__main__":
    run_forever()
