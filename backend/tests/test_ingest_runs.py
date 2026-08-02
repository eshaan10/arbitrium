"""Durable job history.

The property that matters is one the rolled-back ``db_session`` fixture cannot
express: a run row must survive a FAILED ingest, which means it must be written
in its own committed transaction. These tests therefore commit for real and clean
up after themselves — deliberately, and scoped to this one table.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete

from marketedge.db.engine import get_session
from marketedge.db.models import IngestRun
from marketedge.ingestion.result import IngestResult
from marketedge.ingestion.runs import (
    ABANDONED,
    FAILURE,
    RUNNING,
    SUCCESS,
    fail_run,
    finish_run,
    latest_runs,
    start_run,
    sweep_abandoned_runs,
)

UTC = timezone.utc
TEST_SOURCE = "__test_source__"


@pytest.fixture
def committed_runs():
    """Real committed rows, removed afterwards.

    ``db_session`` rolls everything back, which would hide the one guarantee this
    table exists to provide: that a run record outlives a failed pass.
    """
    yield TEST_SOURCE
    session = get_session()
    try:
        session.execute(delete(IngestRun).where(IngestRun.source == TEST_SOURCE))
        session.commit()
    finally:
        session.close()


def _fetch(run_id):
    session = get_session()
    try:
        return session.get(IngestRun, run_id)
    finally:
        session.close()


def test_start_run_commits_immediately(committed_runs):
    """Committed up front, so a later crash still leaves evidence of the attempt."""
    run_id = start_run(TEST_SOURCE)
    assert run_id is not None
    row = _fetch(run_id)
    assert row.status == RUNNING
    assert row.finished_at is None


def test_finish_run_records_truthful_counts(committed_runs):
    run_id = start_run(TEST_SOURCE)
    finish_run(
        run_id,
        IngestResult(
            source=TEST_SOURCE, events_seen=33, events_skipped=2,
            rows_attempted=66, rows_written=14,
        ),
    )
    row = _fetch(run_id)
    assert row.status == SUCCESS
    assert (row.events_seen, row.rows_attempted, row.rows_written) == (33, 66, 14)
    assert row.finished_at is not None


def test_zero_writes_is_recorded_as_success_not_failure(committed_runs):
    """A quiet market is a healthy pass. Conflating it with failure was the bug."""
    run_id = start_run(TEST_SOURCE)
    finish_run(run_id, IngestResult(source=TEST_SOURCE, rows_attempted=66, rows_written=0))
    row = _fetch(run_id)
    assert row.status == SUCCESS
    assert row.rows_written == 0


def test_failure_is_recorded_with_a_redacted_message(committed_runs):
    """A persisted credential is worse than a logged one — rows do not rotate."""
    key = "abcdef0123456789abcdef0123456789"
    run_id = start_run(TEST_SOURCE)
    fail_run(
        run_id,
        RuntimeError(f"failed calling https://api.the-odds-api.com/v4/x?apiKey={key}"),
    )
    row = _fetch(run_id)
    assert row.status == FAILURE
    assert row.error_type == "RuntimeError"
    assert key not in row.error_message
    assert "***REDACTED***" in row.error_message


def test_recorder_never_breaks_ingestion_on_a_bad_id():
    """finish/fail on a None id are no-ops, so a failed start cannot cascade."""
    finish_run(None, IngestResult(source=TEST_SOURCE))
    fail_run(None, RuntimeError("boom"))


def test_sweep_marks_stranded_running_rows(committed_runs):
    """A stranded 'running' row is the signature of a killed worker."""
    session = get_session()
    try:
        stale = IngestRun(
            source=TEST_SOURCE, status=RUNNING,
            started_at=datetime.now(UTC) - timedelta(days=2),
        )
        session.add(stale)
        session.commit()
        stale_id = stale.id
    finally:
        session.close()

    sweep_abandoned_runs(older_than_seconds=3600)
    assert _fetch(stale_id).status == ABANDONED


def test_sweep_leaves_a_fresh_running_row_alone(committed_runs):
    run_id = start_run(TEST_SOURCE)
    sweep_abandoned_runs(older_than_seconds=3600)
    assert _fetch(run_id).status == RUNNING


def test_latest_runs_returns_the_newest_per_source(committed_runs):
    first = start_run(TEST_SOURCE)
    finish_run(first, IngestResult(source=TEST_SOURCE, rows_written=1))
    second = start_run(TEST_SOURCE)
    finish_run(second, IngestResult(source=TEST_SOURCE, rows_written=2))

    session = get_session()
    try:
        newest = latest_runs(session)[TEST_SOURCE]
    finally:
        session.close()
    assert newest.id == second
    assert newest.rows_written == 2
