"""/health ingestion freshness (Layer 3).

Derived from the append-only table rather than in-process counters, so it still
reports a growing age when the poller is dead or crash-looping — the failure mode
that made the original outage invisible.

The policy tests are pure: staleness must be judged against injected timestamps,
not against whatever the live poller has written to the shared table.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from arbitrium.api.main import _ingestion_freshness, staleness_report
from arbitrium.config import settings
from arbitrium.db.models import Event, OddsSnapshot

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


# --- the adaptive-interval / staleness-window mismatch -----------------------


def test_consensus_staleness_tracks_the_adaptive_interval():
    """The window must follow the schedule actually in force, not the flat setting.

    Found live: with the next kickoff 2 days out the Odds API poller was
    correctly on the mid tier (21600s, 4x/day), but /health judged it against
    ``odds_poll_interval_seconds`` (900s) and reported a 14.6-hour-old write as
    stale. The poller was healthy; the monitor was miscalibrated by 24x, and
    /health had been reporting "degraded" for most of every week.

    This is the same failure SHAPE as the original outage inverted: there the
    monitor stayed silent while ingestion was broken, here it cries wolf while
    ingestion is fine. Both end with nobody trusting the signal.
    """
    from arbitrium.ingestion.polling import poll_interval_for

    mid_interval = poll_interval_for(NOW + timedelta(days=2), now=NOW)
    assert mid_interval == settings.odds_poll_mid_seconds

    # A write one interval old is plainly fine on that schedule.
    out = staleness_report(
        {"consensus": NOW - timedelta(seconds=mid_interval)},
        now=NOW,
        intervals={"consensus": mid_interval},
    )
    assert out["consensus"]["stale"] is False
    assert out["consensus"]["stale_after_seconds"] == (
        mid_interval * settings.ingest_staleness_interval_multiple
    )
    assert out["consensus"]["poll_interval_seconds"] == mid_interval


def test_the_flat_setting_would_have_called_a_healthy_poller_stale():
    """Pins the regression itself, so reverting to the flat interval fails here."""
    age = timedelta(hours=14, minutes=36)  # the observed live gap

    honest = staleness_report(
        {"consensus": NOW - age},
        now=NOW,
        intervals={"consensus": settings.odds_poll_mid_seconds},
    )
    assert honest["consensus"]["stale"] is False

    miscalibrated = staleness_report({"consensus": NOW - age}, now=NOW)
    assert miscalibrated["consensus"]["stale"] is True


def test_far_tier_tolerates_a_full_day_between_writes():
    """Beyond a week from kickoff the poller runs daily by design."""
    out = staleness_report(
        {"consensus": NOW - timedelta(hours=23)},
        now=NOW,
        intervals={"consensus": settings.odds_poll_far_seconds},
    )
    assert out["consensus"]["stale"] is False


def test_a_genuinely_dead_poller_is_still_caught_on_the_slowest_tier():
    """The fix must not blind the monitor: daily tier still flags a week of silence."""
    out = staleness_report(
        {"consensus": NOW - timedelta(days=7)},
        now=NOW,
        intervals={"consensus": settings.odds_poll_far_seconds},
    )
    assert out["consensus"]["stale"] is True


# --- strict mode, for external uptime monitoring ----------------------------


def test_strict_mode_turns_a_degraded_verdict_into_a_non_200(db_session, monkeypatch):
    """A dead scheduler must be able to page someone.

    /health returns 200 with a degraded body by default, which is right for a
    dashboard and useless for an uptime monitor — a monitor watching status
    codes would see a perfectly healthy service while ingestion was dead. That
    is precisely how the original week-long outage stayed invisible.

    Staleness is forced here rather than waited for: the real thing takes hours
    to appear, and a test that only passes when the live feed happens to be
    broken is not a test.
    """
    from fastapi import Response

    from arbitrium.api import main as api

    monkeypatch.setattr(
        api,
        "_ingestion_freshness",
        lambda db: {
            "kalshi": {
                "last_write_at": None, "age_seconds": None, "stale": True,
                "stale_after_seconds": 1800, "poll_interval_seconds": 300,
            }
        },
    )

    res = Response()
    body = api.health(strict=True, response=res, db=db_session)

    assert body["status"] == "degraded"
    assert res.status_code == 503


def test_a_stale_source_is_still_200_without_strict(db_session, monkeypatch):
    """Default mode stays 200 so the dashboard can render the reason."""
    from fastapi import Response

    from arbitrium.api import main as api

    monkeypatch.setattr(
        api,
        "_ingestion_freshness",
        lambda db: {
            "kalshi": {
                "last_write_at": None, "age_seconds": None, "stale": True,
                "stale_after_seconds": 1800, "poll_interval_seconds": 300,
            }
        },
    )

    res = Response()
    body = api.health(strict=False, response=res, db=db_session)
    assert body["status"] == "degraded"
    assert res.status_code != 503


def test_default_mode_still_returns_200_when_degraded(db_session):
    """The dashboard needs the body, not an error."""
    from fastapi import Response

    from arbitrium.api.main import health

    res = Response()
    health(strict=False, response=res, db=db_session)
    assert res.status_code != 503
