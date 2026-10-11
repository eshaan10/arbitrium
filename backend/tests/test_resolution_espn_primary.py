"""ESPN-primary resolution, with the paid scores call as a gated fallback.

Each scores call costs 2 credits. With three sports in season, resolving
everything through it would spend a real share of a 500-credit month on data
ESPN gives away, so ESPN goes first and the paid call only sees what ESPN left
behind — late in the window, in enabled sports, and never out of the reserve.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from arbitrium.config import settings
from arbitrium.db.models import Event
from arbitrium.ingestion import espn, resolution
from arbitrium.ingestion.outcomes import ScoreExtract

UTC = timezone.utc
LATER = datetime(2099, 10, 20, 12, 0, tzinfo=UTC)
SEA, LAR = "Seattle Seahawks", "Los Angeles Rams"


def _event(db, *, start, sport="nfl", odds_id=None):
    ev = Event(sport=sport, league=sport.upper(), home_team=SEA, away_team=LAR,
               scheduled_start=start, status="scheduled", odds_api_event_id=odds_id)
    db.add(ev)
    db.flush()
    return ev


# --- what the fallback is allowed to ask about ---------------------------------------


def test_fallback_targets_only_old_enough_games_in_enabled_sports(db_session, monkeypatch):
    monkeypatch.setattr(settings, "odds_sports_enabled", ["nfl"])
    old = _event(db_session, start=LATER - timedelta(hours=50))
    _event(db_session, start=LATER - timedelta(hours=10))  # ESPN still has time
    _event(db_session, start=LATER - timedelta(hours=90))  # past the scores window
    _event(db_session, start=LATER - timedelta(hours=50), sport="nba")  # disabled
    assert resolution.fallback_targets(db_session, now=LATER) == [("nfl", old.scheduled_start)]


def test_fallback_keys_follow_the_season_of_the_game():
    """A preseason key is not asked about a regular-season game: 2 credits for nothing."""
    oct_nfl = datetime(2026, 10, 12, tzinfo=UTC)
    assert resolution.fallback_keys([("nfl", oct_nfl)]) == ["americanfootball_nfl"]
    oct_nba = datetime(2026, 10, 12, tzinfo=UTC)
    assert resolution.fallback_keys([("nba", oct_nba)]) == [
        "basketball_nba", "basketball_nba_preseason"
    ]
    assert resolution.fallback_keys([]) == []


# --- the pass ------------------------------------------------------------------


class _NoPaidCalls:
    def __init__(self, *a, **k):
        raise AssertionError("the paid scores endpoint must not be called")


class _FakeScores:
    def __init__(self, payloads):
        self.payloads = payloads
        self.calls: list[str] = []

    def __call__(self, *a, **k):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def get_scores(self, sport_key):
        self.calls.append(sport_key)
        return self.payloads

    quota_remaining = 400


@pytest.fixture
def wired(db_session, monkeypatch):
    """Point run_resolution at the test transaction and a far-future clock."""
    monkeypatch.setattr(settings, "odds_sports_enabled", ["nfl"])
    monkeypatch.setattr(resolution, "get_session",
                        lambda: Session(bind=db_session.connection()))
    real_targets = resolution.fallback_targets
    monkeypatch.setattr(resolution, "fallback_targets",
                        lambda s: real_targets(s, now=LATER))
    monkeypatch.setattr(resolution, "mark_unresolvable", lambda s: 0)
    return db_session


def _extract(start, *, home_score=27, away_score=20):
    return ScoreExtract(
        odds_api_event_id="", home_team=SEA, away_team=LAR,
        home_score=home_score, away_score=away_score,
        winner_team=SEA if home_score > away_score else LAR,
        commence_time=start, sport="nfl",
    )


def test_espn_resolves_first_and_the_paid_call_is_never_made(wired, monkeypatch):
    ev = _event(wired, start=LATER - timedelta(hours=50))
    monkeypatch.setattr(resolution, "backfill_targets", lambda s: [("nfl", ev.scheduled_start)])
    monkeypatch.setattr(resolution, "fetch_results", lambda t: [_extract(ev.scheduled_start)])
    monkeypatch.setattr(resolution, "OddsApiClient", _NoPaidCalls)

    result, counts = resolution.run_resolution()

    wired.refresh(ev)
    assert (ev.status, ev.resolution_source) == ("final", resolution.ESPN_RESOLUTION_SOURCE)
    assert result.rows_written == 1 and counts["resolved"] == 1


def test_the_paid_fallback_covers_what_espn_left_behind(wired, monkeypatch):
    ev = _event(wired, start=LATER - timedelta(hours=50), odds_id="odds-espn-missed")
    monkeypatch.setattr(resolution, "backfill_targets", lambda s: [("nfl", ev.scheduled_start)])
    monkeypatch.setattr(resolution, "fetch_results", lambda t: [])  # ESPN has nothing
    monkeypatch.setattr(resolution, "resolution_affordable", lambda cost: True)
    scores = _FakeScores([{
        "id": "odds-espn-missed", "completed": True, "home_team": SEA, "away_team": LAR,
        "commence_time": ev.scheduled_start.isoformat(),
        "scores": [{"name": SEA, "score": "17"}, {"name": LAR, "score": "24"}],
    }])
    monkeypatch.setattr(resolution, "OddsApiClient", scores)

    resolution.run_resolution()

    wired.refresh(ev)
    assert scores.calls == ["americanfootball_nfl"]
    assert (ev.status, ev.winner_team, ev.resolution_source) == (
        "final", LAR, resolution.RESOLUTION_SOURCE
    )


def test_the_fallback_never_spends_the_reserve(wired, monkeypatch, caplog):
    ev = _event(wired, start=LATER - timedelta(hours=50))
    monkeypatch.setattr(resolution, "backfill_targets", lambda s: [("nfl", ev.scheduled_start)])
    monkeypatch.setattr(resolution, "fetch_results", lambda t: [])
    monkeypatch.setattr(resolution, "resolution_affordable", lambda cost: False)
    scores = _FakeScores([])
    monkeypatch.setattr(resolution, "OddsApiClient", scores)

    _, counts = resolution.run_resolution()

    assert scores.calls == []
    assert counts["fallback_skipped_reserve"] == 1
    assert "reserve" in caplog.text


def test_a_young_unresolved_game_waits_for_espn(wired, monkeypatch):
    _event(wired, start=LATER - timedelta(hours=6))
    monkeypatch.setattr(resolution, "backfill_targets", lambda s: [])
    monkeypatch.setattr(resolution, "fetch_results", lambda t: [])
    monkeypatch.setattr(resolution, "OddsApiClient", _NoPaidCalls)
    resolution.run_resolution()  # must not reach the paid endpoint


def test_espn_failure_does_not_take_the_pass_down(wired, monkeypatch):
    monkeypatch.setattr(resolution, "backfill_targets", lambda s: [("nfl", LATER)])

    def boom(targets):
        raise RuntimeError("espn changed shape")

    monkeypatch.setattr(resolution, "fetch_results", boom)
    monkeypatch.setattr(resolution, "OddsApiClient", _NoPaidCalls)
    result, _ = resolution.run_resolution()
    assert result.rows_written == 0


# --- ESPN team ids for NBA / NHL ------------------------------------------------


def _espn(sport_home, sport_away, *, home_id="13", away_id="2"):
    return {
        "id": "espn-9", "date": "2026-11-03T00:00Z",
        "competitions": [{
            "status": {"type": {"completed": True}},
            "competitors": [
                {"homeAway": "home", "score": "110",
                 "team": {"id": home_id, "displayName": sport_home}},
                {"homeAway": "away", "score": "104",
                 "team": {"id": away_id, "displayName": sport_away}},
            ],
        }],
    }


def test_an_nba_final_resolves_through_the_espn_id(db_session):
    """End to end: ESPN payload -> team_by_espn_id -> the Kalshi-created event.

    The display name is deliberately wrong-shaped ("LA Clippers", and a home
    name that matches nothing): resolution goes by id, so names cannot matter.
    """
    start = datetime(2099, 11, 3, 3, 30, tzinfo=UTC)
    ev = Event(sport="nba", league="NBA", home_team="Los Angeles Lakers",
               away_team="Los Angeles Clippers", scheduled_start=start, status="scheduled",
               kalshi_event_ticker="KXNBAGAME-99NOV02LACLAL")
    db_session.add(ev)
    db_session.flush()

    payload = _espn("Lakers (renamed)", "LA Clippers", home_id="13", away_id="12")
    payload["date"] = "2099-11-03T03:30Z"
    extract = espn.extract_espn_event(payload, "nba")
    assert (extract.home_team, extract.away_team, extract.winner_team) == (
        "Los Angeles Lakers", "Los Angeles Clippers", "Los Angeles Lakers"
    )

    outcome = resolution.resolve_event(db_session, extract,
                                       source=resolution.ESPN_RESOLUTION_SOURCE)
    db_session.refresh(ev)
    assert outcome is resolution.ResolutionOutcome.RESOLVED
    assert (ev.status, ev.home_score, ev.away_score, ev.winner_team, ev.resolution_source) == (
        "final", 110, 104, "Los Angeles Lakers", resolution.ESPN_RESOLUTION_SOURCE
    )


def test_espn_ids_are_scoped_by_league():
    """ESPN id 2 is the Celtics in the NBA and the Bills in the NFL."""
    assert espn.resolve_by_espn_id("NBA", "2").name == "Boston Celtics"
    assert espn.resolve_by_espn_id("NFL", "2").name == "Buffalo Bills"


def test_an_unknown_espn_id_is_skipped_not_guessed(caplog):
    payload = _espn("Los Angeles Lakers", "Boston Celtics", home_id="13", away_id="99999")
    assert espn.extract_espn_event(payload, "nba") is None
    assert "id 99999" in caplog.text


def test_nhl_without_a_registry_resolves_nothing():
    assert espn.extract_espn_event(_espn("Boston Bruins", "Toronto Maple Leafs"), "nhl") is None


def test_nfl_still_resolves_by_name():
    extract = espn.extract_espn_event(_espn(SEA, LAR, home_id="", away_id=""), "nfl")
    assert (extract.home_team, extract.away_team) == (SEA, LAR)


def test_nhl_has_an_espn_path():
    assert espn.ESPN_SPORTS["nhl"] == "hockey/nhl"
    assert espn.ESPN_LEAGUE["nhl"] == "NHL"
