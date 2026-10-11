"""NBA end to end: Kalshi extraction, repeat-matchup matching, per-sport calibration.

The NBA-specific hazard is the REPEAT MATCHUP. The same two teams meet again
within 1-3 days ~190 times a season (two-game sets, every playoff series), so
"same team pair inside the window" no longer identifies one game. These tests pin
down that each such case is decided deliberately — matched to the right game,
left unmatched, or flagged ambiguous — and never silently merged into the wrong one.

Synthetic '99' tickers / far-future dates throughout: the fixture rolls back, but
it still reads the real committed tables.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from arbitrium.api.main import performance
from arbitrium.db.models import Event
from arbitrium.ingestion.kalshi import (
    SERIES_CONFIG,
    KalshiEventMetadata,
    extract_event_metadata,
    ingest_event,
    upsert_event,
)
from arbitrium.ingestion.odds_api import OddsSport, ingest_odds_event
from arbitrium.ingestion.snapshots import insert_snapshots
from arbitrium.matching import EventKey, MatchCandidate, MatchStatus, match_event, match_window

UTC = timezone.utc
OCT16 = datetime(2099, 10, 16, tzinfo=UTC)  # a ticker date, midnight UTC
CELTICS, SIXERS = "Boston Celtics", "Philadelphia 76ers"
NBA_KALSHI = SERIES_CONFIG["KXNBAGAME"]
NFL_KALSHI = SERIES_CONFIG["KXNFLGAME"]
NBA_ODDS = OddsSport("nba", "NBA")

BOS = ("BOS", "Boston Celtics", "6dd427f5-fa02-40ef-aa90-cfa73e0c539e")
PHI = ("PHI", "Philadelphia 76ers", "0554528d-586b-461f-827b-801cf93e8a8e")

_MON = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()


def _kalshi_nba_event(away, home, tip: datetime, *, ticker_date: datetime | None = None,
                      occurrence: str | None = "auto"):
    """A KXNBAGAME event shaped like the live payload (KXNBAGAME-26OCT16BOSPHI).

    ``ticker_date`` is the US calendar date in the ticker; it defaults to the tip
    minus 6h, which is the US date for any evening tip.
    """
    d = ticker_date or (tip - timedelta(hours=6))
    event_ticker = f"KXNBAGAME-{d:%y}{_MON[d.month - 1]}{d:%d}{away[0]}{home[0]}"
    occ = occurrence
    if occurrence == "auto":
        occ = (tip + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def market(team):
        m = {
            "ticker": f"{event_ticker}-{team[0]}",
            "custom_strike": {"basketball_team": team[2]},
            "yes_bid_dollars": "0.4500", "yes_ask_dollars": "0.5500",
            "last_price_dollars": "0.5000",
            "yes_bid_size_fp": "1000.00", "yes_ask_size_fp": "1000.00",
            "volume_fp": "0.00", "open_interest_fp": "0.00", "status": "active",
        }
        if occ is not None:
            m["occurrence_datetime"] = occ
        return m

    return {"event_ticker": event_ticker, "markets": [market(away), market(home)]}


def _odds_event(event_id, home, away, commence: datetime):
    return {
        "id": event_id,
        "commence_time": commence.isoformat(),
        "home_team": home,
        "away_team": away,
        "bookmakers": [
            {"key": "draftkings", "markets": [{"key": "h2h", "outcomes": [
                {"name": home, "price": -150}, {"name": away, "price": 130}]}]},
            {"key": "fanduel", "markets": [{"key": "h2h", "outcomes": [
                {"name": home, "price": -145}, {"name": away, "price": 125}]}]},
        ],
    }


def _future_tip(day=1):
    """A 7pm-ET tip in Dec 2099 — far from any real row."""
    return datetime(2099, 12, day, 0, 0, tzinfo=UTC)


# --- Kalshi extraction -------------------------------------------------------


def test_nba_event_resolves_teams_and_exact_tip():
    tip = datetime(2099, 10, 16, 23, 0, tzinfo=UTC)  # BOS @ PHI, 7pm ET
    meta = extract_event_metadata(_kalshi_nba_event(BOS, PHI, tip), NBA_KALSHI)
    assert meta is not None
    assert (meta.away_team, meta.home_team) == ("Boston Celtics", "Philadelphia 76ers")
    assert meta.scheduled_start == tip  # occurrence_datetime minus 3h, not midnight
    assert meta.sport == "nba" and meta.league == "NBA"


def test_nba_uuid_mismatch_skips_the_event():
    """The basketball_team UUID is now actually checked (it used to read
    football_team and so never ran)."""
    event = _kalshi_nba_event(BOS, PHI, datetime(2099, 10, 16, 23, 0, tzinfo=UTC))
    event["markets"][0]["custom_strike"]["basketball_team"] = PHI[2]  # BOS suffix, PHI uuid
    assert extract_event_metadata(event, NBA_KALSHI) is None


def test_late_west_coast_tip_lands_on_the_next_utc_day():
    tip = datetime(2099, 10, 17, 2, 30, tzinfo=UTC)  # 10:30pm ET on Oct 16
    event = _kalshi_nba_event(BOS, PHI, tip, ticker_date=datetime(2099, 10, 16, tzinfo=UTC))
    assert extract_event_metadata(event, NBA_KALSHI).scheduled_start == tip


def test_missing_occurrence_falls_back_to_ticker_date():
    event = _kalshi_nba_event(BOS, PHI, datetime(2099, 10, 16, 23, 0, tzinfo=UTC), occurrence=None)
    assert extract_event_metadata(event, NBA_KALSHI).scheduled_start == OCT16


def test_implausible_occurrence_falls_back_to_ticker_date():
    """If the field ever stops meaning tip+3h, trusting it would mis-match games."""
    event = _kalshi_nba_event(
        BOS, PHI, datetime(2099, 10, 16, 23, 0, tzinfo=UTC), occurrence="2099-10-25T02:00:00Z"
    )
    assert extract_event_metadata(event, NBA_KALSHI).scheduled_start == OCT16


def test_nfl_still_uses_the_ticker_date():
    assert NFL_KALSHI.occurrence_lead is None


# --- the matcher: repeat matchups (pure) -------------------------------------


def _key(start, home="Philadelphia 76ers", away="Boston Celtics", sport="nba"):
    return EventKey(sport, home, away, start)


def test_window_is_per_sport():
    assert match_window("nba") == timedelta(hours=12)
    assert match_window("nfl") == timedelta(days=3)


def test_back_to_back_matches_the_right_game():
    """Game 1 tonight, game 2 tomorrow, both already on file."""
    g1 = datetime(2099, 12, 1, 0, 0, tzinfo=UTC)
    g2 = g1 + timedelta(days=1)
    cands = [MatchCandidate("g1", _key(g1)), MatchCandidate("g2", _key(g2, CELTICS, SIXERS))]
    assert match_event(_key(g1), cands).candidate.identifier == "g1"
    assert match_event(_key(g2), cands).candidate.identifier == "g2"


def test_back_to_back_was_a_silent_mis_merge_under_the_old_rules():
    """Why the window changed. With Kalshi on midnight-UTC ticker dates and the
    ±3d window, the first game's 1am-UTC tip sits 25h from its own row and 1h
    from the next day's — a confident MATCH to the wrong game, not an ambiguity."""
    tip1 = datetime(2099, 12, 1, 1, 0, tzinfo=UTC)  # game 1, US date Nov 30
    row1 = MatchCandidate("g1", _key(datetime(2099, 11, 30, tzinfo=UTC)))
    row2 = MatchCandidate("g2", _key(datetime(2099, 12, 1, tzinfo=UTC)))
    old = match_event(_key(tip1), [row1, row2], window_days=3)
    assert old.status is MatchStatus.MATCHED and old.candidate.identifier == "g2"


