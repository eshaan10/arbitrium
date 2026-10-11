"""The credit governor: reserve, daily allowance, pace tiers, and the per-sport cap.

The free tier is 500 credits a month. These pin the rules that keep three
sports inside it, and the one rule that must never bend for pace: a closing-line
checkpoint on a normal heavy game day always runs.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from arbitrium.config import settings
from arbitrium.db.models import CreditLog
from arbitrium.ingestion import governor
from arbitrium.ingestion.governor import Budget, Tier, admit
from arbitrium.ingestion.polling import (
    CHECKPOINT_CLOSE,
    CHECKPOINT_T1H,
    CHECKPOINT_T6H,
    CHECKPOINT_T24H,
    GameSlot,
    PlannedPass,
    plan_passes,
)

UTC = timezone.utc
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)  # 22 UTC days left incl. today
LIQUID = 25_000.0
THIN = 50.0


def _game(start, *, sport="nba", key="basketball_nba", liquidity=LIQUID):
    return GameSlot(uuid.uuid4(), sport, key, start, liquidity)


def _pass(*covers, at=NOW, sport="nba"):
    return PlannedPass(sport, at, tuple(covers))


def _budget(remaining, spent_today=0, now=NOW):
    return Budget(remaining=remaining, spent_today=spent_today, now=now)


# --- the calendar ------------------------------------------------------------


def test_reserve_is_ten_percent_of_the_budget():
    assert governor.reserve_credits() == 50


def test_period_runs_from_the_first_at_midnight_utc():
    assert governor.period_start(NOW) == datetime(2026, 10, 1, tzinfo=UTC)
    assert governor.next_reset(NOW) == datetime(2026, 11, 1, tzinfo=UTC)


def test_the_reset_instant_belongs_to_the_new_period():
    reset = datetime(2026, 11, 1, tzinfo=UTC)
    assert governor.period_start(reset) == reset
    assert governor.period_start(reset - timedelta(microseconds=1)) == datetime(
        2026, 10, 1, tzinfo=UTC
    )


def test_december_resets_into_january():
    assert governor.next_reset(datetime(2026, 12, 31, 23, 59, tzinfo=UTC)) == datetime(
        2027, 1, 1, tzinfo=UTC
    )


def test_days_left_counts_today_and_is_never_zero():
    assert _budget(300).days_left == 22
    assert _budget(300, now=datetime(2026, 10, 31, 23, 59, tzinfo=UTC)).days_left == 1


# --- the allowance -----------------------------------------------------------


def test_allowance_is_what_is_above_the_reserve_over_the_days_left():
    # 280 at the start of the day, 50 reserved, 22 days to go.
    assert _budget(270, spent_today=10).daily_allowance == pytest.approx(230 / 22)


def test_allowance_holds_still_while_today_spends_it():
    """Taken at the start of the day; otherwise each call would shrink the next."""
    assert _budget(280, 0).daily_allowance == _budget(270, 10).daily_allowance


def test_allowance_is_zero_at_or_below_the_reserve():
    assert _budget(40).daily_allowance == 0


# --- tiers -------------------------------------------------------------------


def test_tiers_escalate_with_overspend():
    allowance = _budget(280, 0).daily_allowance  # ~10.45
    assert _budget(280, 0).tier() is Tier.NORMAL
    assert _budget(280 - 11, 11).tier() is Tier.OVER_PACE
    assert _budget(280 - 16, 16).tier() is Tier.CLOSE_ONLY
    assert 11 >= allowance and 16 >= 1.5 * allowance


def test_unknown_balance_is_its_own_tier():
    assert _budget(None).tier() is Tier.UNKNOWN


def test_the_reserve_is_never_crossed():
    assert _budget(51).affordable(1)
    assert not _budget(50).affordable(1)  # would leave 49
    assert not _budget(51).affordable(2)  # a scores call
    assert _budget(50).tier() is Tier.RESERVE


# --- admission ---------------------------------------------------------------


def test_everything_runs_under_pace():
    p = _pass((_game(NOW + timedelta(hours=24), liquidity=THIN), CHECKPOINT_T24H))
    assert admit(p, _budget(300), cap=4, non_close_calls_today=0).admitted


def test_unknown_balance_spends_nothing_not_even_a_close():
    p = _pass((_game(NOW + timedelta(minutes=10)), CHECKPOINT_CLOSE))
    d = admit(p, _budget(None), cap=4, non_close_calls_today=0)
    assert (d.admitted, d.reason) == (False, "balance_unknown")


def test_the_reserve_stops_even_a_close():
    p = _pass((_game(NOW + timedelta(minutes=10)), CHECKPOINT_CLOSE))
    d = admit(p, _budget(50), cap=4, non_close_calls_today=0)
    assert (d.admitted, d.reason) == (False, "reserve")


def test_over_pace_drops_t24h_first():
    p = _pass((_game(NOW + timedelta(hours=24)), CHECKPOINT_T24H))
    d = admit(p, _budget(269, 11), cap=4, non_close_calls_today=0)
    assert (d.admitted, d.reason) == (False, "over_pace")


def test_over_pace_drops_thin_games_but_keeps_liquid_ones():
    thin = _pass((_game(NOW + timedelta(hours=1), liquidity=THIN), CHECKPOINT_T1H))
    unknown = _pass((_game(NOW + timedelta(hours=1), liquidity=None), CHECKPOINT_T1H))
    liquid = _pass((_game(NOW + timedelta(hours=1)), CHECKPOINT_T1H))
    over = _budget(269, 11)
    assert not admit(thin, over, cap=4, non_close_calls_today=0).admitted
    assert not admit(unknown, over, cap=4, non_close_calls_today=0).admitted
    assert admit(liquid, over, cap=4, non_close_calls_today=0).admitted


def test_close_only_tier_keeps_closes_and_nothing_else():
    close = _pass((_game(NOW + timedelta(minutes=10), liquidity=THIN), CHECKPOINT_CLOSE))
    t1h = _pass((_game(NOW + timedelta(hours=1)), CHECKPOINT_T1H))
    severe = _budget(264, 16)
    assert severe.tier() is Tier.CLOSE_ONLY
    assert admit(close, severe, cap=4, non_close_calls_today=0).admitted
    assert not admit(t1h, severe, cap=4, non_close_calls_today=0).admitted


def test_a_close_is_exempt_from_the_daily_cap():
    p = _pass((_game(NOW + timedelta(minutes=10)), CHECKPOINT_CLOSE))
    assert admit(p, _budget(300), cap=4, non_close_calls_today=4).admitted


def test_the_cap_stops_non_closing_calls():
    p = _pass((_game(NOW + timedelta(hours=1)), CHECKPOINT_T1H))
    d = admit(p, _budget(300), cap=4, non_close_calls_today=4)
    assert (d.admitted, d.reason) == (False, "daily_cap")


def test_the_cap_keeps_slots_for_higher_priority_passes_later_today():
    """Furthest-from-start and thinnest give way, even when they come first."""
    early_t24 = _pass((_game(NOW + timedelta(hours=24), liquidity=THIN), CHECKPOINT_T24H))
    later = [
        _pass((_game(NOW + timedelta(hours=4)), CHECKPOINT_T1H), at=NOW + timedelta(hours=3)),
        _pass((_game(NOW + timedelta(hours=8)), CHECKPOINT_T6H), at=NOW + timedelta(hours=2)),
    ]
    d = admit(early_t24, _budget(300), cap=2, non_close_calls_today=0, later_today=later)
    assert (d.admitted, d.reason) == (False, "daily_cap_priority")

    # With a third slot, it fits behind them.
    roomier = admit(early_t24, _budget(300), cap=3, non_close_calls_today=0, later_today=later)
    assert roomier.admitted


def test_liquidity_breaks_ties_between_equal_checkpoints():
    thin = _pass((_game(NOW + timedelta(hours=1), liquidity=THIN), CHECKPOINT_T1H))
    rich = _pass(
        (_game(NOW + timedelta(hours=2)), CHECKPOINT_T1H), at=NOW + timedelta(hours=1)
    )
    assert not admit(
        thin, _budget(300), cap=1, non_close_calls_today=0, later_today=[rich]
    ).admitted
    assert admit(rich, _budget(300), cap=1, non_close_calls_today=0, later_today=[thin]).admitted


def test_closes_later_today_do_not_consume_cap_slots():
    p = _pass((_game(NOW + timedelta(hours=1)), CHECKPOINT_T1H))
    closes = [
        _pass((_game(NOW + timedelta(hours=h)), CHECKPOINT_CLOSE), at=NOW + timedelta(hours=h))
        for h in (2, 3, 4)
    ]
    assert admit(p, _budget(300), cap=1, non_close_calls_today=0, later_today=closes).admitted


# --- the heavy game day ------------------------------------------------------


def _slate(day_utc: datetime) -> list[GameSlot]:
    """A heavy autumn Sunday: NFL early/late/night windows, a full NBA and NHL night."""
    def at(h, m=0):
        return day_utc.replace(hour=h, minute=m)

    nfl = [at(17), at(17), at(17), at(17), at(17), at(17), at(20, 5), at(20, 25),
           at(20, 25), at(20, 25)] + [at(0, 20) + timedelta(days=1)]
    nba = [at(23), at(23, 30), at(23, 30)] + [
        at(h, m) + timedelta(days=1) for h, m in ((0, 0), (1, 0), (2, 0), (2, 30), (3, 0))
    ]
    nhl = [at(23), at(23), at(23, 30)] + [
        at(h, m) + timedelta(days=1) for h, m in ((0, 0), (1, 0), (2, 0))
    ]
    thin_every_third = lambda i: THIN if i % 3 == 0 else LIQUID  # noqa: E731
    return (
        [_game(s, sport="nfl", key="americanfootball_nfl", liquidity=thin_every_third(i))
         for i, s in enumerate(nfl)]
        + [_game(s, sport="nba", liquidity=thin_every_third(i)) for i, s in enumerate(nba)]
        + [_game(s, sport="nhl", key="icehockey_nhl", liquidity=thin_every_third(i))
           for i, s in enumerate(nhl)]
    )


@dataclass
class _DayOutcome:
    closes_taken: set
    tiers_seen: set
    remaining: int
    skipped: list


def _simulate(games, start, *, remaining, caps) -> _DayOutcome:
    """Walk the plan pass by pass, exactly as odds_schedule.run_due_passes does."""
    out = _DayOutcome(set(), set(), remaining, [])
    spent_today = close_today = 0
    close_log: list[tuple[datetime, int]] = []  # what credit_log would hold
    non_close = {s: 0 for s in caps}
    done: set = set()
    clock = start
    day = governor.utc_day_start(clock)
    while plan := plan_passes(games, done, now=clock):
        p = plan[0]
        clock = p.at
        if governor.utc_day_start(clock) != day:
            day, spent_today, close_today = governor.utc_day_start(clock), 0, 0
            non_close = {s: 0 for s in caps}
        week = sum(c for t, c in close_log if t >= clock - governor.CLOSE_RATE_WINDOW)
        budget = Budget(out.remaining, spent_today, clock, close_spent_today=close_today,
                        close_rate=week / governor.CLOSE_RATE_WINDOW.days)
        out.tiers_seen.add(budget.tier())
        later = [q for q in plan[1:] if q.sport == p.sport and q.at < day + timedelta(days=1)]
        d = admit(p, budget, cap=caps[p.sport], non_close_calls_today=non_close[p.sport],
                  later_today=later)
        if d.admitted:
            out.remaining -= p.cost
            spent_today += p.cost
            if p.has_close:
                close_today += p.cost
                close_log.append((clock, p.cost))
            else:
                non_close[p.sport] += p.cost
            out.closes_taken |= {g.event_id for g, c in p.covers if c is CHECKPOINT_CLOSE}
        else:
            out.skipped.append((p.top_checkpoint.name, d.reason))
        done |= {(g.event_id, c.name) for g, c in p.covers}
        clock += timedelta(seconds=1)
    return out


def test_a_heavy_game_day_never_loses_a_close_to_pace():
    """Requirement: over pace may thin the day out, but every close still runs.

    Simulated end to end through the planner and the governor: a month that
    is running low (120 left with 14 days to go), the default per-sport caps,
    and a slate heavy enough to push the day into the close-only tier. Every
    game must still get its closing checkpoint.
    """
    day = datetime(2026, 10, 18, tzinfo=UTC)
    games = _slate(day)
    out = _simulate(games, day - timedelta(hours=8), remaining=120,
                    caps={"nfl": 6, "nba": 4, "nhl": 4})

    assert out.closes_taken == {g.event_id for g in games}
    assert out.tiers_seen & {Tier.OVER_PACE, Tier.CLOSE_ONLY}, (
        "the slate must actually push the day over pace, or this proves nothing"
    )
    assert out.skipped, "and pace must actually have dropped something"
    assert all(name != "close" for name, _ in out.skipped)
    assert out.remaining >= governor.reserve_credits()


def test_near_the_reserve_closes_are_the_last_thing_standing_and_then_stop():
    day = datetime(2026, 10, 18, tzinfo=UTC)
    games = _slate(day)
    out = _simulate(games, day - timedelta(hours=8), remaining=58,
                    caps={"nfl": 6, "nba": 4, "nhl": 4})
    assert out.remaining == governor.reserve_credits()  # spent down to, never into
    assert ("close", "reserve") in out.skipped


# --- the ledger (DB) ---------------------------------------------------------


def _log(db, *, at, credits=1, remaining=None, sport="nfl", endpoint="odds", checkpoint=None):
    db.add(CreditLog(called_at=at, sport=sport, sport_key="americanfootball_nfl",
                     endpoint=endpoint, checkpoint=checkpoint, credits_used=credits,
                     remaining=remaining))
    db.flush()


def _far_now():
    # Far in the future, so no row already in the database can be "latest".
    return datetime(2099, 3, 15, 12, tzinfo=UTC)


def test_balance_comes_from_the_latest_header_this_period(db_session):
    now = _far_now()
    _log(db_session, at=now - timedelta(hours=3), remaining=300)
    _log(db_session, at=now - timedelta(hours=1), remaining=297)
    b = governor.current_balance(db_session, now=now)
    assert (b.remaining, b.source) == (297, "credit_log")


def test_a_log_from_last_period_means_the_quota_has_reset(db_session):
    now = _far_now()
    _log(db_session, at=datetime(2099, 2, 28, 23, tzinfo=UTC), remaining=12)
    b = governor.current_balance(db_session, now=now)
    assert (b.remaining, b.source) == (settings.odds_api_monthly_credit_budget, "period_reset")


def test_seed_and_unknown_apply_only_to_an_db_session(monkeypatch):
    class _Empty:
        def execute(self, *_a, **_k):
            class R:
                def first(self):
                    return None
            return R()

    monkeypatch.setattr(settings, "odds_credits_remaining_seed", 173)
    assert governor.current_balance(_Empty(), now=NOW).remaining == 173
    monkeypatch.setattr(settings, "odds_credits_remaining_seed", None)
    b = governor.current_balance(_Empty(), now=NOW)
    assert (b.remaining, b.source) == (None, "unknown")


def test_spend_today_and_the_cap_meter(db_session):
    now = _far_now()
    midnight = governor.utc_day_start(now)
    _log(db_session, at=midnight - timedelta(minutes=1), credits=1)  # yesterday
    _log(db_session, at=midnight + timedelta(hours=1), credits=1, checkpoint="t24h")
    _log(db_session, at=midnight + timedelta(hours=2), credits=1, checkpoint="close")
    _log(db_session, at=midnight + timedelta(hours=3), credits=0, endpoint="events")
    _log(db_session, at=midnight + timedelta(hours=4), credits=2, endpoint="scores")
    assert governor.spent_since(db_session, midnight) == 4
    assert governor.non_close_odds_calls_today(db_session, "nfl", now=now) == 1


def test_record_call_writes_its_own_row(db_session, monkeypatch):
    from sqlalchemy.orm import Session

    monkeypatch.setattr(
        governor, "get_session", lambda: Session(bind=db_session.connection())
    )
    at = _far_now() + timedelta(days=1)
    governor.record_call(
        governor.CallRecord("odds", "americanfootball_nfl", 1, 411, 89, 14, "nfl", "close"),
        called_at=at,
    )
    row = db_session.query(CreditLog).filter(CreditLog.called_at == at).one()
    assert (row.credits_used, row.remaining, row.checkpoint) == (1, 411, "close")


def test_record_call_never_raises(monkeypatch, caplog):
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(governor, "get_session", boom)
    governor.record_call(governor.CallRecord("odds", "americanfootball_nfl", 1, 1, 1, 1))
    assert "under-count" in caplog.text


def test_closes_are_set_aside_before_anything_else_is_paced():
    # 230 above the reserve over 22 days is ~10.5/day, of which closes take 9.
    budget = _budget(280, 0)
    assert budget.non_close_allowance == budget.daily_allowance
    reserved = Budget(280, 0, NOW, close_rate=9.0)
    assert reserved.non_close_allowance == pytest.approx(230 / 22 - 9.0)
    # Two T-1h calls already put the day over a ~1.5 non-close share...
    assert Budget(278, 2, NOW, close_rate=9.0).tier() is Tier.OVER_PACE
    # ...while the closes spent alongside them do not count against it.
    assert Budget(270, 10, NOW, close_spent_today=8, close_rate=9.0).tier() is Tier.OVER_PACE


def test_close_demand_beyond_the_allowance_leaves_only_closes():
    assert Budget(280, 0, NOW, close_rate=30.0).tier() is Tier.CLOSE_ONLY


# --- a whole month -----------------------------------------------------------


def _synthetic_month(sports: set[str], *, seed: int = 7) -> list[GameSlot]:
    """A November slate: nightly NBA/NHL at realistic tip times, NFL TNF/Sun/MNF."""
    import random

    rng = random.Random(seed)
    d0 = datetime(2026, 11, 1, tzinfo=UTC)
    nightly = {
        "nba": ("basketball_nba", [(23, 0), (23, 30), (24, 0), (24, 30), (25, 0), (26, 0),
                                   (26, 30), (27, 0)], 3, 12),
        "nhl": ("icehockey_nhl", [(23, 0), (23, 30), (24, 0), (25, 0), (26, 0), (26, 30)], 2, 11),
    }
    nfl_week = {3: [(24, 15)], 6: [(18, 0)] * 8 + [(21, 5)] * 2 + [(21, 25)] * 2 + [(25, 20)],
                0: [(25, 15)]}
    games: list[GameSlot] = []
    for n in range(30):
        d = d0 + timedelta(days=n)
        for sport, (key, tips, lo, hi) in nightly.items():
            count = rng.randint(lo, hi)
            if sport not in sports:
                continue
            for _ in range(count):
                h, m = rng.choice(tips)
                games.append(_game(d + timedelta(hours=h, minutes=m), sport=sport, key=key,
                                   liquidity=rng.choice([THIN, 5_000.0, LIQUID])))
        if "nfl" in sports:
            for h, m in nfl_week.get(d.weekday(), []):
                games.append(_game(d + timedelta(hours=h, minutes=m), sport="nfl",
                                   key="americanfootball_nfl"))
    return [g for g in games if g.start < datetime(2026, 11, 30, 23, tzinfo=UTC)]


CAPS = {"nfl": 6, "nba": 4, "nhl": 4}


def test_a_month_of_all_three_sports_keeps_every_close_and_the_reserve():
    """The case the budget is sized for: three sports in season at once.

    Measured before closes were set aside: the month ran into the reserve in
    its last week and lost 58 of 475 closes. Pace has to leave room for the
    closes still to come, not just for today's.
    """
    games = _synthetic_month({"nfl", "nba", "nhl"})
    out = _simulate(games, datetime(2026, 11, 1, tzinfo=UTC), remaining=500, caps=CAPS)
    assert len(games) > 400
    assert out.closes_taken == {g.event_id for g in games}
    assert out.remaining >= governor.reserve_credits()
    assert out.skipped, "three sports do not fit unrationed; something must give"
    assert all(name != "close" for name, _ in out.skipped)


def test_nfl_alone_runs_every_checkpoint_with_room_to_spare():
    """Prod default until NBA/NHL are enabled: nothing should need rationing."""
    games = _synthetic_month({"nfl"})
    out = _simulate(games, datetime(2026, 11, 1, tzinfo=UTC), remaining=500, caps=CAPS)
    assert out.skipped == []
    assert 500 - out.remaining < 150
