"""ESPN fallback resolution.

Pins the behaviours that make a second source safe rather than merely available:
it must never resolve the wrong game when it has no shared identifier, it must
never take down a pass the primary already served, and it must be able to
recover an outcome we previously gave up on.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from arbitrium.db.models import Event
from arbitrium.ingestion.espn import (
    ESPN_SPORTS,
    EspnClient,
    extract_espn_event,
    fetch_results,
    sweep_dates,
)
from arbitrium.ingestion.outcomes import ScoreExtract
from arbitrium.ingestion.resolution import (
    ESPN_RESOLUTION_SOURCE,
    ResolutionOutcome,
    backfill_targets,
    resolve_event,
)

UTC = timezone.utc


def _espn(home, away, home_score, away_score, *, completed=True,
          date="2026-08-07T00:00Z"):
    return {
        "id": "espn-1",
        "date": date,
        "competitions": [{
            "status": {"type": {"name": "STATUS_FINAL", "completed": completed}},
            "competitors": [
                {"homeAway": "home", "team": {"displayName": home}, "score": home_score},
                {"homeAway": "away", "team": {"displayName": away}, "score": away_score},
            ],
        }],
    }


# --- pure extraction ---------------------------------------------------------


def test_extracts_a_completed_game():
    out = extract_espn_event(
        _espn("Arizona Cardinals", "Carolina Panthers", "30", "33"), "nfl")
    assert out is not None
    assert (out.home_score, out.away_score) == (30, 33)
    assert out.winner_team == "Carolina Panthers"
    assert out.commence_time == datetime(2026, 8, 7, 0, 0, tzinfo=UTC)


def test_scores_arrive_as_strings_like_the_odds_api():
    """Same bug class as the Kalshi *_dollars fields; both sources send strings."""
    out = extract_espn_event(
        _espn("Kansas City Chiefs", "Denver Broncos", "24", "17"), "nfl")
    assert isinstance(out.home_score, int) and out.home_score == 24


def test_home_and_away_come_from_the_role_not_array_order():
    forward = extract_espn_event(
        _espn("Kansas City Chiefs", "Denver Broncos", "24", "17"), "nfl")
    p = _espn("Kansas City Chiefs", "Denver Broncos", "24", "17")
    p["competitions"][0]["competitors"].reverse()
    reversed_ = extract_espn_event(p, "nfl")
    assert forward.home_score == reversed_.home_score == 24
    assert forward.winner_team == reversed_.winner_team


def test_incomplete_game_is_skipped():
    assert extract_espn_event(
        _espn("Kansas City Chiefs", "Denver Broncos", None, None, completed=False), "nfl"
    ) is None


def test_unresolved_team_is_skipped():
    assert extract_espn_event(
        _espn("Kansas City Chiefs", "London Monarchs", "24", "17"), "nfl") is None


def test_completed_zero_zero_is_skipped():
    assert extract_espn_event(
        _espn("Kansas City Chiefs", "Denver Broncos", "0", "0"), "nfl") is None


def test_no_shared_identifier_is_left_empty():
    """Must be falsy so resolution falls through to the matcher rather than
    matching every event whose odds id IS NULL."""
    out = extract_espn_event(
        _espn("Kansas City Chiefs", "Denver Broncos", "24", "17"), "nfl")
    assert out.odds_api_event_id == ""
    assert not out.odds_api_event_id


# --- date handling -----------------------------------------------------------


def test_sweep_covers_the_utc_versus_us_date_gap():
    """ESPN buckets by US calendar date; we store UTC. An evening kickoff lands
    on the previous US day, so a single-date lookup would miss it."""
    dates = sweep_dates(datetime(2026, 8, 6, 0, 0, tzinfo=UTC))
    assert dates == ["20260805", "20260806", "20260807"]


def test_espn_sport_mapping_covers_ingested_sports():
    assert ESPN_SPORTS["nfl"] == "football/nfl"


# --- resilience --------------------------------------------------------------


def test_client_returns_empty_on_failure_never_raises():
    """A fallback that raises would take down a pass the primary already served."""
    c = EspnClient(base_url="http://127.0.0.1:1")
    assert c.get_scoreboard("nfl", "20260806") == []
    c.close()


def test_unknown_sport_is_skipped_not_fatal():
    c = EspnClient()
    assert c.get_scoreboard("underwater_basketweaving", "20260806") == []
    c.close()


def test_fetch_results_deduplicates_dates(monkeypatch):
    """Two games the same day must not cost two lookups per date."""
    calls = []

    class Stub(EspnClient):
        def __init__(self): pass
        def get_scoreboard(self, sport, date):
            calls.append((sport, date))
            return []
        def close(self): pass

    start = datetime(2026, 8, 6, 0, 0, tzinfo=UTC)
    fetch_results([("nfl", start), ("nfl", start)], client=Stub())
    assert len(calls) == 3  # the +/-1 sweep, once — not six


# --- the wrong-game guard ----------------------------------------------------


def test_empty_odds_id_does_not_match_a_kalshi_only_event(db_session):
    """The guard that matters most.

    SQLAlchemy renders `== None` as `IS NULL`, so an ESPN extract (no odds id)
    would otherwise match an arbitrary Kalshi-only event and write the result of
    one game onto another.
    """
    start = datetime.now(UTC) + timedelta(days=700)
    unrelated = Event(
        sport="nfl", league="NFL", home_team="Buffalo Bills", away_team="Miami Dolphins",
        scheduled_start=start, status="scheduled", odds_api_event_id=None,
    )
    db_session.add(unrelated)
    db_session.flush()

    # A result for a completely different matchup, far from that date.
    extract = ScoreExtract(
        odds_api_event_id="", home_team="Kansas City Chiefs", away_team="Denver Broncos",
        home_score=24, away_score=17, winner_team="Kansas City Chiefs",
        commence_time=start + timedelta(days=60), sport="nfl",
    )
    assert resolve_event(db_session, extract) is ResolutionOutcome.NOT_FOUND
    db_session.refresh(unrelated)
    assert unrelated.status == "scheduled"
    assert unrelated.winner_team is None


# --- recovery ----------------------------------------------------------------


def test_a_condemned_event_can_be_recovered(db_session):
    """`unresolvable` means we failed to collect it, not that it never happened."""
    start = datetime.now(UTC) - timedelta(days=5)
    ev = Event(
        sport="nfl", league="NFL", home_team="Arizona Cardinals",
        away_team="Carolina Panthers", scheduled_start=start,
        status="unresolvable", unresolvable_reason="window_expired",
        odds_api_event_id="odds-recover-1",
    )
    db_session.add(ev)
    db_session.flush()

    extract = ScoreExtract(
        odds_api_event_id="odds-recover-1", home_team="Arizona Cardinals",
        away_team="Carolina Panthers", home_score=30, away_score=33,
        winner_team="Carolina Panthers", commence_time=start, sport="nfl",
    )
    assert resolve_event(db_session, extract, source=ESPN_RESOLUTION_SOURCE) is (
        ResolutionOutcome.RESOLVED
    )
    db_session.flush()
    db_session.refresh(ev)

    assert ev.status == "final"
    assert ev.winner_team == "Carolina Panthers"
    assert ev.winner_side == "away"  # generated column, Carolina is the away team
    assert ev.resolution_source == ESPN_RESOLUTION_SOURCE  # distinguishable from on-time
    assert ev.unresolvable_reason is None  # the condemnation is cleared


def test_backfill_targets_includes_condemned_events(db_session):
    start = datetime.now(UTC) - timedelta(days=6)
    ev = Event(
        sport="nfl", league="NFL", home_team="Chicago Bears", away_team="Green Bay Packers",
        scheduled_start=start, status="unresolvable", unresolvable_reason="window_expired",
    )
    db_session.add(ev)
    db_session.flush()
    targets = backfill_targets(db_session)
    assert ("nfl", start) in targets


def test_backfill_targets_excludes_games_not_yet_played(db_session):
    ev = Event(
        sport="nfl", league="NFL", home_team="New York Jets", away_team="Tennessee Titans",
        scheduled_start=datetime.now(UTC) + timedelta(days=3), status="scheduled",
    )
    db_session.add(ev)
    db_session.flush()
    assert all(s != ev.scheduled_start for _, s in backfill_targets(db_session))


def test_a_final_event_is_never_overwritten_by_the_fallback(db_session):
    """Recovery must not become a licence to rewrite settled results."""
    start = datetime.now(UTC) - timedelta(days=5)
    ev = Event(
        sport="nfl", league="NFL", home_team="Kansas City Chiefs", away_team="Denver Broncos",
        scheduled_start=start, status="final", home_score=24, away_score=17,
        winner_team="Kansas City Chiefs", odds_api_event_id="odds-final-1",
    )
    db_session.add(ev)
    db_session.flush()

    extract = ScoreExtract(
        odds_api_event_id="odds-final-1", home_team="Kansas City Chiefs",
        away_team="Denver Broncos", home_score=21, away_score=17,
        winner_team="Kansas City Chiefs", commence_time=start, sport="nfl",
    )
    assert resolve_event(db_session, extract, source=ESPN_RESOLUTION_SOURCE) is (
        ResolutionOutcome.CONFLICT
    )
    db_session.refresh(ev)
    assert ev.home_score == 24  # untouched
