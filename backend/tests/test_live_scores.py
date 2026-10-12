"""Live-scores ingestion: ESPN extraction, window gating, upsert, API payload.

The pure-extraction tests parse fixture payloads (no DB, no HTTP). The DB tests
reuse the rolled-back ``db_session`` fixture; they are container-only, like the
other DB tests in this suite.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from arbitrium.api.main import divergences, event_detail
from arbitrium.db.models import CalibrationHistory, Event, EventLiveState, OddsSnapshot
from arbitrium.ingestion import live_scores
from arbitrium.ingestion.espn import (
    LIVE_STATUS_FINAL,
    LIVE_STATUS_HALFTIME,
    LIVE_STATUS_IN_PROGRESS,
    LIVE_STATUS_POSTPONED,
    LIVE_STATUS_SCHEDULED,
    extract_live_state,
)
from arbitrium.ingestion.live_scores import (
    CADENCE_LIVE_SECONDS,
    CADENCE_SCHEDULED_SECONDS,
    UPCOMING_DAYS,
    compute_cadence_seconds,
    run_pass,
    run_upcoming_pass,
)

UTC = timezone.utc


# ---------- fixtures ---------------------------------------------------------


def _nfl_payload(status_name="STATUS_IN_PROGRESS", state="in", completed=False,
                 period=3, clock="4:12", home="Kansas City Chiefs",
                 away="Denver Broncos", home_score="21", away_score="17",
                 home_record="2-1", away_record="1-2",
                 possession_id="1", situation=True,
                 date="2026-09-14T20:00Z", espn_id="espn-nfl-1"):
    return {
        "id": espn_id,
        "date": date,
        "competitions": [{
            "status": {
                "period": period,
                "displayClock": clock,
                "type": {
                    "name": status_name,
                    "state": state,
                    "completed": completed,
                    "shortDetail": f"Q{period} {clock}",
                    "detail": f"Q{period} {clock}",
                },
            },
            "competitors": [
                {
                    "id": "1",
                    "homeAway": "home",
                    "team": {"displayName": home, "id": "12"},
                    "score": home_score,
                    "records": [{"summary": home_record}],
                    "linescores": [{"value": 7}, {"value": 7}, {"value": 7}],
                },
                {
                    "id": "2",
                    "homeAway": "away",
                    "team": {"displayName": away, "id": "7"},
                    "score": away_score,
                    "records": [{"summary": away_record}],
                    "linescores": [{"value": 7}, {"value": 10}, {"value": 0}],
                },
            ],
            "venue": {"fullName": "Arrowhead Stadium"},
            "broadcasts": [{"names": ["NBC"]}],
            "situation": {
                "possession": possession_id,
                "shortDownDistanceText": "2nd & 7",
                "lastPlay": {"text": "Mahomes pass short right for 6"},
            } if situation else {},
        }],
    }


def _nba_payload(period=4, clock="2:14", status_name="STATUS_IN_PROGRESS",
                 state="in", espn_id="espn-nba-1"):
    return {
        "id": espn_id,
        "date": "2026-10-20T23:00Z",
        "competitions": [{
            "status": {
                "period": period,
                "displayClock": clock,
                "type": {
                    "name": status_name,
                    "state": state,
                    "completed": False,
                    "shortDetail": f"Q{period} {clock}",
                },
            },
            "competitors": [
                {"id": "1", "homeAway": "home",
                 "team": {"id": "1", "displayName": "Atlanta Hawks"},
                 "score": "88", "records": [{"summary": "4-2"}],
                 "linescores": [{"value": 20}, {"value": 22}, {"value": 24}, {"value": 22}]},
                {"id": "2", "homeAway": "away",
                 "team": {"id": "2", "displayName": "Boston Celtics"},
                 "score": "90", "records": [{"summary": "5-1"}],
                 "linescores": [{"value": 24}, {"value": 22}, {"value": 20}, {"value": 24}]},
            ],
            "venue": {"fullName": "State Farm Arena"},
            "broadcasts": [{"names": ["ESPN"]}],
            "situation": {},
        }],
    }


# ---------- status mapping ---------------------------------------------------


def test_scheduled_game_maps_to_scheduled_with_no_scores():
    s = extract_live_state(
        _nfl_payload(status_name="STATUS_SCHEDULED", state="pre",
                     home_score=None, away_score=None, period=0, clock="0:00"),
        "nfl",
    )
    assert s is not None
    assert s.status == LIVE_STATUS_SCHEDULED
    assert s.home_score is None and s.away_score is None
    assert s.clock is None
    assert s.venue == "Arrowhead Stadium"
    assert s.broadcast == "NBC"
    assert s.home_record == "2-1"


def test_in_progress_game_maps_with_period_and_clock():
    s = extract_live_state(_nfl_payload(), "nfl")
    assert s is not None
    assert s.status == LIVE_STATUS_IN_PROGRESS
    assert s.period == 3 and s.clock == "4:12"
    assert s.detail == "Q3 4:12"
    assert s.home_score == 21 and s.away_score == 17


def test_halftime_maps_to_halftime_and_wipes_clock():
    s = extract_live_state(
        _nfl_payload(status_name="STATUS_HALFTIME", state="in", period=2, clock="0:00"),
        "nfl",
    )
    assert s is not None
    assert s.status == LIVE_STATUS_HALFTIME
    assert s.clock is None
    assert s.detail == "Halftime"


def test_final_game_maps_to_final():
    s = extract_live_state(
        _nfl_payload(status_name="STATUS_FINAL", state="post", completed=True,
                     period=4, clock="0:00"),
        "nfl",
    )
    assert s is not None
    assert s.status == LIVE_STATUS_FINAL


def test_postponed_maps_regardless_of_state():
    s = extract_live_state(
        _nfl_payload(status_name="STATUS_POSTPONED", state="pre",
                     home_score=None, away_score=None),
        "nfl",
    )
    assert s is not None
    assert s.status == LIVE_STATUS_POSTPONED


def test_nba_has_no_possession_or_down_distance():
    s = extract_live_state(_nba_payload(), "nba")
    assert s is not None
    assert s.possession_side is None
    assert s.down_distance is None
    assert s.linescore == {"home": [20, 22, 24, 22], "away": [24, 22, 20, 24]}


def test_nba_overtime_detail_string():
    # Period 5 is OT in the NBA; period 6 is 2OT.
    s = extract_live_state(_nba_payload(period=5, clock="3:14"), "nba")
    # ESPN's shortDetail is "Q5 3:14" in our stub, but our builder uses the
    # period label instead when the state is in_progress.
    assert s.detail == "OT 3:14"
    s2 = extract_live_state(_nba_payload(period=6, clock="1:00"), "nba")
    assert s2.detail == "2OT 1:00"


def test_nfl_possession_side_maps_from_competitor_id():
    s = extract_live_state(_nfl_payload(possession_id="2"), "nfl")
    assert s.possession_side == "away"
    s_home = extract_live_state(_nfl_payload(possession_id="1"), "nfl")
    assert s_home.possession_side == "home"


def test_nfl_down_distance_and_last_play_captured():
    s = extract_live_state(_nfl_payload(), "nfl")
    assert s.down_distance == "2nd & 7"
    assert s.last_play == "Mahomes pass short right for 6"


# ---------- window gating ----------------------------------------------------


class _StubClient:
    """Scoreboard stub that remembers how many times it was called."""

    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = payloads
        self.calls = 0

    def get_scoreboard(self, sport, date):  # noqa: ARG002
        self.calls += 1
        return self.payloads

    def close(self):
        pass


def _game(db_session, *, sport="nfl", home="Kansas City Chiefs",
          away="Denver Broncos", start, status="scheduled"):
    ev = Event(
        sport=sport, league=sport.upper(),
        home_team=home, away_team=away,
        scheduled_start=start, status=status,
    )
    db_session.add(ev)
    db_session.flush()
    return ev


def test_idle_window_makes_zero_espn_calls(db_session):
    # DB has no NFL games anywhere nearby.
    now = datetime.now(UTC)
    stub = _StubClient([_nfl_payload()])

    def _factory():
        class _Ctx:
            def __enter__(self_inner): return db_session
            def __exit__(self_inner, *exc): return False
        return _Ctx()

    result = run_pass("nfl", session_factory=_factory, client=stub, now=now)
    assert stub.calls == 0
    assert result.rows_written == 0
    assert result.events_seen == 0


def test_live_window_triggers_poll_and_upsert(db_session):
    now = datetime.now(UTC)
    ev = _game(db_session, start=now - timedelta(minutes=30))
    stub = _StubClient([_nfl_payload(date=(now - timedelta(minutes=30)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"))])

    def _factory():
        class _Ctx:
            def __enter__(self_inner): return db_session
            def __exit__(self_inner, *exc): return False
        return _Ctx()

    result = run_pass("nfl", session_factory=_factory, client=stub, now=now)
    assert stub.calls >= 1
    assert result.rows_written == 1
    row = db_session.get(EventLiveState, ev.id)
    assert row is not None
    assert row.status == LIVE_STATUS_IN_PROGRESS


def test_cadence_live_vs_scheduled_vs_idle(db_session):
    now = datetime.now(UTC)
    # No games -> idle (returns None).
    assert compute_cadence_seconds(db_session, "nfl", now=now) is None

    # Scheduled in 6 hours -> scheduled cadence.
    _game(db_session, start=now + timedelta(hours=6))
    assert compute_cadence_seconds(db_session, "nfl", now=now) == CADENCE_SCHEDULED_SECONDS

    # Scheduled in 5 minutes -> live cadence (pre-kickoff window).
    _game(db_session, home="San Francisco 49ers", away="Seattle Seahawks",
          start=now + timedelta(minutes=5))
    assert compute_cadence_seconds(db_session, "nfl", now=now) == CADENCE_LIVE_SECONDS


def test_upsert_is_idempotent(db_session):
    now = datetime.now(UTC)
    ev = _game(db_session, start=now - timedelta(minutes=10))
    payload_date = (now - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    stub = _StubClient([_nfl_payload(date=payload_date)])

    def _factory():
        class _Ctx:
            def __enter__(self_inner): return db_session
            def __exit__(self_inner, *exc): return False
        return _Ctx()

    run_pass("nfl", session_factory=_factory, client=stub, now=now)
    run_pass("nfl", session_factory=_factory, client=stub, now=now)
    from sqlalchemy import select as _select
    rows = db_session.execute(_select(EventLiveState)).scalars().all()
    assert len(rows) == 1


def test_unmatched_espn_game_is_skipped_and_logged(db_session, caplog):
    now = datetime.now(UTC)
    # One event in DB but a different matchup to force an unmatched ESPN event
    _game(db_session, start=now - timedelta(minutes=10))
    other_payload = _nfl_payload(
        home="Buffalo Bills", away="Miami Dolphins",
        date=(now - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        espn_id="espn-nfl-other",
    )
    stub = _StubClient([other_payload])

    def _factory():
        class _Ctx:
            def __enter__(self_inner): return db_session
            def __exit__(self_inner, *exc): return False
        return _Ctx()

    import logging
    caplog.set_level(logging.WARNING, logger="arbitrium.ingestion.live_scores")
    result = run_pass("nfl", session_factory=_factory, client=stub, now=now)
    # The in-DB game created a live window, so ESPN was called...
    assert stub.calls >= 1
    # ...but ESPN returned a different pair that could not match our DB row.
    assert result.rows_written == 0
    assert any("no matching event row" in m for m in caplog.messages)


# ---------- upcoming games ---------------------------------------------------

# Far from any real fixture in the dev database, so matching sees only ours.
FUTURE = datetime(2031, 10, 12, 16, 0, tzinfo=UTC)


def _session(db_session):
    class _Ctx:
        def __enter__(self_inner): return db_session
        def __exit__(self_inner, *exc): return False
    return lambda: _Ctx()


def _scheduled_payload(*, start, home, away, espn_id, broadcast="Prime Video"):
    p = _nfl_payload(status_name="STATUS_SCHEDULED", state="pre",
                     home=home, away=away, home_score=None, away_score=None,
                     home_record="3-2", away_record="4-1",
                     period=0, clock="0:00", situation=False,
                     date=start.strftime("%Y-%m-%dT%H:%MZ"), espn_id=espn_id)
    p["competitions"][0]["venue"] = {"fullName": "Empower Field at Mile High"}
    p["competitions"][0]["broadcasts"] = [{"names": [broadcast]}]
    for c in p["competitions"][0]["competitors"]:
        c["linescores"] = []
    return p


def test_upcoming_pass_writes_scheduled_rows_days_out(db_session):
    start = FUTURE + timedelta(days=4, hours=8)
    ev = _game(db_session, home="Denver Broncos", away="Seattle Seahawks", start=start)
    stub = _StubClient([_scheduled_payload(
        start=start, home="Denver Broncos", away="Seattle Seahawks", espn_id="up-1")])

    result = run_upcoming_pass("nfl", session_factory=_session(db_session),
                               client=stub, now=FUTURE)

    # Today plus seven days, one call per date.
    assert stub.calls == UPCOMING_DAYS + 1
    assert result.rows_written == 1
    row = db_session.get(EventLiveState, ev.id)
    assert row.status == LIVE_STATUS_SCHEDULED
    assert (row.away_record, row.home_record) == ("4-1", "3-2")
    assert row.venue == "Empower Field at Mile High"
    assert row.broadcast == "Prime Video"
    assert row.home_score is None and row.linescore is None


def test_upcoming_pass_never_touches_live_rows(db_session):
    live_start = FUTURE - timedelta(hours=1)
    live_ev = _game(db_session, home="San Francisco 49ers", away="Seattle Seahawks",
                    start=live_start)
    db_session.add(EventLiveState(
        event_id=live_ev.id, status=LIVE_STATUS_IN_PROGRESS, period=2, clock="3:00",
        home_score=14, away_score=7, broadcast="FOX",
    ))
    later = FUTURE + timedelta(days=2)
    _game(db_session, home="Kansas City Chiefs", away="Denver Broncos", start=later)
    db_session.flush()

    stub = _StubClient([
        # ESPN's live view of the in-progress game: not ours to write.
        _nfl_payload(home="San Francisco 49ers", away="Seattle Seahawks",
                     date=live_start.strftime("%Y-%m-%dT%H:%MZ"), espn_id="live-1"),
        # A stale "scheduled" read of the same game must not roll it back either.
        _scheduled_payload(start=live_start, home="San Francisco 49ers",
                           away="Seattle Seahawks", espn_id="live-1-stale",
                           broadcast="CBS"),
        _scheduled_payload(start=later, home="Kansas City Chiefs",
                           away="Denver Broncos", espn_id="up-2"),
    ])

    result = run_upcoming_pass("nfl", session_factory=_session(db_session),
                               client=stub, now=FUTURE)

    assert result.rows_written == 1
    db_session.expire_all()
    row = db_session.get(EventLiveState, live_ev.id)
    assert row.status == LIVE_STATUS_IN_PROGRESS
    assert (row.home_score, row.away_score) == (14, 7)
    assert row.broadcast == "FOX"


def test_upcoming_pass_makes_zero_calls_with_no_games_ahead(db_session):
    stub = _StubClient([])
    result = run_upcoming_pass("nfl", session_factory=_session(db_session),
                               client=stub, now=FUTURE)
    assert stub.calls == 0
    assert result.rows_written == 0


# ---------- pick_result in the API payload -----------------------------------


def _priced(db_session, *, status="scheduled", start=None, winner_team=None, home_score=None,
            away_score=None, resolved=False):
    start = start or datetime.now(UTC) + timedelta(days=400)
    ev = Event(
        sport="nfl", league="NFL",
        home_team="Kansas City Chiefs", away_team="Denver Broncos",
        scheduled_start=start, status=status,
        winner_team=winner_team, home_score=home_score, away_score=away_score,
        resolved_at=start if resolved else None,
    )
    db_session.add(ev)
    db_session.flush()
    t = start - timedelta(days=1)
    for src, pricing in (
        ("kalshi", (0.6, 0.4)),
        ("consensus", (0.5, 0.5)),
    ):
        for team, prob in zip((ev.home_team, ev.away_team), pricing):
            db_session.add(OddsSnapshot(
                event_id=ev.id, source=src,
                outcome="home" if team == ev.home_team else "away",
                team=team, implied_probability=prob,
                price_format="probability", snapshot_time=t, ingested_at=t,
            ))
    return ev


def _add_pick(db_session, ev, subject_team, side="yes"):
    db_session.add(CalibrationHistory(
        event_id=ev.id,
        divergence_score=0.1, predicted_prob=0.6, confidence_band="moderate",
        origin="live", subject_team=subject_team, side=side,
        flagged_at=ev.scheduled_start - timedelta(days=1),
    ))
    db_session.flush()


def test_pick_result_is_null_until_final(db_session):
    ev = _priced(db_session, start=datetime.now(UTC) - timedelta(days=1))
    _add_pick(db_session, ev, "Kansas City Chiefs")
    out = event_detail(ev.id, db=db_session)
    assert out["event"]["pick_result"] is None


def test_pick_result_hit_when_subject_matches_winner(db_session):
    start = datetime.now(UTC) - timedelta(days=1)
    ev = _priced(db_session, status="final", start=start,
                 winner_team="Kansas City Chiefs",
                 home_score=27, away_score=20, resolved=True)
    _add_pick(db_session, ev, "Kansas City Chiefs")
    out = event_detail(ev.id, db=db_session)
    assert out["event"]["pick_result"] == "hit"


def test_pick_result_miss_when_subject_lost(db_session):
    start = datetime.now(UTC) - timedelta(days=1)
    ev = _priced(db_session, status="final", start=start,
                 winner_team="Denver Broncos",
                 home_score=20, away_score=27, resolved=True)
    _add_pick(db_session, ev, "Kansas City Chiefs")
    out = event_detail(ev.id, db=db_session)
    assert out["event"]["pick_result"] == "miss"


def test_live_payload_present_on_event_detail(db_session):
    start = datetime.now(UTC) + timedelta(days=1)
    ev = _priced(db_session, start=start)
    db_session.add(EventLiveState(
        event_id=ev.id, status=LIVE_STATUS_SCHEDULED,
        venue="Arrowhead Stadium", broadcast="NBC",
        home_record="2-1", away_record="1-2",
    ))
    db_session.flush()
    out = event_detail(ev.id, db=db_session)
    live = out["event"]["live"]
    assert live is not None
    assert live["status"] == LIVE_STATUS_SCHEDULED
    assert live["venue"] == "Arrowhead Stadium"
    assert live["broadcast"] == "NBC"


def test_live_payload_null_when_no_state(db_session):
    ev = _priced(db_session, start=datetime.now(UTC) + timedelta(days=1))
    out = event_detail(ev.id, db=db_session)
    assert out["event"]["live"] is None
    # The divergence block mirrors the shape so the client type is stable.
    if out["divergence"] is not None:
        assert out["divergence"]["live"] is None
        assert out["divergence"]["pick_result"] is None
