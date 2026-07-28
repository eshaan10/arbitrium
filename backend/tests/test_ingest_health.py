"""Ingest failure visibility: the three layers added after the silent outage.

Layer 1 (rows written, not attempted) is what makes the other two possible, so
the first test pins the distinction the old code could not express.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from marketedge.ingestion.result import IngestResult
from scheduler.health import UNHEALTHY_MARKER, IngestHealth

UTC = timezone.utc
T0 = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)


def _result(written, attempted=66):
    return IngestResult(
        source="kalshi", events_seen=33, rows_attempted=attempted, rows_written=written
    )


# --- Layer 1: attempted != written ------------------------------------------


def test_result_separates_written_from_suppressed():
    r = _result(written=14, attempted=66)
    assert r.rows_written == 14
    assert r.rows_suppressed == 52  # dedup working, not an error


def test_fully_suppressed_pass_is_distinguishable_from_a_broken_one():
    """The distinction the old `return total` could not express."""
    healthy_quiet = _result(written=0, attempted=66)
    broken = _result(written=0, attempted=0)
    assert healthy_quiet.rows_attempted != broken.rows_attempted
    assert healthy_quiet.rows_written == broken.rows_written == 0


# --- Layer 2: consecutive failures (the strong signal) ----------------------


def _tracker(**kw):
    kw.setdefault("max_consecutive_failures", 3)
    kw.setdefault("zero_write_warn_seconds", 3600)
    kw.setdefault("zero_write_error_seconds", 21600)
    return IngestHealth("kalshi", **kw)


def test_failures_escalate_to_error_at_the_threshold(caplog):
    h = _tracker()
    exc = RuntimeError("FlushError: did not produce the correct number of INSERTed rows")

    with caplog.at_level(logging.WARNING):
        h.record_failure(exc, now=T0)
        h.record_failure(exc, now=T0 + timedelta(minutes=5))
    assert UNHEALTHY_MARKER not in caplog.text  # below threshold: warn only
    assert h.consecutive_failures == 2

    caplog.clear()
    with caplog.at_level(logging.WARNING):
        h.record_failure(exc, now=T0 + timedelta(minutes=10))
    assert UNHEALTHY_MARKER in caplog.text
    assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_a_success_resets_the_failure_streak(caplog):
    h = _tracker()
    h.record_failure(RuntimeError("boom"), now=T0)
    h.record_failure(RuntimeError("boom"), now=T0 + timedelta(minutes=5))
    h.record_success(_result(written=10), now=T0 + timedelta(minutes=10))
    assert h.consecutive_failures == 0

    caplog.clear()
    with caplog.at_level(logging.WARNING):
        h.record_failure(RuntimeError("boom"), now=T0 + timedelta(minutes=15))
    assert UNHEALTHY_MARKER not in caplog.text  # streak restarted, not resumed


def test_the_real_outage_would_have_escalated(caplog):
    """896 consecutive FlushErrors: escalates on the 3rd, ~15 min in."""
    h = _tracker()
    with caplog.at_level(logging.ERROR):
        for i in range(10):
            h.record_failure(RuntimeError("FlushError"), now=T0 + timedelta(minutes=5 * i))
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 8  # runs 3..10
    assert UNHEALTHY_MARKER in errors[0].getMessage()
    assert "3 consecutive times" in errors[0].getMessage()


# --- Layer 2: quiet time (the weak signal, deliberately generous) -----------


def test_zero_writes_alone_is_not_an_alarm(caplog):
    """A quiet market writing nothing is CORRECT behaviour, not a failure."""
    h = _tracker()
    with caplog.at_level(logging.WARNING):
        h.record_success(_result(written=0), now=T0)
        h.record_success(_result(written=0), now=T0 + timedelta(minutes=5))
        h.record_success(_result(written=0), now=T0 + timedelta(minutes=30))
    assert caplog.text == ""


def test_prolonged_silence_warns_then_errors(caplog):
    h = _tracker()
    h.record_success(_result(written=0), now=T0)  # quiet starts

    with caplog.at_level(logging.WARNING):
        h.record_success(_result(written=0), now=T0 + timedelta(hours=1, minutes=1))
    assert any(r.levelno == logging.WARNING for r in caplog.records)
    assert UNHEALTHY_MARKER not in caplog.text  # warning stays un-escalated

    caplog.clear()
    with caplog.at_level(logging.WARNING):
        h.record_success(_result(written=0), now=T0 + timedelta(hours=6, minutes=1))
    assert any(r.levelno == logging.ERROR for r in caplog.records)
    assert UNHEALTHY_MARKER in caplog.text


def test_a_single_write_clears_the_quiet_clock(caplog):
    h = _tracker()
    h.record_success(_result(written=0), now=T0)
    h.record_success(_result(written=3), now=T0 + timedelta(hours=5))
    assert h.last_write_at == T0 + timedelta(hours=5)

    with caplog.at_level(logging.WARNING):
        # 2h after the write — well past the old quiet start, but the clock reset.
        h.record_success(_result(written=0), now=T0 + timedelta(hours=7))
    assert caplog.text == ""
