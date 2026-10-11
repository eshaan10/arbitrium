"""The game-clock plan: per-sport config, checkpoints, coalescing, and the Kalshi gate.

One /odds call prices every game in a sport, so the plan's job is to land in
every checkpoint window with as few calls as possible — and to spend nothing on
a sport Kalshi is not trading, or on a checkpoint already taken.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from arbitrium.config import Settings, settings
from arbitrium.db.models import Event, IngestRun, OddsCheckpoint
from arbitrium.ingestion import odds_schedule
from arbitrium.ingestion.odds_api import ODDS_SPORTS
from arbitrium.ingestion.odds_schedule import EventsCache, build_plan
from arbitrium.ingestion.polling import (
    CHECKPOINT_CLOSE,
    CHECKPOINT_T1H,
    CHECKPOINT_T6H,
    CHECKPOINT_T24H,
    CHECKPOINTS,
    MISSED_GRACE,
    SPORT_SEASONS,
    GameSlot,
    SeasonWindow,
    active_sports,
    plan_passes,
    sport_polling,
)

UTC = timezone.utc
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


def _game(start, *, sport="nba", key="basketball_nba", liquidity=10_000.0, event_id=None):
    return GameSlot(event_id or uuid.uuid4(), sport, key, start, liquidity)


def _covered(passes):
    return [(g.event_id, c.name) for p in passes for g, c in p.covers]


# --- checkpoints -------------------------------------------------------------


def test_checkpoints_are_the_four_named_offsets_in_order():
    assert [c.name for c in CHECKPOINTS] == ["t24h", "t6h", "t1h", "close"]
    assert [c.offset for c in CHECKPOINTS] == [
        timedelta(hours=24), timedelta(hours=6), timedelta(hours=1), timedelta(minutes=10)
    ]
    assert [c.rank for c in CHECKPOINTS] == sorted(c.rank for c in CHECKPOINTS)


def test_every_window_closes_before_the_game_starts():
    """A price taken in play is not a pre-game checkpoint, least of all the close."""
    start = NOW + timedelta(days=2)
    for cp in CHECKPOINTS:
        opens, closes = cp.window(start)
        assert opens < closes < start


def test_windows_do_not_overlap():
    """Otherwise one call could claim two checkpoints of the same game."""
    start = NOW + timedelta(days=2)
    spans = sorted(cp.window(start) for cp in CHECKPOINTS)
    assert all(a[1] < b[0] for a, b in zip(spans, spans[1:], strict=False))


def test_one_game_gets_four_passes_ending_with_the_close():
    game = _game(NOW + timedelta(days=2))
    passes = plan_passes([game], set(), now=NOW)
    assert [p.top_checkpoint for p in passes] == list(CHECKPOINTS)
    assert passes[-1].has_close
    for p in passes:
        assert p.at == p.top_checkpoint.window(game.start)[1]  # stabbed at the window's end
    assert passes[-1].at == game.start - timedelta(minutes=6)


# --- coalescing ----------------------------------------------------------------


def test_one_slate_costs_one_call_per_checkpoint():
    """Eight 1pm kickoffs plus a 1:05: still four calls, not thirty-six."""
    start = NOW + timedelta(days=2)
    games = [_game(start, sport="nfl", key="americanfootball_nfl") for _ in range(8)]
    games.append(_game(start + timedelta(minutes=5), sport="nfl", key="americanfootball_nfl"))
    passes = plan_passes(games, set(), now=NOW)
    assert len(passes) == 4
    expected = [(g.event_id, c.name) for g in games for c in CHECKPOINTS]
    assert sorted(_covered(passes)) == sorted(expected)


def test_tip_times_far_apart_get_their_own_closes():
    early = _game(NOW + timedelta(days=1, hours=11))
    late = _game(NOW + timedelta(days=1, hours=14, minutes=30))
    closes = [p for p in plan_passes([early, late], set(), now=NOW) if p.has_close]
    assert len(closes) == 2


def test_an_nba_night_coalesces_and_covers_every_checkpoint_exactly_once():
    base = datetime(2026, 11, 3, 23, 0, tzinfo=UTC)
    tips = [0, 30, 60, 90, 120, 180, 210, 240]
    games = [_game(base + timedelta(minutes=t)) for t in tips for _ in range(2)]
    passes = plan_passes(games, set(), now=base - timedelta(days=2))
    covered = _covered(passes)
    assert len(covered) == len(set(covered)) == len(games) * 4
    assert len(passes) < len(tips) * 4  # fewer calls than one per tip time per checkpoint


def test_sports_are_planned_separately():
    """One call prices one sport, so a shared moment is still two calls."""
    start = NOW + timedelta(days=2)
    passes = plan_passes(
        [_game(start), _game(start, sport="nhl", key="icehockey_nhl")], set(), now=NOW
    )
    assert len(passes) == 8
    assert all(len({g.sport for g, _ in p.covers}) == 1 for p in passes)


def test_a_pass_costs_one_credit_per_key_it_needs():
    start = NOW + timedelta(days=2)
    passes = plan_passes(
        [_game(start), _game(start, key="basketball_nba_preseason")], set(), now=NOW
    )
    assert passes[0].sport_keys == ["basketball_nba", "basketball_nba_preseason"]
    assert passes[0].cost == 2
    assert plan_passes([_game(start)], set(), now=NOW)[0].cost == 1


# --- what is outstanding -------------------------------------------------------


def test_done_checkpoints_are_never_planned_again():
    game = _game(NOW + timedelta(days=2))
    done = {(game.event_id, "t24h"), (game.event_id, "t6h")}
    assert [p.top_checkpoint for p in plan_passes([game], done, now=NOW)] == [
        CHECKPOINT_T1H, CHECKPOINT_CLOSE
    ]


def test_a_missed_window_is_dropped_not_taken_late():
    game = _game(NOW + timedelta(hours=3))  # T-24h and T-6h are long gone
    assert [p.top_checkpoint for p in plan_passes([game], set(), now=NOW)] == [
        CHECKPOINT_T1H, CHECKPOINT_CLOSE
    ]


def test_a_window_that_just_closed_is_served_now():
    """The loop can be a few seconds late; that is still the checkpoint."""
    game = _game(NOW + timedelta(minutes=4))  # close window (to T-6m) ended 2 minutes ago
    p = plan_passes([game], set(), now=NOW)[0]
    assert p.has_close and p.at == NOW
    assert plan_passes([game], set(), now=NOW + MISSED_GRACE + timedelta(minutes=3)) == []


def test_priority_prefers_nearer_checkpoints_then_liquidity():
    start = NOW + timedelta(days=2)
    t1h_thin = plan_passes([_game(start, liquidity=10.0)], set(), now=NOW)[2]
    t6h_rich = plan_passes([_game(start, liquidity=1e6)], set(), now=NOW)[1]
    t1h_rich = plan_passes([_game(start, liquidity=1e6)], set(), now=NOW)[2]
    assert t1h_thin.top_checkpoint is CHECKPOINT_T1H and t6h_rich.top_checkpoint is CHECKPOINT_T6H
    assert t1h_thin.priority > t6h_rich.priority
    assert t1h_rich.priority > t1h_thin.priority


# --- per-sport config ----------------------------------------------------------


def test_only_nfl_is_enabled_by_default():
    enabled = {s for s, p in sport_polling().items() if p.enabled}
    assert enabled == {"nfl"}
    assert Settings(_env_file=None).odds_sports_enabled == ["nfl"]


def test_sports_are_enabled_from_a_csv_env_value(monkeypatch):
    monkeypatch.setenv("ODDS_SPORTS_ENABLED", "nfl, NBA,nhl")
    assert Settings(_env_file=None).odds_sports_enabled == ["nfl", "NBA", "nhl"]
    monkeypatch.setattr(settings, "odds_sports_enabled", ["nfl", "NBA", "nhl"])
    assert {s for s, p in sport_polling().items() if p.enabled} == {"nfl", "nba", "nhl"}


@pytest.mark.parametrize("raw, expected", [("", None), ("  ", None), ("430", 430)])
def test_the_credit_seed_reads_blank_as_unset(monkeypatch, raw, expected):
    """.env.example ships the seed blank; copying it must not crash every process."""
    monkeypatch.setenv("ODDS_CREDITS_REMAINING_SEED", raw)
    assert Settings(_env_file=None).odds_credits_remaining_seed == expected


def test_passes_per_day_is_per_sport(monkeypatch):
    monkeypatch.setattr(settings, "odds_passes_per_day_nba", 7)
    cfg = sport_polling()
    assert (cfg["nfl"].passes_per_day, cfg["nba"].passes_per_day, cfg["nhl"].passes_per_day) == (
        6, 7, 4
    )


def test_every_polled_key_is_declared_and_every_declared_key_is_polled():
    polled = {k: sport for sport, (_, seasons) in SPORT_SEASONS.items() for k in seasons}
    assert set(polled) == set(ODDS_SPORTS)
    assert all(ODDS_SPORTS[k].sport == sport for k, sport in polled.items())


@pytest.mark.parametrize(
    "key, day, expected",
    [
        ("americanfootball_nfl", date(2027, 1, 15), True),  # wraps New Year
        ("americanfootball_nfl", date(2027, 3, 1), False),
        ("americanfootball_nfl_preseason", date(2026, 8, 10), True),
        ("americanfootball_nfl_preseason", date(2026, 10, 10), False),
        ("basketball_nba_preseason", date(2026, 10, 16), True),
        ("basketball_nba_preseason", date(2026, 10, 17), False),  # stops itself after Oct 16
        ("icehockey_nhl", date(2026, 8, 1), False),
    ],
)
def test_season_windows(key, day, expected):
    windows = {k: w for _, (_, seasons) in SPORT_SEASONS.items() for k, w in seasons.items()}
    assert windows[key].contains(day) is expected


def test_season_window_without_wrap():
    w = SeasonWindow((3, 1), (3, 31))
    assert w.contains(date(2026, 3, 1)) and w.contains(date(2026, 3, 31))
    assert not w.contains(date(2026, 4, 1))


def test_a_disabled_sport_is_never_active(monkeypatch):
    monkeypatch.setattr(settings, "odds_sports_enabled", ["nfl"])
    assert [p.sport for p in active_sports(date(2026, 11, 1))] == ["nfl"]
    monkeypatch.setattr(settings, "odds_sports_enabled", ["nfl", "nba"])
    nba = {p.sport: p for p in active_sports(date(2026, 10, 18))}["nba"]
    assert nba.keys_in_season(date(2026, 10, 18)) == ["basketball_nba"]


# --- the Kalshi gate and the plan from real rows (DB) ----------------------------


class _FakeOdds:
    """Stands in for OddsApiClient: /events only, and it counts calls."""

    def __init__(self, listings: dict[str, list[dict]]):
        self.listings = listings
        self.events_calls: list[str] = []

    def get_events(self, sport_key):
        self.events_calls.append(sport_key)
        return self.listings.get(sport_key, [])

    def get_odds(self, *a, **k):  # pragma: no cover - must never be reached
        raise AssertionError("planning must never make a paid call")


# Far in the future, so rows already in a shared database (live Kalshi games,
# recent ingest_runs) can never fall inside these tests' windows.
LATER = datetime(2099, 10, 10, 12, 0, tzinfo=UTC)
SEA, LAR = "Seattle Seahawks", "Los Angeles Rams"
KICK = LATER + timedelta(hours=30)  # inside the 36h gate, with T-24h still ahead


def _kalshi_game(db, *, ticker=None, start=None):
    ev = Event(
        sport="nfl", league="NFL", home_team=SEA, away_team=LAR,
        # Kalshi rows carry the ticker's date at midnight UTC, not the kickoff.
        scheduled_start=start or KICK.replace(hour=0, minute=0),
        status="scheduled",
        kalshi_event_ticker=ticker or f"KXNFLGAME-99OCT11LARSEA-{uuid.uuid4().hex[:6]}",
        home_away_source="kalshi_provisional",
    )
    db.add(ev)
    db.flush()
    return ev


def _kalshi_ran(db, *, ago=timedelta(minutes=5), status="success"):
    db.add(IngestRun(source="kalshi", status=status, started_at=LATER - ago))
    db.flush()


def _listing(start=KICK):
    return {
        "id": f"odds-{uuid.uuid4().hex[:8]}", "sport_key": "americanfootball_nfl",
        "commence_time": start.isoformat().replace("+00:00", "Z"),
        "home_team": SEA, "away_team": LAR,
    }


@pytest.fixture
def at_now(monkeypatch):
    monkeypatch.setattr(settings, "odds_sports_enabled", ["nfl"])
    return LATER


def _plan(db, client):
    return build_plan(db, client, now=LATER, cache=EventsCache(ttl=0))


def test_no_kalshi_market_no_plan(db_session, at_now):
    _kalshi_ran(db_session)
    client = _FakeOdds({"americanfootball_nfl": [_listing()]})
    assert _plan(db_session, client) == []
    assert client.events_calls == []  # the gate is checked before even the free call


def test_a_stale_kalshi_poller_closes_every_gate(db_session, at_now, monkeypatch):
    monkeypatch.setattr(odds_schedule, "kalshi_fresh", lambda s, now: False)
    _kalshi_game(db_session)
    assert _plan(db_session, _FakeOdds({"americanfootball_nfl": [_listing()]})) == []


def test_kalshi_freshness_reads_successful_runs_only(db_session):
    _kalshi_ran(db_session, ago=timedelta(minutes=5), status="failure")
    assert not odds_schedule.kalshi_fresh(db_session, now=LATER)
    _kalshi_ran(db_session, ago=timedelta(minutes=10))
    assert odds_schedule.kalshi_fresh(db_session, now=LATER)
    assert not odds_schedule.kalshi_fresh(db_session, now=LATER + timedelta(hours=2))


def test_a_kalshi_backed_game_is_planned_from_its_exact_start(db_session, at_now, monkeypatch):
    monkeypatch.setattr(odds_schedule, "kalshi_fresh", lambda s, now: True)
    ev = _kalshi_game(db_session)
    plan = _plan(db_session, _FakeOdds({"americanfootball_nfl": [_listing()]}))
    assert [p.top_checkpoint for p in plan] == [
        CHECKPOINT_T24H, CHECKPOINT_T6H, CHECKPOINT_T1H, CHECKPOINT_CLOSE
    ]
    (game, _), = plan[-1].covers
    assert game.event_id == ev.id and game.start == KICK  # minute-exact, from /events


def test_a_game_kalshi_does_not_list_is_not_planned(db_session, at_now, monkeypatch):
    monkeypatch.setattr(odds_schedule, "kalshi_fresh", lambda s, now: True)
    _kalshi_game(db_session)
    other = _listing()
    other["home_team"], other["away_team"] = "Dallas Cowboys", "New York Giants"
    plan = _plan(db_session, _FakeOdds({"americanfootball_nfl": [other]}))
    assert plan == []


def test_games_beyond_the_horizon_are_not_planned(db_session, at_now, monkeypatch):
    monkeypatch.setattr(odds_schedule, "kalshi_fresh", lambda s, now: True)
    _kalshi_game(db_session)
    far = _listing(LATER + timedelta(hours=settings.kalshi_gate_horizon_hours + 1))
    assert _plan(db_session, _FakeOdds({"americanfootball_nfl": [far]})) == []


def test_recorded_checkpoints_are_not_replanned(db_session, at_now, monkeypatch):
    monkeypatch.setattr(odds_schedule, "kalshi_fresh", lambda s, now: True)
    ev = _kalshi_game(db_session)
    for name in ("t24h", "t6h"):
        db_session.add(OddsCheckpoint(event_id=ev.id, sport="nfl", checkpoint=name,
                                      status="captured"))
    db_session.flush()
    plan = _plan(db_session, _FakeOdds({"americanfootball_nfl": [_listing()]}))
    assert [p.top_checkpoint.name for p in plan] == ["t1h", "close"]


def test_the_events_listing_is_cached_and_survives_a_failed_refresh():
    ticks = iter([0.0, 0.0, 10.0, 99_999.0, 99_999.0])
    cache = EventsCache(ttl=3600)
    client = _FakeOdds({"k": [{"id": "a"}]})
    clock = lambda: next(ticks)  # noqa: E731
    assert cache.get(client, "k", clock=clock) == [{"id": "a"}]
    assert cache.get(client, "k", clock=clock) == [{"id": "a"}]
    assert client.events_calls == ["k"]

    def broken(_):
        raise RuntimeError("down")

    client.get_events = broken
    assert cache.get(client, "k", clock=clock) == [{"id": "a"}]


# --- running a due pass ----------------------------------------------------------


class _NullClient:
    """The plan is injected below, so the client is never used — only opened."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None