def test_only_the_other_game_on_file_is_unmatched_not_merged():
    """Two days apart and only game 2 exists yet: game 1 must NOT claim it."""
    g1 = datetime(2099, 12, 1, 0, 0, tzinfo=UTC)
    only_g2 = [MatchCandidate("g2", _key(g1 + timedelta(days=2)))]
    assert match_event(_key(g1), only_g2).status is MatchStatus.UNMATCHED
    # Even a back-to-back's 24h gap is outside the NBA window.
    only_next = [MatchCandidate("g2", _key(g1 + timedelta(days=1)))]
    assert match_event(_key(g1), only_next).status is MatchStatus.UNMATCHED


def test_two_same_pair_rows_inside_the_window_are_ambiguous():
    """Cannot happen in the NBA schedule; if it ever does, refuse to pick."""
    tip = datetime(2099, 12, 1, 0, 0, tzinfo=UTC)
    cands = [MatchCandidate("a", _key(tip - timedelta(hours=2))),
             MatchCandidate("b", _key(tip + timedelta(hours=3)))]
    assert match_event(_key(tip), cands).status is MatchStatus.AMBIGUOUS


# --- the matcher: repeat matchups against the database -----------------------


def _rows_for(session, pair, start):
    lo, hi = start - timedelta(days=5), start + timedelta(days=5)
    rows = session.execute(
        select(Event).where(Event.scheduled_start >= lo, Event.scheduled_start <= hi)
    ).scalars().all()
    return [e for e in rows if {e.home_team, e.away_team} == pair]


