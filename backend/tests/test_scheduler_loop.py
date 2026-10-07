"""The scheduler loop: retries, fail-fast, and resuming the schedule on restart.

The loop previously ran every pass through Prefect, whose in-process API server
failed in production and took every source down with ConnectError for three
weeks while the loop itself stayed up. These tests pin the replacements:

* retries keep Prefect's semantics (retry anything, re-raise the last error);
* the process exits only for failures a restart can fix — no HTTP response —
  and never for an upstream that answered with an error;
* a restart resumes the schedule rather than firing every source at boot, so a
  restart loop cannot spend the Odds API budget.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from arbitrium.config import settings
from arbitrium.ingestion.odds_api import QuotaExhausted
from arbitrium.ingestion.result import IngestResult
from scheduler import flows
from scheduler.flows import _Source, counts_toward_restart, run_cycle, with_retries

UTC = timezone.utc


def _http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://upstream.example/x")
    return httpx.HTTPStatusError(
        f"{status}", request=request, response=httpx.Response(status, request=request)
    )


def _connect_error() -> httpx.ConnectError:
    return httpx.ConnectError("[Errno 111] Connection refused")


@pytest.fixture(autouse=True)
def _no_ingest_runs(monkeypatch):
    """Keep the loop's telemetry writes off the database in these unit tests."""
    monkeypatch.setattr(flows, "start_run", lambda source: None)
    monkeypatch.setattr(flows, "finish_run", lambda run_id, result: None)
    monkeypatch.setattr(flows, "fail_run", lambda run_id, exc: None)


class _Scripted:
    """A pass that raises or returns from a fixed script, one entry per call."""

    def __init__(self, *script):
        self.script = list(script)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        step = self.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step


def _ok() -> IngestResult:
    return IngestResult(source="t", rows_attempted=1, rows_written=1)


# --- with_retries ------------------------------------------------------------


def test_retries_succeeds_first_time_without_sleeping():
    sleeps: list[float] = []
    fn = _Scripted("done")
    assert with_retries(fn, retries=3, delay=30, name="t", sleep=sleeps.append) == "done"
    assert fn.calls == 1 and sleeps == []


def test_retries_recovers_after_transient_failures():
    sleeps: list[float] = []
    fn = _Scripted(_connect_error(), _connect_error(), "done")
    assert with_retries(fn, retries=3, delay=30, name="t", sleep=sleeps.append) == "done"
    assert fn.calls == 3 and sleeps == [30, 30]


def test_retries_give_up_and_raise_the_last_error():
    sleeps: list[float] = []
    last = _connect_error()
    fn = _Scripted(ValueError("first"), ValueError("second"), ValueError("third"), last)
    with pytest.raises(httpx.ConnectError) as caught:
        with_retries(fn, retries=3, delay=30, name="t", sleep=sleeps.append)
    assert caught.value is last
    # 1 attempt + 3 retries, and no sleep after the final failure.
    assert fn.calls == 4 and sleeps == [30, 30, 30]


# --- what counts toward a restart --------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [_connect_error(), httpx.ReadTimeout("timed out"), ValueError("bug"), RuntimeError("x")],
)
def test_no_http_response_counts(exc):
    assert counts_toward_restart(exc) is True


@pytest.mark.parametrize("status", [401, 429, 500, 502, 503])
def test_any_http_status_does_not_count(status):
    assert counts_toward_restart(_http_error(status)) is False


def test_quota_exhausted_does_not_count():
    assert counts_toward_restart(QuotaExhausted("at reserve")) is False


def test_a_wrapped_http_error_is_still_recognised():
    try:
        try:
            raise _http_error(503)
        except httpx.HTTPStatusError as inner:
            raise RuntimeError("pass failed") from inner
    except RuntimeError as outer:
        assert counts_toward_restart(outer) is False


# --- the streak and the exit -------------------------------------------------


def test_streak_counts_no_response_failures_and_resets_on_success():
    source = _Source("kalshi", _Scripted(_connect_error(), _connect_error(), _ok()), 300)
    source.run(0)
    source.run(1)
    assert source.restart_streak == 2
    source.run(2)
    assert source.restart_streak == 0


