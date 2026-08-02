"""Pure score parsing and winner determination.

Pins the failure modes that would silently corrupt calibration ground truth:
string-typed scores (the bug class that already cost this project a silent
ingestion outage), positional score matching, and any home/away-relative winner
encoding.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from marketedge.ingestion.odds_api import MAX_SCORES_DAYS_FROM, ODDS_SPORTS, OddsApiClient
from marketedge.ingestion.resolution import (
    coerce_score,
    decide_winner,
    extract_score,
)

NFL = ODDS_SPORTS["americanfootball_nfl"]
UTC = timezone.utc


def _payload(home, away, home_score, away_score, *, completed=True, reverse=False):
    scores = [{"name": home, "score": home_score}, {"name": away, "score": away_score}]
    if reverse:
        scores.reverse()
    return {
        "id": "abc123",
        "sport_key": "americanfootball_nfl",
        "commence_time": "2026-09-14T17:00:00Z",
        "completed": completed,
        "home_team": home,
        "away_team": away,
        "scores": None if not completed else scores,
    }


# --- score coercion (the *_dollars bug class) --------------------------------


def test_string_score_is_parsed():
    assert coerce_score("5") == 5
    assert coerce_score("24") == 24


@pytest.mark.parametrize("bad", [None, "", "abc", {}, [], True, False])
def test_unparseable_score_is_none_never_zero(bad):
    """A wrong 0 would fabricate a shutout, so None is the only safe default."""
    assert coerce_score(bad) is None


# --- winner determination ----------------------------------------------------


def test_winner_is_the_higher_scoring_team_name():
    assert decide_winner("Chiefs", "Broncos", 24, 17) == "Chiefs"
    assert decide_winner("Chiefs", "Broncos", 10, 31) == "Broncos"


def test_tie_returns_none():
    assert decide_winner("Chiefs", "Broncos", 17, 17) is None


def test_winner_is_home_away_agnostic():
    """The core design property: swapping which team is 'home' changes nothing.

    This is what makes a recorded result immune to a later authoritative
    home/away correction — the same bug class migration 0005 fixed for snapshots.
    """
    a = decide_winner("Chiefs", "Broncos", 24, 17)
    b = decide_winner("Broncos", "Chiefs", 17, 24)
    assert a == b == "Chiefs"


# --- extraction --------------------------------------------------------------


def test_completed_game_extracts():
    out = extract_score(
        _payload("Kansas City Chiefs", "Denver Broncos", "24", "17"), NFL
    )
    assert out is not None
    assert (out.home_score, out.away_score) == (24, 17)
    assert out.winner_team == "Kansas City Chiefs"
    assert out.commence_time == datetime(2026, 9, 14, 17, 0, tzinfo=UTC)


def test_scores_are_matched_by_name_not_position():
    """The API guarantees no ordering; a positional read would invert the result."""
    forward = extract_score(
        _payload("Kansas City Chiefs", "Denver Broncos", "24", "17"), NFL
    )
    reversed_ = extract_score(
        _payload("Kansas City Chiefs", "Denver Broncos", "24", "17", reverse=True), NFL
    )
    assert forward.home_score == reversed_.home_score == 24
    assert forward.away_score == reversed_.away_score == 17
    assert forward.winner_team == reversed_.winner_team == "Kansas City Chiefs"


def test_incomplete_game_is_skipped():
    """The offseason/in-progress case: 100 NFL events, none completed."""
    assert extract_score(
        _payload("Kansas City Chiefs", "Denver Broncos", None, None, completed=False), NFL
    ) is None


def test_missing_scores_is_skipped():
    p = _payload("Kansas City Chiefs", "Denver Broncos", "24", "17")
    p["scores"] = None
    assert extract_score(p, NFL) is None


def test_one_unparseable_score_skips_the_whole_event():
    """Half a result is worse than none — it would grade against a fake score."""
    assert extract_score(
        _payload("Kansas City Chiefs", "Denver Broncos", "24", "oops"), NFL
    ) is None


def test_unknown_team_is_skipped():
    assert extract_score(_payload("Kansas City Chiefs", "London Monarchs", "24", "17"), NFL) is None


def test_tie_extracts_with_no_winner():
    out = extract_score(_payload("Kansas City Chiefs", "Denver Broncos", "20", "20"), NFL)
    assert out is not None
    assert out.winner_team is None  # a real draw, distinct from unresolved


def test_completed_zero_zero_is_skipped_as_implausible():
    """Far likelier a premature `completed` flag than a real NFL 0-0."""
    assert extract_score(
        _payload("Kansas City Chiefs", "Denver Broncos", "0", "0"), NFL
    ) is None


# --- client guard ------------------------------------------------------------


def test_days_from_beyond_the_api_ceiling_raises_locally():
    """A config typo must not cost a credit AND a pass inside an unrepeatable window."""
    client = OddsApiClient(api_key="dummy")
    with pytest.raises(ValueError, match="between 1 and 3"):
        client.get_scores("americanfootball_nfl", days_from=MAX_SCORES_DAYS_FROM + 1)
    with pytest.raises(ValueError):
        client.get_scores("americanfootball_nfl", days_from=0)
    client.close()