def test_back_to_back_lands_on_two_rows_each_dual_keyed(db_session):
    """Both games, both sources, Kalshi first then Odds API: two rows, and each
    Odds id ends up on its own game."""
    tip1 = _future_tip()
    tip2 = tip1 + timedelta(days=1)
    pair = {"Boston Celtics", "Philadelphia 76ers"}

    ingest_event(db_session, _kalshi_nba_event(BOS, PHI, tip1), NBA_KALSHI)
    ingest_event(db_session, _kalshi_nba_event(PHI, BOS, tip2), NBA_KALSHI)
    db_session.flush()
    ingest_odds_event(db_session, _odds_event("nba-g1", SIXERS, CELTICS, tip1), NBA_ODDS)
    ingest_odds_event(db_session, _odds_event("nba-g2", CELTICS, SIXERS, tip2), NBA_ODDS)
    db_session.flush()

    rows = sorted(_rows_for(db_session, pair, tip1), key=lambda e: e.scheduled_start)
    assert len(rows) == 2
    assert [r.odds_api_event_id for r in rows] == ["nba-g1", "nba-g2"]
    assert all(r.kalshi_event_ticker for r in rows)
    assert [r.home_team for r in rows] == ["Philadelphia 76ers", "Boston Celtics"]


def test_back_to_back_odds_first_then_kalshi(db_session):
    """Reverse poll order — Odds API creates both rows, Kalshi claims each."""
    tip1 = _future_tip(day=15)
    tip2 = tip1 + timedelta(days=1)
    pair = {"Boston Celtics", "Philadelphia 76ers"}

    ingest_odds_event(db_session, _odds_event("nba-r1", SIXERS, CELTICS, tip1), NBA_ODDS)
    ingest_odds_event(db_session, _odds_event("nba-r2", CELTICS, SIXERS, tip2), NBA_ODDS)
    db_session.flush()
    ingest_event(db_session, _kalshi_nba_event(BOS, PHI, tip1), NBA_KALSHI)
    ingest_event(db_session, _kalshi_nba_event(PHI, BOS, tip2), NBA_KALSHI)
    db_session.flush()

    rows = sorted(_rows_for(db_session, pair, tip1), key=lambda e: e.scheduled_start)
    assert len(rows) == 2
    assert [r.odds_api_event_id for r in rows] == ["nba-r1", "nba-r2"]
    assert rows[0].kalshi_event_ticker != rows[1].kalshi_event_ticker
    assert all(r.kalshi_event_ticker for r in rows)


