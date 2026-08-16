"""Reciprocal Kalshi-side merge + snapshot team anchoring.

Before the merge existed, correctness depended on Kalshi always polling first: an
Odds-API-created event would be duplicated the moment that ordering slipped. These
tests run the Odds API FIRST on purpose, which is the case that used to break.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from arbitrium.db.models import Event, OddsSnapshot
from arbitrium.ingestion.kalshi import (
    SERIES_CONFIG,
    KalshiEventMetadata,
    ingest_event,
    upsert_event,
)
from arbitrium.ingestion.odds_api import ODDS_SPORTS, ingest_odds_event

UTC = timezone.utc
# Synthetic '99' year in every ticker: the fixture rolls back, but it still READS
# the real committed events table, and a ticker colliding with a real one would take
# the fast path against production data instead of exercising the merge.
NFL_ODDS = ODDS_SPORTS["americanfootball_nfl"]
NFL_KALSHI = SERIES_CONFIG["KXNFLGAME"]


def _odds_event(event_id, home, away, commence):
    return {
        "id": event_id,
        "commence_time": commence,
        "home_team": home,
        "away_team": away,
        "bookmakers": [
            {"key": "draftkings", "markets": [{"key": "h2h", "outcomes": [
                {"name": home, "price": -150}, {"name": away, "price": 130}]}]},
            {"key": "fanduel", "markets": [{"key": "h2h", "outcomes": [
                {"name": home, "price": -145}, {"name": away, "price": 125}]}]},
        ],
    }


def _kalshi_meta(ticker, home, away, start):
    """Metadata as the Kalshi path builds it — home/away is PROVISIONAL here."""
    return KalshiEventMetadata(
        kalshi_event_ticker=ticker, sport="nfl", league="NFL",
        home_team=home, away_team=away, scheduled_start=start,
        outcome_markets={},
    )


def _count_events(session, pair, start):
    """Events for this matchup NEAR ``start``.

    Scoped to the test's far-future window on purpose: the real committed table
    already holds these matchups for the actual season, and an unscoped count
    would pick those up and report a duplicate that isn't one.
    """
    lo, hi = start - timedelta(days=5), start + timedelta(days=5)
    rows = session.execute(
        select(Event.home_team, Event.away_team)
        .where(Event.scheduled_start >= lo, Event.scheduled_start <= hi)
    ).all()
    return sum(1 for h, a in rows if {h, a} == pair)


def test_kalshi_merges_into_event_created_by_odds_api_first(db_session):
    start = datetime.now(UTC) + timedelta(days=420)
    pair = {"Kansas City Chiefs", "Denver Broncos"}

    # 1. Odds API polls FIRST and creates the event.
    ingest_odds_event(
        db_session,
        _odds_event("odds-1", "Kansas City Chiefs", "Denver Broncos", start.isoformat()),
        NFL_ODDS,
    )
    db_session.flush()
    assert _count_events(db_session, pair, start) == 1

    # 2. Kalshi polls second, with the REVERSED provisional home/away and a
    #    date-only kickoff — the realistic shape of a Kalshi ticker.
    meta = _kalshi_meta(
        "KXNFLGAME-99SEP14DENKC", "Denver Broncos", "Kansas City Chiefs",
        start.replace(hour=0, minute=0, second=0, microsecond=0),
    )
    event_id = upsert_event(db_session, meta)
    db_session.flush()

    assert _count_events(db_session, pair, start) == 1, "Kalshi must merge, not duplicate"
    merged = db_session.get(Event, event_id)
    assert merged.kalshi_event_ticker == meta.kalshi_event_ticker
    assert merged.odds_api_event_id == "odds-1"  # dual-keyed


def test_merge_does_not_downgrade_authoritative_home_away(db_session):
    start = datetime.now(UTC) + timedelta(days=421)
    ingest_odds_event(
        db_session,
        _odds_event("odds-2", "Buffalo Bills", "Miami Dolphins", start.isoformat()),
        NFL_ODDS,
    )
    db_session.flush()

    meta = _kalshi_meta(
        "KXNFLGAME-99SEP15MIABUF", "Miami Dolphins", "Buffalo Bills",
        start.replace(hour=0, minute=0, second=0, microsecond=0),
    )
    event_id = upsert_event(db_session, meta)
    db_session.flush()

    ev = db_session.get(Event, event_id)
    # Odds API is authoritative; Kalshi's provisional guess must not overwrite it.
    assert ev.home_team == "Buffalo Bills"
    assert ev.away_team == "Miami Dolphins"
    assert ev.home_away_source == "odds_api"
    assert ev.scheduled_start == start  # exact kickoff kept, not Kalshi's midnight


def test_known_ticker_still_takes_the_fast_path(db_session):
    start = datetime.now(UTC) + timedelta(days=422)
    meta = _kalshi_meta(
        "KXNFLGAME-99SEP16NYGDAL", "Dallas Cowboys", "New York Giants", start,
    )
    first = upsert_event(db_session, meta)
    db_session.flush()
    second = upsert_event(db_session, meta)
    db_session.flush()
    assert first == second
    assert _count_events(db_session, {"Dallas Cowboys", "New York Giants"}, start) == 1


def test_unmatched_kalshi_event_is_created_not_dropped(db_session):
    start = datetime.now(UTC) + timedelta(days=423)
    meta = _kalshi_meta(
        "KXNFLGAME-99AUG13NEIND", "Indianapolis Colts", "New England Patriots", start,
    )
    event_id = upsert_event(db_session, meta)
    db_session.flush()
    ev = db_session.get(Event, event_id)
    assert ev is not None
    assert ev.odds_api_event_id is None  # single-source, still recorded
    assert ev.home_away_source == "kalshi_provisional"


def test_kalshi_snapshots_carry_team(db_session):
    """The bug this fixes: every post-0005 Kalshi poll wrote team = NULL."""
    start = datetime.now(UTC) + timedelta(days=424)
    ev = Event(
        sport="nfl", league="NFL", home_team="Green Bay Packers",
        away_team="Chicago Bears", scheduled_start=start, status="scheduled",
    )
    db_session.add(ev)
    db_session.flush()

    kalshi_event = {
        "event_ticker": "KXNFLGAME-99SEP17CHIGB",
        "markets": [
            {"ticker": "KXNFLGAME-99SEP17CHIGB-GB", "yes_bid_dollars": "0.60",
             "yes_ask_dollars": "0.62", "custom_strike": {"football_team": None}},
            {"ticker": "KXNFLGAME-99SEP17CHIGB-CHI", "yes_bid_dollars": "0.38",
             "yes_ask_dollars": "0.40", "custom_strike": {"football_team": None}},
        ],
    }
    ingest_event(db_session, kalshi_event, NFL_KALSHI)
    db_session.flush()

    rows = db_session.execute(
        select(OddsSnapshot.outcome, OddsSnapshot.team)
        .where(OddsSnapshot.source == "kalshi", OddsSnapshot.team.isnot(None))
        .join(Event, Event.id == OddsSnapshot.event_id)
        .where(Event.kalshi_event_ticker == "KXNFLGAME-99SEP17CHIGB")
    ).all()
    assert len(rows) == 2, "both Kalshi snapshots must be team-anchored"
    assert {t for _, t in rows} == {"Green Bay Packers", "Chicago Bears"}
