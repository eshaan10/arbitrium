"""/health ingestion freshness (Layer 3).

Derived from the append-only table rather than in-process counters, so it still
reports a growing age when the poller is dead or crash-looping — the failure mode
that made the original outage invisible.

The policy tests are pure: staleness must be judged against injected timestamps,
not against whatever the live poller has written to the shared table.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from arbitrium.api.main import _ingestion_freshness, consensus_report, staleness_report
from arbitrium.config import settings
from arbitrium.db.models import Event, OddsCheckpoint, OddsSnapshot
from arbitrium.ingestion.polling import missed_closes

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
    assert out["kalshi"]["last_write_at"] is None
    assert out["kalshi"]["age_seconds"] is None
    assert out["kalshi"]["stale"] is True


def test_only_interval_sources_are_judged_by_age():
    """Consensus runs on the game clock, so it has no interval to be late against."""
    assert set(staleness_report({}, now=NOW)) == {"kalshi"}


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


# --- consensus: judged by missed closes, not by gaps -------------------------


def test_a_long_quiet_gap_is_not_stale_on_the_game_clock():
    """Passes are hours or days apart by design; age alone means nothing.

    The adaptive-interval monitor once called a healthy poller stale for most
    of every week (a 14.6h gap judged against 15 minutes). Judging the game
    clock by age would repeat that with even longer gaps.
    """
    out = consensus_report(NOW - timedelta(days=4), 0, now=NOW)
    assert out["stale"] is False
    assert out["age_seconds"] == 4 * 86400
    assert out["schedule"] == "game_clock"


def test_a_missed_close_is_stale_however_recent_the_last_write():
    out = consensus_report(NOW - timedelta(minutes=2), 1, now=NOW)
    assert out["stale"] is True and out["missed_closes"] == 1


def test_never_written_and_nothing_missed_is_idle_not_stale():
    assert consensus_report(None, 0, now=NOW)["stale"] is False


LATER = datetime(2099, 10, 10, 12, 0, tzinfo=UTC)


def _tracked_game(db, *, start, sport="nfl"):
    ev = Event(
        sport=sport, league=sport.upper(), home_team="Seattle Seahawks",
        away_team="Los Angeles Rams", scheduled_start=start, status="scheduled",
        kalshi_event_ticker=f"KX-{start:%y%m%d%H%M}-{sport}",
        odds_api_event_id=f"odds-{start:%y%m%d%H%M}-{sport}",
    )
    db.add(ev)
    db.flush()
    return ev


def test_missed_closes_counts_games_that_started_without_one(db_session, monkeypatch):
    monkeypatch.setattr(settings, "odds_sports_enabled", ["nfl"])
    # The schedule was live before any of these games.
    anchor = _tracked_game(db_session, start=LATER - timedelta(days=3))
    db_session.add(OddsCheckpoint(event_id=anchor.id, sport="nfl", checkpoint="t24h",
                                  status="captured", captured_at=LATER - timedelta(days=2)))
    missed = _tracked_game(db_session, start=LATER - timedelta(hours=2))
    taken = _tracked_game(db_session, start=LATER - timedelta(hours=3))
    skipped = _tracked_game(db_session, start=LATER - timedelta(hours=4))
    _tracked_game(db_session, start=LATER + timedelta(minutes=2))  # close not yet due
    _tracked_game(db_session, start=LATER - timedelta(hours=1), sport="nba")  # disabled sport
    db_session.add_all([
        OddsCheckpoint(event_id=taken.id, sport="nfl", checkpoint="close", status="captured"),
        OddsCheckpoint(event_id=skipped.id, sport="nfl", checkpoint="close",
                       status="skipped_budget", reason="reserve"),
    ])
    db_session.flush()
    assert missed is not None
    assert missed_closes(db_session, now=LATER) == 1


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