def test_kalshi_never_merges_into_a_row_holding_another_ticker(db_session):
    """The claimed-row rule, shown under NFL's wide window where it is what
    stops the merge: a row already keyed to a different Kalshi ticker is a
    different game, however near."""
    start = datetime(2099, 9, 14, tzinfo=UTC)
    first = KalshiEventMetadata(
        kalshi_event_ticker="KXNFLGAME-99SEP14DENKC", sport="nfl", league="NFL",
        home_team="Kansas City Chiefs", away_team="Denver Broncos",
        scheduled_start=start, outcome_markets={},
    )
    second = KalshiEventMetadata(
        kalshi_event_ticker="KXNFLGAME-99SEP16KCDEN", sport="nfl", league="NFL",
        home_team="Denver Broncos", away_team="Kansas City Chiefs",
        scheduled_start=start + timedelta(days=2), outcome_markets={},
    )
    id1 = upsert_event(db_session, first)
    db_session.flush()
    id2 = upsert_event(db_session, second)
    db_session.flush()
    assert id1 != id2


# --- calibration is gated per sport ------------------------------------------


def _graded_game(db, sport, league, home, away, *, days_ago):
    ev = Event(
        sport=sport, league=league, home_team=home, away_team=away,
        scheduled_start=datetime.now(UTC) - timedelta(days=days_ago),
        status="final", winner_team=home, home_score=100, away_score=90,
    )
    db.add(ev)
    db.flush()
    at = ev.scheduled_start - timedelta(hours=2)
    insert_snapshots(db, [{
        "event_id": ev.id, "source": "kalshi", "outcome": "home", "team": home,
        "implied_probability": 0.6, "price_format": "probability",
        "snapshot_time": at, "ingested_at": at,
    }])
    db.flush()
    return ev


def _n(resp):
    return resp["source_reliability"]["kalshi"]["n"]


def test_nba_and_nfl_samples_are_counted_separately(db_session):
    nfl_before = _n(performance(sport="nfl", db=db_session))
    nba_before = _n(performance(sport="nba", db=db_session))

    for i in range(3):
        _graded_game(db_session, "nfl", "NFL", "Kansas City Chiefs", "Denver Broncos",
                     days_ago=900 + i)
    _graded_game(db_session, "nba", "NBA", "Boston Celtics", "Philadelphia 76ers", days_ago=900)

    nfl = performance(sport="nfl", db=db_session)
    nba = performance(sport="nba", db=db_session)
    assert _n(nfl) == nfl_before + 3
    assert _n(nba) == nba_before + 1  # NBA neither borrows NFL's games…
    assert nfl["sport"] == "nfl" and nba["sport"] == "nba"
    assert set(nba["sports"]) >= {"nfl", "nba"}


def test_a_new_sport_starts_from_its_own_zero(db_session):
    """However large NFL's sample, NBA's gate sees only NBA games."""
    for i in range(30):  # past the 25-game reporting floor, for NFL only
        _graded_game(db_session, "nfl", "NFL", "Kansas City Chiefs", "Denver Broncos",
                     days_ago=1000 + i)
    nba = performance(sport="nba", db=db_session)
    nba_rel = nba["source_reliability"]["kalshi"]
    if nba_rel["n"] < 25:  # true unless real NBA history exists in this database
        assert nba_rel["status"] == "insufficient" and nba_rel["accuracy"] is None
    assert performance(sport="nfl", db=db_session)["source_reliability"]["kalshi"]["n"] >= 30


def test_unknown_sport_is_refused_not_pooled(db_session):
    with pytest.raises(HTTPException) as exc:
        performance(sport="all", db=db_session)
    assert exc.value.status_code == 422
