"""/health ingestion freshness (Layer 3).

Derived from the append-only table rather than in-process counters, so it still
reports a growing age when the poller is dead or crash-looping — the failure mode
that made the original outage invisible.

The policy tests are pure: staleness must be judged against injected timestamps,
not against whatever the live poller has written to the shared table.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from marketedge.api.main import _ingestion_freshness, staleness_report
from marketedge.config import settings
from marketedge.db.models import Event, OddsSnapshot

UTC = timezone.utc
NOW = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
KALSHI_THRESHOLD = (
    settings.kalshi_poll_interval_seconds * settings.ingest_staleness_interval_multiple
)


def test_recent_write_is_not_stale():
    out = staleness_report({"kalshi": NOW - timedelta(seconds=30)}, now=NOW)
    assert out["kalshi"]["stale"] is False
    assert out["kalshi"]["age_seconds"] == 30


def test_dead_poller_is_flagged_stale():
    """Rows exist, but the newest is far older than the interval allows."""
    out = staleness_report(
        {"kalshi": NOW - timedelta(seconds=KALSHI_THRESHOLD + 600)}, now=NOW
    )
    assert out["kalshi"]["stale"] is True
    assert out["kalshi"]["age_seconds"] > KALSHI_THRESHOLD


def test_threshold_is_a_boundary_not_a_range():
    just_inside = staleness_report({"kalshi": NOW - timedelta(seconds=KALSHI_THRESHOLD)}, now=NOW)
    just_outside = staleness_report(
        {"kalshi": NOW - timedelta(seconds=KALSHI_THRESHOLD + 1)}, now=NOW
    )
    assert just_inside["kalshi"]["stale"] is False
    assert just_outside["kalshi"]["stale"] is True


def test_source_that_never_wrote_is_stale_not_absent():
    out = staleness_report({}, now=NOW)
    assert out["consensus"]["last_write_at"] is None
    assert out["consensus"]["age_seconds"] is None
    assert out["consensus"]["stale"] is True


def test_each_source_uses_its_own_interval():
    """The Odds API polls less often, so the same gap must not flag both."""
    out = staleness_report({}, now=NOW)
    assert set(out) == {"kalshi", "consensus"}
    assert (
        out["consensus"]["stale_after_seconds"] > out["kalshi"]["stale_after_seconds"]
    ), "a slower poll interval must tolerate a longer gap"


def test_the_outage_pattern_is_visible():
    """A week of failed polls: last write ages without bound, stale stays true."""
    for days in (1, 3, 7):
        out = staleness_report({"kalshi": NOW - timedelta(days=days)}, now=NOW)
        assert out["kalshi"]["stale"] is True
        assert out["kalshi"]["age_seconds"] == days * 86400


# --- DB wiring (the query, not the policy) ----------------------------------


def test_freshness_reads_real_snapshots(db_session):
    ev = Event(
        sport="nfl", league="NFL", home_team="Seattle Seahawks",
        away_team="Los Angeles Rams",
        scheduled_start=datetime.now(UTC) + timedelta(days=460),
        status="scheduled",
    )
    db_session.add(ev)
    db_session.flush()
    db_session.add(OddsSnapshot(
        event_id=ev.id, source="kalshi", outcome="home", team="Seattle Seahawks",
        implied_probability=0.61, price_format="probability",
        ingested_at=datetime.now(UTC), snapshot_time=datetime.now(UTC),
    ))
    db_session.flush()

    out = _ingestion_freshness(db_session)
    assert set(out) == {"kalshi", "consensus"}
    assert out["kalshi"]["last_write_at"] is not None
    assert out["kalshi"]["age_seconds"] < 300