def test_an_http_response_breaks_the_streak():
    source = _Source("kalshi", _Scripted(_connect_error(), _http_error(429), _connect_error()), 300)
    source.run(0)
    source.run(1)
    assert source.restart_streak == 0
    source.run(2)
    assert source.restart_streak == 1


def test_cycle_exits_non_zero_at_the_threshold_and_not_before(monkeypatch):
    monkeypatch.setattr(settings, "scheduler_exit_after_consecutive_failures", 3)
    source = _Source("kalshi", _Scripted(*[_connect_error()] * 3), 0)
    run_cycle([source], 0)
    run_cycle([source], 1)
    with pytest.raises(SystemExit) as caught:
        run_cycle([source], 2)
    assert caught.value.code == 1


def test_an_upstream_outage_never_exits(monkeypatch):
    monkeypatch.setattr(settings, "scheduler_exit_after_consecutive_failures", 3)
    source = _Source("odds_api", _Scripted(*[_http_error(503)] * 10), 0)
    for tick in range(10):
        run_cycle([source], tick)  # must not raise
    assert source.health.consecutive_failures == 10  # still alerted on
    assert source.restart_streak == 0


def test_cycle_skips_sources_that_are_not_due(monkeypatch):
    monkeypatch.setattr(settings, "scheduler_exit_after_consecutive_failures", 1)
    fn = _Scripted(_connect_error())
    source = _Source("kalshi", fn, 300)
    source.next_run_at = 100
    run_cycle([source], 50)
    assert fn.calls == 0


# --- resuming the schedule after a restart -----------------------------------


NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def test_a_source_that_never_ran_is_due_immediately(monkeypatch):
    monkeypatch.setattr(flows, "last_started_at", lambda name, **_: None)
    source = _Source("odds_api", _ok, 86_400)
    source.resume_schedule(1_000.0, wall_now=NOW)
    assert source.due(1_000.0)


def test_a_recent_run_defers_the_first_pass(monkeypatch):
    # The daily odds pass ran an hour ago: a restart must not run it again now.
    monkeypatch.setattr(flows, "last_started_at", lambda name, **_: NOW - timedelta(hours=1))
    source = _Source("odds_api", _ok, 86_400)
    source.resume_schedule(1_000.0, wall_now=NOW)
    assert source.next_run_at == pytest.approx(1_000.0 + 23 * 3600)
    assert not source.due(1_000.0)


def test_an_overdue_source_runs_immediately(monkeypatch):
    monkeypatch.setattr(flows, "last_started_at", lambda name, **_: NOW - timedelta(minutes=20))
    source = _Source("kalshi", _ok, 300)
    source.resume_schedule(1_000.0, wall_now=NOW)
    assert source.due(1_000.0)


def test_a_naive_timestamp_is_treated_as_utc(monkeypatch):
    naive = (NOW - timedelta(seconds=100)).replace(tzinfo=None)
    monkeypatch.setattr(flows, "last_started_at", lambda name, **_: naive)
    source = _Source("kalshi", _ok, 300)
    source.resume_schedule(1_000.0, wall_now=NOW)
    assert source.next_run_at == pytest.approx(1_200.0)


def _history_down(monkeypatch):
    """Simulate ingest_runs being unreadable: return whatever on_error was given."""
    monkeypatch.setattr(flows, "last_started_at", lambda name, on_error=None: on_error)


def test_unreadable_history_defers_a_paid_source(monkeypatch):
    # The database is down — the likeliest cause of a restart loop. A paid pass
    # must not fire on every restart.
    _history_down(monkeypatch)
    source = _Source("odds_api", _ok, 86_400, paid=True)
    source.resume_schedule(1_000.0, wall_now=NOW)
    assert source.next_run_at == pytest.approx(1_000.0 + 86_400)


def test_unreadable_history_runs_a_free_source_now(monkeypatch):
    _history_down(monkeypatch)
    source = _Source("kalshi", _ok, 300)
    source.resume_schedule(1_000.0, wall_now=NOW)
    assert source.due(1_000.0)


def test_only_the_quota_spending_sources_are_marked_paid():
    paid = {s.name for s in flows.build_sources() if s.paid}
    assert paid == {"odds_api", "resolution"}


# --- the dependency itself ---------------------------------------------------


def test_the_scheduler_does_not_import_prefect():
    import sys

    assert "prefect" not in sys.modules
