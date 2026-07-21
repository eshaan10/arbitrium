"""Edge-case coverage for the pure cross-source event matcher."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from marketedge.matching import (
    EventKey,
    MatchCandidate,
    MatchStatus,
    match_event,
)

UTC = timezone.utc


def _key(sport="nfl", home="Kansas City Chiefs", away="Denver Broncos", start=None):
    return EventKey(sport, home, away, start or datetime(2026, 9, 14, tzinfo=UTC))


def _cand(ident, **kw):
    return MatchCandidate(identifier=ident, key=_key(**kw))


# --- #1 postponement window + boundary --------------------------------------


def test_match_same_day():
    target = _key(start=datetime(2026, 9, 14, 17, 0, tzinfo=UTC))
    cand = _cand("A", start=datetime(2026, 9, 14, 0, 0, tzinfo=UTC))
    res = match_event(target, [cand], window_days=3)
    assert res.status is MatchStatus.MATCHED and res.candidate.identifier == "A"


def test_match_postponement_within_window():
    target = _key(start=datetime(2026, 9, 16, 17, 0, tzinfo=UTC))  # ~2.7d after
    cand = _cand("A", start=datetime(2026, 9, 14, 0, 0, tzinfo=UTC))
    assert match_event(target, [cand], window_days=3).status is MatchStatus.MATCHED


def test_match_at_exact_window_boundary_inclusive():
    base = datetime(2026, 9, 14, 0, 0, tzinfo=UTC)
    target = _key(start=base + timedelta(days=3))  # exactly 3 days
    assert match_event(target, [_cand("A", start=base)], window_days=3).status is MatchStatus.MATCHED


def test_no_match_just_beyond_window():
    base = datetime(2026, 9, 14, 0, 0, tzinfo=UTC)
    target = _key(start=base + timedelta(days=3, seconds=1))  # just over 3 days
    res = match_event(target, [_cand("A", start=base)], window_days=3)
    assert res.status is MatchStatus.UNMATCHED
    assert "window" in res.reason


# --- #2 UTC-midnight skew ----------------------------------------------------


def test_match_utc_midnight_skew():
    # Kalshi ticker date (Sun) vs Odds API kickoff crossing UTC midnight (Mon).
    kalshi = _cand("A", start=datetime(2026, 9, 13, 0, 0, tzinfo=UTC))
    target = _key(start=datetime(2026, 9, 14, 0, 15, tzinfo=UTC))  # ~1.01 days
    assert match_event(target, [kalshi], window_days=3).status is MatchStatus.MATCHED


# --- #3 doubleheader tie-break ----------------------------------------------


def test_doubleheader_picks_nearest():
    game1 = _cand("G1", start=datetime(2026, 9, 14, 0, 0, tzinfo=UTC))
    game2 = _cand("G2", start=datetime(2026, 9, 15, 0, 0, tzinfo=UTC))
    target = _key(start=datetime(2026, 9, 14, 2, 0, tzinfo=UTC))  # closest to G1
    res = match_event(target, [game1, game2], window_days=3)
    assert res.status is MatchStatus.MATCHED and res.candidate.identifier == "G1"


def test_doubleheader_equidistant_is_ambiguous():
    game1 = _cand("G1", start=datetime(2026, 9, 14, 0, 0, tzinfo=UTC))
    game2 = _cand("G2", start=datetime(2026, 9, 16, 0, 0, tzinfo=UTC))
    target = _key(start=datetime(2026, 9, 15, 0, 0, tzinfo=UTC))  # exactly between
    res = match_event(target, [game1, game2], window_days=3)
    assert res.status is MatchStatus.AMBIGUOUS


# --- team-pair identity ------------------------------------------------------


def test_unmatched_when_no_team_pair():
    target = _key(home="Buffalo Bills", away="Miami Dolphins")
    cand = _cand("A")  # different pair (KC/DEN)
    res = match_event(target, [cand], window_days=3)
    assert res.status is MatchStatus.UNMATCHED and "team pair" in res.reason


def test_team_pair_is_order_independent():
    # Provisional home/away may be reversed vs authoritative; the unordered pair
    # must still match, so a later home/away flip never breaks matching.
    target = _key(home="Kansas City Chiefs", away="Denver Broncos")
    cand = _cand("A", home="Denver Broncos", away="Kansas City Chiefs")  # swapped
    assert match_event(target, [cand], window_days=3).status is MatchStatus.MATCHED


def test_different_sport_does_not_match():
    target = EventKey("nba", "Kansas City Chiefs", "Denver Broncos", datetime(2026, 9, 14, tzinfo=UTC))
    cand = _cand("A")  # nfl
    assert match_event(target, [cand], window_days=3).status is MatchStatus.UNMATCHED
