"""Scheduled ingestion: one plain polling loop, no orchestration framework.

Kalshi runs on a flat interval (fast, free — a live order book). The Odds API
does not run on an interval at all: it runs when the game-clock plan has a pass
due (see ingestion.polling and ingestion.governor), because every call costs
credits from a 500-a-month budget. Poll ORDER is irrelevant: both
ingestion paths run the shared matcher before inserting, so whichever source
reaches a game first creates the ``events`` row and the other merges into it.

Each pass reports what it actually WROTE, not what it attempted, and feeds an
:class:`~scheduler.health.IngestHealth` tracker that escalates on consecutive
failures or prolonged silence. Before that existed, a broken ingest looked
exactly like a healthy quiet one for a week.

WHY THERE IS NO PREFECT HERE. Every pass used to be wrapped in a Prefect
``@flow``/``@task``. With no Prefect server configured, Prefect 3 spawns a local
API server inside this process and routes every call through it over loopback
HTTP — 231 MB for that server plus ~110 MB of imports, measured, on a 512 MB
machine. In production it stopped coming back after 35 hours, and every pass of
every source failed with ``ConnectError: [Errno 111]`` for three weeks, including
calibration, which never touches the network at all. What Prefect actually
provided was retries, which are ``with_retries`` below, and run tracking, which
``ingest_runs`` already does durably and Prefect's throwaway SQLite did not.

FAIL FAST. The loop survives any single failure, but not a sustained one: after
``scheduler_exit_after_consecutive_failures`` passes of one source fail with no
HTTP response from upstream, the process exits non-zero so the platform restarts
it. A process that cannot reach anything is the one state a restart can fix; an
upstream that answers with an error is not, so those never count.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TypeVar

import httpx

from arbitrium.calibration import grading
from arbitrium.config import settings
from arbitrium.ingestion import kalshi, live_scores, odds_schedule, resolution
from arbitrium.ingestion.espn import ESPN_SPORTS
from arbitrium.ingestion.odds_api import QuotaExhausted
from arbitrium.ingestion.result import IngestResult
from arbitrium.ingestion.runs import (
    fail_run,
    finish_run,
    last_started_at,
    start_run,
    sweep_abandoned_runs,
)
from arbitrium.logging_config import UNHEALTHY_MARKER, configure_logging
from scheduler.health import IngestHealth

configure_logging()
logger = logging.getLogger(__name__)

T = TypeVar("T")

# Returned by last_started_at when ingest_runs cannot be read, as distinct from
# None ("this source has never run").
_HISTORY_UNAVAILABLE = object()


def with_retries(
    fn: Callable[[], T],
    *,
    retries: int,
    delay: int,
    name: str,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call ``fn``, retrying up to ``retries`` times ``delay`` seconds apart.

    The direct replacement for Prefect's task retries, with the same semantics:
    any exception is retried, and the last one propagates once retries run out.
    Blocking on purpose — the loop is serial, exactly as it was under Prefect.
    """
    for attempt in range(1, retries + 2):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - retry anything, re-raise the last
            if attempt > retries:
                raise
            logger.warning(
                "%s attempt %d/%d failed: %s: %s; retrying in %ds",
                name, attempt, retries + 1, type(exc).__name__, exc, delay,
            )
            sleep(delay)
    raise AssertionError("unreachable")  # pragma: no cover


def kalshi_pass() -> IngestResult:
    # Retries cover transient network / API failures only. Non-transient parse
    # failures are skip-and-logged inside run_ingest and never reach here, so a
    # malformed market cannot burn retries.
    return with_retries(kalshi.run_ingest, retries=3, delay=30, name="kalshi")


def odds_pass() -> IngestResult:
    # One retry, not three. The pass re-plans on every attempt, so a checkpoint
    # recorded before the failure is never re-bought — but a failure AFTER a
    # paid response and BEFORE its checkpoint row is written would be, and every
    # retry is a credit.
    return with_retries(odds_schedule.run_due_passes, retries=1, delay=30, name="odds_api")


def calibration_pass() -> IngestResult:
    # Purely database-side: records the recommendations currently standing and
    # grades whatever has resolved. No external API, so one retry is plenty.
    counts = with_retries(grading.run_calibration, retries=1, delay=60, name="calibration")
    return IngestResult(
        source="calibration",
        rows_attempted=counts["live_recorded"] + counts["graded"],
        rows_written=counts["live_recorded"] + counts["graded"],
    )


def resolution_pass() -> IngestResult:
    # Only ONE retry, unlike the ingest passes. Each scores call costs 2 credits,
    # and a game gets ~14 resolution chances inside its window anyway, so extra
    # retries buy almost nothing and spend a budget that outcome collection
    # cannot afford to run out of.
    result, _detail = with_retries(
        resolution.run_resolution, retries=1, delay=60, name="resolution"
    )
    return result


