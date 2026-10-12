"""Finished games on /divergences, and the side-aware pick result behind them.

Container-only DB tests on the rolled-back ``db_session``. The dev database
holds real finals too, so every assertion looks up this test's own event id
rather than counting the list.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from arbitrium.api.main import divergences, event_detail
from arbitrium.calibration.grading import backfill_sides
from arbitrium.db.models import CalibrationHistory, Event, EventLiveState, OddsSnapshot

UTC = timezone.utc
HOME, AWAY = "Kansas City Chiefs", "Denver Broncos"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Finished games come from stored rows: any HTTP call at all fails the test."""
    def _refuse(*_a, **_k):
        raise AssertionError("unexpected HTTP call")
    monkeypatch.setattr(httpx.Client, "send", _refuse)


def _event(db, *, start, status="final", home_score=None, away_score=None, winner=None):
    ev = Event(
        sport="nfl", league="NFL", home_team=HOME, away_team=AWAY,
        scheduled_start=start, status=status,
        home_score=home_score, away_score=away_score, winner_team=winner,
    )
    db.add(ev)
    db.flush()
    return ev


def _pick(db, ev, *, team=HOME, side="yes", price=0.54, fair=0.61):
    db.add(CalibrationHistory(
        event_id=ev.id, divergence_score=abs(fair - price), predicted_prob=fair,
        confidence_band="moderate", origin="live", subject_team=team, side=side,
        entry_prob=price, flagged_at=ev.scheduled_start - timedelta(hours=6),
    ))
    db.flush()


def _feed(db, **kw):
    params = dict(sport=None, status=None, min_divergence=None,
                  tradeable_only=False, limit=200, db=db)
    params.update(kw)
    return divergences(**params)


def _final(feed, ev):
    return next((f for f in feed["recent_finals"] if f["event_id"] == str(ev.id)), None)


# ---------- side-aware pick result -------------------------------------------


@pytest.mark.parametrize("side,winner,expected", [
    ("yes", HOME, "hit"),
    ("yes", AWAY, "miss"),
    # Buy No on the Chiefs is a call that the Chiefs lose.
    ("no", AWAY, "hit"),
    ("no", HOME, "miss"),
])
def test_pick_result_reads_the_side(db_session, side, winner, expected):
    h, a = (27, 20) if winner == HOME else (20, 27)
    ev = _event(db_session, start=datetime.now(UTC) - timedelta(days=1),
                home_score=h, away_score=a, winner=winner)
    _pick(db_session, ev, side=side)
    assert event_detail(ev.id, db=db_session)["event"]["pick_result"] == expected


def test_pick_result_is_null_when_the_side_was_never_recorded(db_session):
    ev = _event(db_session, start=datetime.now(UTC) - timedelta(days=1),
                home_score=27, away_score=20, winner=HOME)
    _pick(db_session, ev, side=None)
    out = event_detail(ev.id, db=db_session)
    assert out["event"]["pick_result"] is None
    assert out["event"]["flagged"] is None


# ---------- recent_finals ----------------------------------------------------


def test_recent_final_carries_the_flagged_snapshot(db_session):
    ev = _event(db_session, start=datetime.now(UTC) - timedelta(days=2),
                home_score=15, away_score=23, winner=AWAY)
    _pick(db_session, ev, side="no", price=0.54, fair=0.61)

    feed = _feed(db_session)
    final = _final(feed, ev)
    assert final is not None
    assert (final["home_score"], final["away_score"], final["winner_team"]) == (15, 23, AWAY)
    assert final["pick_result"] == "hit"
    assert final["flagged"]["team"] == HOME
    assert final["flagged"]["side"] == "no"
    assert final["flagged"]["price"] == pytest.approx(0.54)
    assert final["flagged"]["fair_value"] == pytest.approx(0.61)
    assert all(d["event_id"] != str(ev.id) for d in feed["divergences"])


def test_final_without_a_pick_still_reports_its_score(db_session):
    ev = _event(db_session, start=datetime.now(UTC) - timedelta(days=1),
                home_score=31, away_score=7, winner=HOME)
    final = _final(_feed(db_session), ev)
    assert (final["home_score"], final["away_score"]) == (31, 7)
    assert final["pick_result"] is None
    assert final["flagged"] is None