@pytest.fixture
def due_close(db_session, monkeypatch):
    """A Kalshi-backed game whose close is due now, with every side effect captured."""
    from sqlalchemy.orm import Session

    from arbitrium.ingestion import governor
    from arbitrium.ingestion.result import IngestResult

    ev = _kalshi_game(db_session, start=LATER + timedelta(minutes=6))
    game = GameSlot(ev.id, "nfl", "americanfootball_nfl", LATER + timedelta(minutes=6), 5_000.0)
    monkeypatch.setattr(settings, "odds_api_key", "test-key")
    monkeypatch.setattr(settings, "odds_sports_enabled", ["nfl"])
    monkeypatch.setattr(odds_schedule, "get_session", lambda: Session(bind=db_session.connection()))
    monkeypatch.setattr(odds_schedule, "OddsApiClient", _NullClient)
    monkeypatch.setattr(odds_schedule, "build_plan",
                        lambda s, c, now: plan_passes([game], set(), now=now))
    monkeypatch.setattr(governor, "non_close_odds_calls_today", lambda *a, **k: 0)
    calls = []
    monkeypatch.setattr(
        odds_schedule.odds_api, "run_ingest",
        lambda keys, checkpoint: calls.append((keys, checkpoint))
        or IngestResult(source="odds_api", events_seen=1, rows_attempted=2, rows_written=2),
    )
    return ev, calls


