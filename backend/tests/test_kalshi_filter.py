"""Tests for Kalshi series config, event-metadata extraction, and run_ingest guards."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from marketedge.ingestion.kalshi import (
    SERIES_CONFIG,
    KalshiClient,
    _parse_event_ticker,
    extract_event_metadata,
    run_ingest,
)


# ---------------------------------------------------------------------------
# Series config
# ---------------------------------------------------------------------------


def test_nfl_nba_declared_binary_two_outcomes():
    for series in ("KXNFLGAME", "KXNBAGAME"):
        cfg = SERIES_CONFIG[series]
        assert cfg.outcome_count == 2 and cfg.has_draw is False


def test_soccer_declared_three_way_with_draw():
    for series in ("KXMLSGAME", "KXLALIGAGAME"):
        cfg = SERIES_CONFIG[series]
        assert cfg.outcome_count == 3 and cfg.has_draw is True


# ---------------------------------------------------------------------------
# Event-ticker parsing
# ---------------------------------------------------------------------------


def test_parse_event_ticker_date_and_matchup():
    parsed = _parse_event_ticker("KXNFLGAME-26SEP14DENKC")
    assert parsed is not None
    game_date, matchup = parsed
    assert game_date == datetime(2026, 9, 14, tzinfo=timezone.utc)
    assert matchup == "DENKC"


@pytest.mark.parametrize("bad", ["", "NODASH", "KXNFLGAME-XXYYZZ", "KXNFLGAME-26ZZZ14DENKC"])
def test_parse_event_ticker_rejects_bad(bad):
    assert _parse_event_ticker(bad) is None


# ---------------------------------------------------------------------------
# Event-metadata extraction (real NFL payload shape)
# ---------------------------------------------------------------------------


def _nfl_event():
    return {
        "event_ticker": "KXNFLGAME-26SEP14DENKC",
        "markets": [
            {"ticker": "KXNFLGAME-26SEP14DENKC-KC",
             "custom_strike": {"football_team": "64f72720-2e4a-4cc8-a39b-ca148aecb389"},
             "yes_bid_dollars": "0.57", "yes_ask_dollars": "0.59", "volume_fp": "3123.22"},
            {"ticker": "KXNFLGAME-26SEP14DENKC-DEN",
             "custom_strike": {"football_team": "0aa02fd7-1bb1-474b-98e1-5379d0a191e3"},
             "yes_bid_dollars": "0.41", "yes_ask_dollars": "0.43", "volume_fp": "1707.71"},
        ],
    }


def test_extract_event_metadata_resolves_teams_and_provisional_home_away():
    meta = extract_event_metadata(_nfl_event(), SERIES_CONFIG["KXNFLGAME"])
    assert meta is not None
    assert meta.kalshi_event_ticker == "KXNFLGAME-26SEP14DENKC"
    assert (meta.sport, meta.league) == ("nfl", "NFL")
    # Matchup "DENKC": DEN first => provisional away; KC second => provisional home.
    assert meta.away_team == "Denver Broncos"
    assert meta.home_team == "Kansas City Chiefs"
    assert meta.scheduled_start == datetime(2026, 9, 14, tzinfo=timezone.utc)
    assert meta.home_away_source == "kalshi_provisional"
    assert set(meta.outcome_markets) == {"home", "away"}
    assert meta.outcome_markets["home"]["ticker"].endswith("-KC")
    assert meta.outcome_markets["away"]["ticker"].endswith("-DEN")


def test_extract_event_metadata_skips_on_uuid_mismatch():
    ev = _nfl_event()
    ev["markets"][0]["custom_strike"]["football_team"] = "wrong-uuid"
    assert extract_event_metadata(ev, SERIES_CONFIG["KXNFLGAME"]) is None


def test_extract_event_metadata_skips_unknown_team_code():
    ev = _nfl_event()
    ev["markets"][0]["ticker"] = "KXNFLGAME-26SEP14DENKC-ZZZ"
    ev["markets"][0]["custom_strike"] = {}
    assert extract_event_metadata(ev, SERIES_CONFIG["KXNFLGAME"]) is None


# ---------------------------------------------------------------------------
# run_ingest guards
# ---------------------------------------------------------------------------


def test_run_ingest_raises_on_undeclared_series():
    with pytest.raises(ValueError, match="Undeclared Kalshi series"):
        run_ingest(series_tickers=["KXTOTALLYUNKNOWNSERIES"])


def test_run_ingest_zero_events_noops(monkeypatch):
    # A dormant/off-season series returns no events. Graceful no-op (0 rows),
    # touching neither the DB (nothing queued) nor the network beyond the mock.
    monkeypatch.setattr(KalshiClient, "get_events", lambda self, **kwargs: [])
    result = run_ingest(series_tickers=["KXNFLGAME"])
    assert result.rows_attempted == 0
    assert result.rows_written == 0
    assert result.events_seen == 0