def test_recent_finals_stop_at_seven_days_and_run_newest_first(db_session):
    now = datetime.now(UTC)
    older = _event(db_session, start=now - timedelta(days=6), home_score=1, away_score=0, winner=HOME)
    newer = _event(db_session, start=now - timedelta(days=1), home_score=1, away_score=0, winner=HOME)
    stale = _event(db_session, start=now - timedelta(days=8), home_score=1, away_score=0, winner=HOME)

    finals = _feed(db_session)["recent_finals"]
    ids = [f["event_id"] for f in finals]
    assert str(stale.id) not in ids
    assert ids.index(str(newer.id)) < ids.index(str(older.id))
    starts = [f["scheduled_start"] for f in finals]
    assert starts == sorted(starts, reverse=True)


def test_espn_final_leaves_the_feed_before_resolution_runs(db_session):
    ev = _event(db_session, start=datetime.now(UTC) - timedelta(hours=4), status="scheduled")
    db_session.add(EventLiveState(event_id=ev.id, status="final", home_score=17, away_score=24))
    t = ev.scheduled_start - timedelta(hours=1)
    for team, p in ((HOME, 0.5), (AWAY, 0.5)):
        for src in ("kalshi", "consensus"):
            db_session.add(OddsSnapshot(
                event_id=ev.id, source=src, outcome="home" if team == HOME else "away",
                team=team, implied_probability=p, price_format="probability",
                snapshot_time=t, ingested_at=t,
            ))
    _pick(db_session, ev, team=HOME, side="yes")

    feed = _feed(db_session)
    assert all(d["event_id"] != str(ev.id) for d in feed["divergences"])
    final = _final(feed, ev)
    assert (final["home_score"], final["away_score"], final["winner_team"]) == (17, 24, AWAY)
    assert final["pick_result"] == "miss"


def test_a_scored_filter_returns_no_finals(db_session):
    _event(db_session, start=datetime.now(UTC) - timedelta(days=1),
           home_score=1, away_score=0, winner=HOME)
    assert _feed(db_session, tradeable_only=True)["recent_finals"] == []


# ---------- side backfill ----------------------------------------------------


def _book(db, ev, t):
    """Kalshi and consensus as of ``t``: the best buy is No on the Chiefs at 42c."""
    quotes = {
        ("kalshi", HOME): (0.59, {"yes_bid": 0.58, "yes_ask": 0.60}),
        ("kalshi", AWAY): (0.43, {"yes_bid": 0.40, "yes_ask": 0.45}),
        ("consensus", HOME): (0.50, {"n_books": 6}),
        ("consensus", AWAY): (0.50, {"n_books": 6}),
    }
    for (src, team), (p, depth) in quotes.items():
        db.add(OddsSnapshot(
            event_id=ev.id, source=src, outcome="home" if team == HOME else "away",
            team=team, implied_probability=p, price_format="probability",
            order_book_depth=depth, snapshot_time=t, ingested_at=t,
        ))
    db.flush()


def test_backfill_recovers_the_side_by_replaying_the_call(db_session):
    ev = _event(db_session, start=datetime.now(UTC) - timedelta(days=1),
                home_score=20, away_score=27, winner=AWAY)
    _book(db_session, ev, ev.scheduled_start - timedelta(hours=7))
    _pick(db_session, ev, team=HOME, side=None, price=0.42, fair=0.50)

    assert backfill_sides(db_session) >= 1
    row = db_session.query(CalibrationHistory).filter_by(event_id=ev.id).one()
    assert row.side == "no"


def test_backfill_leaves_a_row_it_cannot_reproduce(db_session):
    ev = _event(db_session, start=datetime.now(UTC) - timedelta(days=1),
                home_score=20, away_score=27, winner=AWAY)
    _book(db_session, ev, ev.scheduled_start - timedelta(hours=7))
    # Stored price does not match what the replay finds.
    _pick(db_session, ev, team=HOME, side=None, price=0.30, fair=0.50)

    backfill_sides(db_session)
    row = db_session.query(CalibrationHistory).filter_by(event_id=ev.id).one()
    assert row.side is None