def counts_toward_restart(exc: BaseException) -> bool:
    """True when the failure got no HTTP response from upstream.

    A restart can fix a process that cannot reach anything — this module's own
    outage was exactly that. It cannot fix an upstream that answered with an
    error, so any HTTP status (5xx, 401, 429 alike) is excluded. ``QuotaExhausted``
    is excluded too: it is raised before a request, but on the strength of the
    quota header from an earlier response, and restarting would only re-spend
    the budget it exists to protect. Walks the cause chain, so wrapping an HTTP
    error does not disguise it.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (httpx.HTTPStatusError, QuotaExhausted)):
            return False
        current = current.__cause__ or current.__context__
    return True


class _Source:
    """One polled source: its pass, its pacing, and its health tracker."""

    def __init__(
        self,
        name: str,
        pass_fn: Callable[[], IngestResult],
        interval: int | Callable[[], int],
        *,
        health: IngestHealth | None = None,
        paid: bool = False,
    ) -> None:
        self.name = name
        self.pass_fn = pass_fn
        # Paid sources spend Odds API credits on every pass, so when the schedule
        # cannot be recovered they wait an interval rather than run blind.
        self.paid = paid
        # A callable lets a source re-pace itself between passes — the Odds API
        # polls hourly near kickoff and daily when the next game is weeks away,
        # which is what keeps it inside the monthly credit budget.
        self._interval = interval
        self.health = health or IngestHealth(name)
        self.next_run_at = 0.0
        # Consecutive failures that a restart could plausibly fix. Separate from
        # health.consecutive_failures, which counts every failure for alerting.
        self.restart_streak = 0

    @property
    def interval(self) -> int:
        try:
            return self._interval() if callable(self._interval) else self._interval
        except Exception:  # noqa: BLE001 - pacing must never kill the loop
            logger.warning("%s: interval lookup failed; using the replan interval", self.name)
            return settings.odds_replan_seconds

    def resume_schedule(self, now: float, *, wall_now: datetime | None = None) -> None:
        """Pick up the schedule where the last process left it.

        Without this every source runs the moment the process boots, so each
        restart is an extra Odds API pass — and with fail-fast and an `always`
        restart policy, a restart loop would turn the daily odds pass into one
        per restart and burn the monthly budget. Any status counts as "last run":
        a failed pass still spent its slot.

        When the history cannot be read at all — the database is down, which is
        precisely when a restart loop is likeliest — free sources run now and
        paid sources wait a full interval. A paid pass could not store its
        result without the database anyway, so waiting costs nothing, and the
        budget no longer depends on each pass happening to query the database
        before its first paid call.
        """
        last = last_started_at(self.name, on_error=_HISTORY_UNAVAILABLE)
        if last is _HISTORY_UNAVAILABLE:
            if self.paid:
                self.next_run_at = now + self.interval
            return
        if last is None:
            return  # never ran: due immediately
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        elapsed = ((wall_now or datetime.now(timezone.utc)) - last).total_seconds()
        self.next_run_at = now + max(0.0, self.interval - elapsed)

    def due(self, now: float) -> bool:
        return now >= self.next_run_at

    def run(self, now: float) -> None:
        # Recorded in ingest_runs BEFORE the pass, in its own committed
        # transaction: if it shared the ingest transaction, a failed pass would
        # roll back the very evidence that it failed.
        run_id = start_run(self.name)
        try:
            result = self.pass_fn()
            self.health.record_success(result)
            finish_run(run_id, result)
            self.restart_streak = 0
        except Exception as exc:  # noqa: BLE001 - keep the loop alive
            # Logged by the tracker (with escalation); the traceback still goes
            # out at debug level for diagnosis.
            self.health.record_failure(exc)
            fail_run(run_id, exc)
            logger.debug("%s ingest traceback", self.name, exc_info=True)
            # An HTTP response proves the path to upstream works, so it breaks
            # the streak rather than merely not adding to it.
            self.restart_streak = self.restart_streak + 1 if counts_toward_restart(exc) else 0
        finally:
            self.next_run_at = now + self.interval


class _PlannedSource(_Source):
    """A paid source that runs only when the game-clock plan has a pass due.

    Between passes it re-reads the plan every ``replan`` seconds — the database
    plus the free /events listing — so a newly listed game or an opening Kalshi
    gate is noticed without a paid call, and without an ingest_runs row per
    check. A restart cannot re-spend: the plan is rebuilt from odds_checkpoints,
    which records every checkpoint already captured or skipped.
    """

    def __init__(
        self,
        name: str,
        pass_fn: Callable[[], IngestResult],
        plan_fn: Callable[[], float | None],
        *,
        replan: int,
        health: IngestHealth | None = None,
    ) -> None:
        super().__init__(name, pass_fn, replan, health=health, paid=True)
        self._plan_fn = plan_fn
        self._replan_at = 0.0
        self.next_run_at = float("inf")

    def _replan(self, now: float) -> None:
        self._replan_at = now + self.interval
        try:
            wait = self._plan_fn()
        except Exception as exc:  # noqa: BLE001 - planning must never kill the loop
            # Paid: when the plan cannot be read, do not run blind.
            logger.warning("%s: planning failed (%s: %s); retrying in %ds",
                           self.name, type(exc).__name__, exc, self.interval)
            wait = None
        self.next_run_at = float("inf") if wait is None else now + wait

    def resume_schedule(self, now: float, *, wall_now: datetime | None = None) -> None:
        self._replan_at = now  # the durable plan IS the schedule; read it on the first tick

    def due(self, now: float) -> bool:
        if now >= self._replan_at:
            self._replan(now)
        return now >= self.next_run_at

    def run(self, now: float) -> None:
        failures = self.health.consecutive_failures
        super().run(now)
        self._replan(now)
        if self.health.consecutive_failures > failures:
            # A failed pass leaves its checkpoints unrecorded, so the plan still
            # says "due now". Without this it would re-run — and re-spend — on
            # the next five-second tick.
            self.next_run_at = max(self.next_run_at, now + self.interval)


def run_cycle(sources: list[_Source], now: float) -> None:
    """Run every due source once; exit the process if one cannot recover alone.

    Raises SystemExit(1) rather than calling sys.exit deep in a pass, so the
    in-flight pass has already closed its ingest_runs row before the process
    goes — the evidence of why it exited is never the thing that gets lost.
    """
    limit = settings.scheduler_exit_after_consecutive_failures
    for source in sources:
        if not source.due(now):
            continue
        source.run(now)
        if source.restart_streak >= limit:
            logger.critical(
                "%s: %s failed %d consecutive times with no response from upstream. "
                "Exiting non-zero so the platform restarts the scheduler; this loop "
                "will not recover on its own.",
                UNHEALTHY_MARKER, source.name, source.restart_streak,
            )
            raise SystemExit(1)


def _live_scores_sources() -> list[_Source]:
    """One live-scoreboard source per enabled sport. Free (ESPN), DB-gated.

    Interval is dynamic: 30s when a game is in its live window, 15m while
    there are scheduled games today, 1h otherwise. The pass_fn re-checks the
    DB so the "no HTTP call" guarantee survives even if the interval closure
    is wrong by a tick.
    """
    return [
        _Source(
            f"live_scores_{sport}",
            live_scores.pass_fn_for(sport),
            live_scores.interval_fn_for(sport),
        )
        for sport in ESPN_SPORTS
    ]


def build_sources() -> list[_Source]:
    return [
        _Source("kalshi", kalshi_pass, settings.kalshi_poll_interval_seconds),
        # Game-clock: T-24h, T-6h, T-1h and the close, only for Kalshi-backed
        # games, coalesced across a sport and rationed by the credit governor.
        # A flat 15-minute interval once burned the monthly budget in five days.
        _PlannedSource(
            "odds_api",
            odds_pass,
            odds_schedule.seconds_until_next_pass,
            replan=settings.odds_replan_seconds,
            health=IngestHealth(
                "odds_api",
                zero_write_warn_seconds=settings.odds_zero_write_warn_seconds,
                zero_write_error_seconds=settings.odds_zero_write_error_seconds,
            ),
        ),
        _Source(
            "calibration",
            calibration_pass,
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
            resolution_pass,
            settings.resolution_poll_interval_seconds,
            # ESPN-primary and free, but its fallback is a 2-credit scores call.
            # Waiting one 6h interval is safe: ~14 chances inside the window.
            paid=True,
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
        *_live_scores_sources(),
    ]


def run_forever() -> None:
    """Multi-source polling loop.

    Sources are checked on a short tick and each runs on its own interval, so a
    slow Odds API pass never delays a Kalshi one.
    """
    # A restart leaves 'running' rows stranded; without this they read as
    # "currently working" forever and mask a crash loop.
    sweep_abandoned_runs()

    sources = build_sources()
    start = time.monotonic()
    for source in sources:
        source.resume_schedule(start)
    logger.info(
        "Starting ingest loop: %s (exits after %d consecutive no-response failures)",
        ", ".join(
            f"{s.name} on the game-clock plan (replans every {s.interval}s)"
            if isinstance(s, _PlannedSource)
            else f"{s.name} every {s.interval}s, first in {max(0, round(s.next_run_at - start))}s"
            for s in sources
        ),
        settings.scheduler_exit_after_consecutive_failures,
    )
    while True:
        run_cycle(sources, time.monotonic())
        time.sleep(5)


if __name__ == "__main__":
    run_forever()
