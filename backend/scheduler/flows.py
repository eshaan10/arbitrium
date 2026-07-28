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

from prefect import flow, task

from marketedge.config import settings
from marketedge.ingestion import kalshi, odds_api
from marketedge.ingestion.result import IngestResult
from marketedge.logging_config import configure_logging
from scheduler.health import IngestHealth

configure_logging()
logger = logging.getLogger(__name__)


@task(retries=3, retry_delay_seconds=30)
def ingest_kalshi_task() -> IngestResult:
    # retries here cover transient network / API failures only. Non-transient
    # parse failures are skip-and-logged inside run_ingest and never reach here,
    # so a malformed market can no longer burn retries.
    return kalshi.run_ingest()


@task(retries=3, retry_delay_seconds=30)
def ingest_odds_task() -> IngestResult:
    return odds_api.run_ingest()


@flow(name="kalshi-ingest")
def kalshi_ingest_flow() -> IngestResult:
    """Single ingest pass over the configured Kalshi sports series."""
    return ingest_kalshi_task()


@flow(name="odds-api-ingest")
def odds_ingest_flow() -> IngestResult:
    """Single ingest pass over the configured Odds API sports."""
    return ingest_odds_task()


class _Source:
    """One polled source: its flow, its interval, and its health tracker."""

    def __init__(self, name: str, flow_fn, interval: int) -> None:
        self.name = name
        self.flow_fn = flow_fn
        self.interval = interval
        self.health = IngestHealth(name)
        self.next_run_at = 0.0

    def due(self, now: float) -> bool:
        return now >= self.next_run_at

    def run(self, now: float) -> None:
        try:
            result = self.flow_fn()
            self.health.record_success(result)
        except Exception as exc:  # noqa: BLE001 - keep the loop alive
            # Logged by the tracker (with escalation); the traceback still goes
            # out at debug level for diagnosis.
            self.health.record_failure(exc)
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
    sources = [
        _Source("kalshi", kalshi_ingest_flow, settings.kalshi_poll_interval_seconds),
        _Source("odds_api", odds_ingest_flow, settings.odds_poll_interval_seconds),
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
