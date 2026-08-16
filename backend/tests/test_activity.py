"""/activity — recent real price movement across the feed.

Exists because the ticker and the "biggest mover" rail cannot be answered by
/divergences (no change timestamps) or /events/{id}/history (one event per
request) without N round trips.

Every row it returns is a genuine move: the dedup trigger only admits a snapshot
when the price actually changed, so these tests assert the endpoint reports what
was observed and never manufactures an event.

``db_session`` rolls back but does not hide existing rows, so every assertion
here is scoped to the event the test created rather than to global counts.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from arbitrium.api.main import activity
from arbitrium.db.models import Event, OddsSnapshot

UNIQUE_HOME = "Test Isolation Chiefs"


def _event(db_session, home=UNIQUE_HOME, away="Test Isolation Broncos"):
    ev = Event(
        sport="nfl", league="NFL", home_team=home, away_team=away,
        scheduled_start=datetime.now(UTC) + timedelta(days=3), status="scheduled",
    )
    db_session.add(ev)
    db_session.flush()
    return ev


def _snap(db_session, ev, prob, minutes_ago, source="kalshi", team=None):
    at = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    db_session.add(
        OddsSnapshot(
            event_id=ev.id, source=source, outcome="home",
            team=team or ev.home_team, implied_probability=prob,
            price_format="kalshi", snapshot_time=at, ingested_at=at,
        )
    )
    db_session.flush()


def _mine(body, ev, key="changes"):
    return [r for r in body[key] if r["event_id"] == str(ev.id)]


def _call(db_session, hours=24, limit=200, movers_limit=25):
    return activity(hours=hours, limit=limit, movers_limit=movers_limit, db=db_session)


def test_reports_a_move_with_the_price_it_moved_from(db_session):
    # Deliberately the NEWEST rows in the window. `limit` caps the response
    # newest-first across the whole feed before any per-event filtering, and the
    # live table now carries more than 200 changes in 24h — older fixture rows
    # get cut by the limit rather than by anything this test is asserting.
    ev = _event(db_session)
    _snap(db_session, ev, 0.5000, 2)
    _snap(db_session, ev, 0.5400, 1)

    changes = _mine(_call(db_session), ev)
    assert len(changes) == 1
    assert changes[0]["from"] == 0.5
    assert changes[0]["to"] == 0.54
    assert round(changes[0]["delta"], 4) == 0.04
    assert changes[0]["home_team"] == UNIQUE_HOME


def test_a_single_observation_is_not_a_move(db_session):
    """One price is not a change. Reporting it would invent movement."""
    ev = _event(db_session)
    _snap(db_session, ev, 0.5000, 30)

    assert _mine(_call(db_session), ev) == []


def test_changes_are_newest_first(db_session):
    ev = _event(db_session)
    _snap(db_session, ev, 0.50, 300)
    _snap(db_session, ev, 0.52, 200)
    _snap(db_session, ev, 0.55, 100)

    times = [c["at"] for c in _mine(_call(db_session), ev)]
    assert times == sorted(times, reverse=True)


def test_the_window_excludes_older_movement(db_session):
    """Both sides of the boundary, on one event.

    Asserted against this event's own rows rather than by widening the window:
    ``limit`` caps the response newest-first over the WHOLE feed, so on a live
    table a deliberately-old row is cut by the limit and not by the window,
    which would make a passing 48h assertion prove nothing.
    """
    ev = _event(db_session)
    _snap(db_session, ev, 0.40, 60 * 40)  # 40h ago — outside
    _snap(db_session, ev, 0.45, 60 * 39)  # 39h ago — outside

    assert _mine(_call(db_session, hours=24), ev) == []

    _snap(db_session, ev, 0.48, 5)  # inside the window
    changes = _mine(_call(db_session, hours=24), ev)
    assert len(changes) == 1
    # It moved from the last price actually observed, even though that
    # observation is itself outside the window.
    assert changes[0]["from"] == 0.45
    assert changes[0]["to"] == 0.48


def test_a_move_at_the_window_edge_still_reports_where_it_came_from(db_session):
    """The lag runs over ALL history, not just the window.

    Otherwise the oldest change inside the window would report a null previous
    price and the ticker would show a move from nowhere.
    """
    ev = _event(db_session)
    _snap(db_session, ev, 0.30, 60 * 30)  # outside the 24h window
    _snap(db_session, ev, 0.36, 1)  # inside it, and newest so the limit keeps it

    changes = _mine(_call(db_session, hours=24), ev)
    assert len(changes) == 1
    assert changes[0]["from"] == 0.3
    assert changes[0]["to"] == 0.36


def test_movers_need_more_than_one_observation_and_carry_their_swing(db_session):
    ev = _event(db_session)
    _snap(db_session, ev, 0.40, 100)
    _snap(db_session, ev, 0.62, 50)

    movers = _mine(_call(db_session), ev, key="movers")
    assert len(movers) == 1
    assert round(movers[0]["swing"], 4) == 0.22
    assert movers[0]["changes"] == 2


def test_a_flat_series_is_not_a_mover(db_session):
    ev = _event(db_session)
    _snap(db_session, ev, 0.50, 100)

    assert _mine(_call(db_session), ev, key="movers") == []


def test_movers_ignore_consensus_so_ranking_is_not_sampling_rate(db_session):
    """Consensus polls adaptively; ranking across both would rank cadence."""
    ev = _event(db_session)
    _snap(db_session, ev, 0.10, 100, source="consensus")
    _snap(db_session, ev, 0.90, 50, source="consensus")

    assert _mine(_call(db_session), ev, key="movers") == []


def test_response_always_carries_its_shape_and_window(db_session):
    body = _call(db_session, hours=6)
    assert body["window_hours"] == 6
    assert set(body["counts"]) == {"changes", "movers"}
    assert body["counts"]["changes"] == len(body["changes"])
    assert body["counts"]["movers"] == len(body["movers"])
