"""Prefect flows for scheduled ingestion.

Phase 1 wraps the Kalshi ingest in a Prefect flow and runs it on a fixed polling
interval. Prefect (over raw cron) gives us retries and observability for free.
"""

from __future__ import annotations

import logging
import time

from prefect import flow, task

from marketedge.config import settings
from marketedge.ingestion import kalshi

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)


@task(retries=3, retry_delay_seconds=30)
def ingest_kalshi_task() -> int:
    # retries here cover transient network / API failures only. Non-transient
    # parse failures are skip-and-logged inside run_ingest and never reach here,
    # so a malformed market can no longer burn retries.
    return kalshi.run_ingest()


@flow(name="kalshi-ingest")
def kalshi_ingest_flow() -> int:
    """Single ingest pass over the configured Kalshi sports series."""
    return ingest_kalshi_task()


def run_forever() -> None:
    """Naive polling loop for Phase 1.

    Phase 6 replaces this with a proper Prefect deployment + schedule; for local
    development this keeps the scheduler service alive and polling.
    """
    interval = settings.kalshi_poll_interval_seconds
    logger.info("Starting Kalshi polling loop every %ss", interval)
    while True:
        try:
            kalshi_ingest_flow()
        except Exception:  # noqa: BLE001 - keep the loop alive across transient errors
            logger.exception("Kalshi ingest pass failed; will retry next interval")
        time.sleep(interval)


if __name__ == "__main__":
    run_forever()