def _checkpoints(db, ev):
    return [(r.checkpoint, r.status, r.reason)
            for r in db.query(OddsCheckpoint).filter(OddsCheckpoint.event_id == ev.id)]


def test_a_due_close_is_bought_and_tagged(db_session, due_close, monkeypatch):
    from arbitrium.ingestion import governor

    ev, calls = due_close
    monkeypatch.setattr(governor, "load_budget",
                        lambda s, now: governor.Budget(300, 0, now))
    result = odds_schedule.run_due_passes(now=LATER)
    assert calls == [(["americanfootball_nfl"], "close")]
    assert _checkpoints(db_session, ev) == [("close", "captured", None)]
    assert result.rows_written == 2


def test_a_close_refused_by_the_reserve_is_recorded_as_skipped(db_session, due_close, monkeypatch):
    from arbitrium.ingestion import governor

    ev, calls = due_close
    monkeypatch.setattr(governor, "load_budget", lambda s, now: governor.Budget(50, 0, now))
    odds_schedule.run_due_passes(now=LATER)
    assert calls == []
    assert _checkpoints(db_session, ev) == [("close", "skipped_budget", "reserve")]


def test_nothing_due_spends_nothing(db_session, due_close, monkeypatch):
    from arbitrium.ingestion import governor

    ev, calls = due_close
    monkeypatch.setattr(governor, "load_budget", lambda s, now: governor.Budget(300, 0, now))
    odds_schedule.run_due_passes(now=LATER - timedelta(hours=1))
    assert calls == [] and _checkpoints(db_session, ev) == []


def test_without_a_key_the_scheduler_plans_nothing(monkeypatch):
    monkeypatch.setattr(settings, "odds_api_key", None)
    assert odds_schedule.seconds_until_next_pass(now=LATER) is None
