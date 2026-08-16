"""In-process health tracking for the polling loop.

Layer 2 of the ingest failure visibility added after a dedup-trigger bug caused
896 consecutive silent poll failures. Two distinct signals, deliberately weighted
differently:

* **Consecutive failures** — a pass that raises is unambiguously broken. Three in
  a row escalates to ERROR. This is the strong signal, and the one that would
  have caught the outage within ~15 minutes.
* **Continuous zero-write time** — much weaker, because the dedup trigger makes
  zero writes the CORRECT behaviour for a quiet market. Overnight in the
  off-season a healthy poller legitimately writes nothing for hours, so this is
  measured in hours of silence, not runs, and warns long before it errors.

Every escalated line carries the literal marker ``INGEST_UNHEALTHY`` so it can be
grepped or alerted on without parsing prose.

This state lives in the process and resets on restart — which is exactly why it
is not the only layer. ``/health`` derives staleness from the database instead
(see arbitrium.api.main), so a crash-looping poller still surfaces.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from arbitrium.config import settings
from arbitrium.ingestion.result import IngestResult
from arbitrium.logging_config import UNHEALTHY_MARKER

logger = logging.getLogger(__name__)

# Re-exported from arbitrium.logging_config so both layers share one marker
# without scheduler.* becoming a dependency of arbitrium.*.
__all__ = ["IngestHealth", "UNHEALTHY_MARKER"]


class IngestHealth:
    """Tracks consecutive failures and quiet time for one ingest source."""

    def __init__(
        self,
        source: str,
        *,
        max_consecutive_failures: int | None = None,
        zero_write_warn_seconds: int | None = None,
        zero_write_error_seconds: int | None = None,
    ) -> None:
        self.source = source
        self.max_consecutive_failures = (
            max_consecutive_failures
            if max_consecutive_failures is not None
            else settings.ingest_max_consecutive_failures
        )
        self.warn_after = timedelta(
            seconds=zero_write_warn_seconds
            if zero_write_warn_seconds is not None
            else settings.ingest_zero_write_warn_seconds
        )
        self.error_after = timedelta(
            seconds=zero_write_error_seconds
            if zero_write_error_seconds is not None
            else settings.ingest_zero_write_error_seconds
        )
        self.consecutive_failures = 0
        self.last_write_at: datetime | None = None
        self._quiet_since: datetime | None = None

    @staticmethod
    def _now(now: datetime | None) -> datetime:
        return now if now is not None else datetime.now(timezone.utc)

    def record_failure(self, exc: BaseException, *, now: datetime | None = None) -> None:
        """Record a pass that raised. Escalates once the streak crosses the floor."""
        self._now(now)
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.max_consecutive_failures:
            logger.error(
                "%s: %s ingest has failed %d consecutive times; no data is being "
                "recorded. Latest error: %s: %s",
                UNHEALTHY_MARKER, self.source, self.consecutive_failures,
                type(exc).__name__, exc,
            )
        else:
            logger.warning(
                "%s ingest pass failed (%d/%d before escalation): %s: %s",
                self.source, self.consecutive_failures, self.max_consecutive_failures,
                type(exc).__name__, exc,
            )

    def record_success(self, result: IngestResult, *, now: datetime | None = None) -> None:
        """Record a pass that completed, escalating on prolonged silence."""
        moment = self._now(now)
        self.consecutive_failures = 0

        if result.rows_written > 0:
            self.last_write_at = moment
            self._quiet_since = None
            return

        # Nothing written. Legitimate when prices haven't moved — only the
        # DURATION of the silence makes it suspicious.
        if self._quiet_since is None:
            self._quiet_since = moment
            return

        quiet_for = moment - self._quiet_since
        if quiet_for >= self.error_after:
            logger.error(
                "%s: %s has written no rows for %s (threshold %s). Either the "
                "market is dormant or ingestion is silently broken — check "
                "/health for database-side staleness.",
                UNHEALTHY_MARKER, self.source, _fmt(quiet_for), _fmt(self.error_after),
            )
        elif quiet_for >= self.warn_after:
            logger.warning(
                "%s has written no rows for %s; expected for a quiet market, "
                "suspicious otherwise.",
                self.source, _fmt(quiet_for),
            )


def _fmt(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    hours, rem = divmod(total, 3600)
    minutes = rem // 60
    return f"{hours}h{minutes:02d}m" if hours else f"{minutes}m"
