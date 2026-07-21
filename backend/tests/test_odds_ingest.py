"""Odds API ingestion: extraction skip, dual-key merge, single-source creation.

The DB tests use the rolled-back ``db_session`` fixture and far-future dates so
they never collide with (or pollute) the real committed events.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from marketedge.db.models import Event, OddsSnapshot
from marketedge.ingestion.odds_api import (
    ODDS_SPORTS,
    extract_odds_event,
    ingest_odds_event,
)

UTC = timezone.utc
NFL = ODDS_SPORTS["americanfootball_nfl"]


def _odds_event(event_id, home, away, commence, books=None):
    return {
        "id": event_id,
        "commence_time": commence,
        "home_team": home,
        "away_team": away,
        "bookmakers": books if books is not None else [
            {"key": "draftkings", "markets": [{"key": "h2h", "outcomes": [
                {"name": home, "price": -150}, {"name": away, "price": 130}]}]},
            {"key": "fanduel", "markets": [{"key": "h2h", "outcomes": [
                {"name": home, "price": -145}, {"name": away, "price": 125}]}]},
        ],
    }


# --- #4 name-mismatch skip (pure) -------------------------------------------


def test_extract_skips_unresolved_team_name():
    ev = _odds_event("x", "Kansas City Chiefs", "London Monarchs", "2026-09-14T17:00:00Z")
    assert extract_odds_event(ev, NFL) is None


def test_extract_skips_unparseable_commence_time():
    ev = _odds_event("x", "Kansas City Chiefs", "Denver Broncos", "not-a-date")
    assert extract_odds_event(ev, NFL) is None


def test_extract_resolves_and_builds_consensus():
    ev = _odds_event("x", "Kansas City Chiefs", "Denver Broncos", "2026-09-14T17:00:00Z")
    out = extract_odds_event(ev, NFL)
    assert out is not None
    assert out.key.team_pair == {"Kansas City Chiefs", "Denver Broncos"}
    assert {s.outcome for s in out.snapshots} == {"home", "away"}


# --- #6 dual-key merge (DB) --------------------------------------------------


def test_dual_key_merge_enriches_existing_kalshi_event(db_session):
    # Pre-existing provisional Kalshi event with home/away DELIBERATELY reversed,
    # far in the future so it can't collide with the real committed events.
    kalshi_ev = Event(
        sport="nfl", league="NFL",
        home_team="Denver Broncos", away_team="Kansas City Chiefs",  # provisional (wrong)
        scheduled_start=datetime(2027, 1, 15, tzinfo=UTC), status="scheduled",
        kalshi_event_ticker="TEST-DUALKEY-DENKC", home_away_source="kalshi_provisional",
    )
    db_session.add(kalshi_ev)
    db_session.flush()

    # Odds API: authoritative KC home, kickoff ~1 day later (within window).
    odds = _odds_event("odds-dualkey-1", "Kansas City Chiefs", "Denver Broncos",
                       "2027-01-16T00:15:00Z")
    rows = ingest_odds_event(db_session, odds, NFL)
    db_session.flush()
    # Enrich is a Core UPDATE; drop identity-map caches so reads reload from DB.
    db_session.expire_all()

    assert rows == 2
    # Same single row now carries BOTH keys + AUTHORITATIVE home/away (flipped).
    merged = db_session.get(Event, kalshi_ev.id)
    assert merged.odds_api_event_id == "odds-dualkey-1"
    assert merged.home_away_source == "odds_api"
    assert merged.home_team == "Kansas City Chiefs"
    assert merged.away_team == "Denver Broncos"

    # No duplicate event created for this odds id.
    ids = db_session.execute(
        select(Event.id).where(Event.odds_api_event_id == "odds-dualkey-1")
    ).scalars().all()
    assert ids == [kalshi_ev.id]

    # Consensus snapshots anchored to team (not home/away).
    snaps = db_session.execute(
        select(OddsSnapshot).where(
            OddsSnapshot.event_id == kalshi_ev.id, OddsSnapshot.source == "consensus"
        )
    ).scalars().all()
    assert {s.team for s in snaps} == {"Kansas City Chiefs", "Denver Broncos"}


def test_unmatched_creates_single_source_odds_only_event(db_session):
    # A game no Kalshi event covers (far-future date, distinct pair) -> odds-only
    # event, never dropped.
    odds = _odds_event("odds-only-1", "Buffalo Bills", "Miami Dolphins",
                       "2027-02-20T18:00:00Z")
    rows = ingest_odds_event(db_session, odds, NFL)
    db_session.flush()

    assert rows == 2
    row = db_session.execute(
        select(Event).where(Event.odds_api_event_id == "odds-only-1")
    ).scalar_one()
    assert row.kalshi_event_ticker is None  # single-source
    assert row.home_away_source == "odds_api"
    assert row.home_team == "Buffalo Bills"
