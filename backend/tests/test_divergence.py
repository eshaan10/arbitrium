"""Divergence scoring: status rules, team-anchored joins, and what is NOT scored.

The pure tests pin the honesty rules (thin consensus and single-source events are
labelled, never silently dropped, and never assigned a number). The DB test proves
the join survives an authoritative home/away flip, which is the whole reason
``odds_snapshots.team`` exists.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from marketedge.db.models import Event, OddsSnapshot
from marketedge.divergence.engine import (
    DivergenceStatus,
    OutcomeDivergence,
    OutcomeQuote,
    compute_divergences,
    detect_arbitrage,
    score_event,
)

UTC = timezone.utc
T0 = datetime(2026, 9, 14, 17, 0, tzinfo=UTC)


def _q(team, prob, *, n_books=None, outcome="home"):
    return OutcomeQuote(
        outcome=outcome, team=team, implied_probability=prob,
        snapshot_time=T0, n_books=n_books,
    )


def _pair(kalshi_home, kalshi_away, cons_home, cons_away, n_books):
    kalshi = [_q("Chiefs", kalshi_home), _q("Broncos", kalshi_away, outcome="away")]
    consensus = [
        _q("Chiefs", cons_home, n_books=n_books),
        _q("Broncos", cons_away, n_books=n_books, outcome="away"),
    ]
    return kalshi, consensus


# --- scored path -------------------------------------------------------------


def test_scored_when_both_sources_and_enough_books():
    k, c = _pair(0.60, 0.40, 0.55, 0.45, n_books=5)
    status, _, n_books, rows, max_abs = score_event(kalshi_quotes=k, consensus_quotes=c)
    assert status is DivergenceStatus.SCORED
    assert n_books == 5
    by_team = {r.team: r for r in rows}
    # Sign convention: positive => Kalshi prices that team HIGHER than the books.
    assert by_team["Chiefs"].divergence == 0.60 - 0.55
    assert by_team["Broncos"].divergence == 0.40 - 0.45
    assert abs(max_abs - 0.05) < 1e-9


def test_book_count_uses_the_weaker_side():
    k, _ = _pair(0.60, 0.40, 0.55, 0.45, n_books=5)
    consensus = [_q("Chiefs", 0.55, n_books=9), _q("Broncos", 0.45, n_books=2, outcome="away")]
    status, _, n_books, _, _ = score_event(kalshi_quotes=k, consensus_quotes=consensus)
    assert n_books == 2
    assert status is DivergenceStatus.INSUFFICIENT_CONSENSUS


# --- the honesty rules -------------------------------------------------------


def test_thin_consensus_is_flagged_and_carries_no_number():
    k, c = _pair(0.60, 0.40, 0.55, 0.45, n_books=1)
    status, reason, n_books, rows, max_abs = score_event(kalshi_quotes=k, consensus_quotes=c)
    assert status is DivergenceStatus.INSUFFICIENT_CONSENSUS
    assert n_books == 1
    assert max_abs is None
    # Observed prices survive (they are real observations); the SCORE does not.
    assert all(r.divergence is None for r in rows)
    assert all(r.kalshi_probability is not None for r in rows)
    assert all(r.consensus_probability is not None for r in rows)
    assert "1 bookmaker" in reason


def test_book_floor_is_a_hard_boundary():
    for n, expected in ((2, DivergenceStatus.INSUFFICIENT_CONSENSUS),
                        (3, DivergenceStatus.SCORED)):
        k, c = _pair(0.60, 0.40, 0.55, 0.45, n_books=n)
        status, _, _, _, _ = score_event(kalshi_quotes=k, consensus_quotes=c, min_books=3)
        assert status is expected, f"n_books={n}"


def test_single_source_is_labelled_not_dropped():
    k, _ = _pair(0.60, 0.40, 0.55, 0.45, n_books=5)
    status, reason, _, rows, max_abs = score_event(kalshi_quotes=k, consensus_quotes=[])
    assert status is DivergenceStatus.SINGLE_SOURCE
    assert max_abs is None
    assert "kalshi" in reason
    # The event still reports what it DOES know.
    assert {r.team for r in rows} == {"Chiefs", "Broncos"}
    assert all(r.consensus_probability is None for r in rows)


def test_mismatched_outcome_keys_are_flagged_not_scored():
    kalshi = [_q("Chiefs", 0.60), _q("Broncos", 0.40, outcome="away")]
    consensus = [_q("Chiefs", 0.55, n_books=9), _q("Raiders", 0.45, n_books=9, outcome="away")]
    status, _, _, _, max_abs = score_event(kalshi_quotes=kalshi, consensus_quotes=consensus)
    assert status is DivergenceStatus.INCOMPARABLE
    assert max_abs is None


def test_draw_outcomes_join_on_outcome_when_team_is_null():
    kalshi = [_q(None, 0.25, outcome="draw")]
    consensus = [_q(None, 0.20, n_books=6, outcome="draw")]
    status, _, _, rows, max_abs = score_event(kalshi_quotes=kalshi, consensus_quotes=consensus)
    assert status is DivergenceStatus.SCORED
    assert rows[0].join_key == "__draw__"
    assert abs(max_abs - 0.05) < 1e-9


# --- DB: the join must survive a home/away flip ------------------------------


def _mk_snapshot(event_id, source, outcome, team, prob, **kw):
    return OddsSnapshot(
        event_id=event_id, source=source, outcome=outcome, team=team,
        implied_probability=prob, price_format="probability",
        snapshot_time=T0, ingested_at=T0, **kw,
    )


def test_divergence_joins_on_team_not_home_away(db_session):
    """Kalshi wrote 'home'=Chiefs; Odds API later proves Chiefs were AWAY.

    The append-only Kalshi row still says outcome='home'. If the comparison keyed
    on home/away it would now compare Chiefs against Broncos. Keyed on team, it
    stays correct.
    """
    start = datetime.now(UTC) + timedelta(days=400)
    ev = Event(
        sport="nfl", league="NFL", home_team="Kansas City Chiefs",
        away_team="Denver Broncos", scheduled_start=start, status="scheduled",
        home_away_source="kalshi_provisional",
    )
    db_session.add(ev)
    db_session.flush()

    db_session.add(_mk_snapshot(ev.id, "kalshi", "home", "Kansas City Chiefs", 0.62))
    db_session.add(_mk_snapshot(ev.id, "kalshi", "away", "Denver Broncos", 0.38))
    db_session.flush()

    # Authoritative flip: the Odds API says Denver is home.
    ev.home_team, ev.away_team = "Denver Broncos", "Kansas City Chiefs"
    ev.home_away_source = "odds_api"
    db_session.add(_mk_snapshot(
        ev.id, "consensus", "home", "Denver Broncos", 0.40,
        order_book_depth={"n_books": 6},
    ))
    db_session.add(_mk_snapshot(
        ev.id, "consensus", "away", "Kansas City Chiefs", 0.60,
        order_book_depth={"n_books": 6},
    ))
    db_session.flush()

    results = compute_divergences(db_session, sport="nfl")
    mine = [r for r in results if r.event_id == ev.id]
    assert len(mine) == 1
    row = mine[0]
    assert row.status is DivergenceStatus.SCORED
    by_team = {o.team: o for o in row.outcomes}
    # Chiefs: kalshi 0.62 vs consensus 0.60 — NOT 0.62 vs 0.40.
    assert abs(by_team["Kansas City Chiefs"].divergence - 0.02) < 1e-9
    assert abs(by_team["Denver Broncos"].divergence - (-0.02)) < 1e-9


def test_latest_snapshot_wins(db_session):
    start = datetime.now(UTC) + timedelta(days=401)
    ev = Event(
        sport="nfl", league="NFL", home_team="Buffalo Bills",
        away_team="Miami Dolphins", scheduled_start=start, status="scheduled",
    )
    db_session.add(ev)
    db_session.flush()
    for prob, t in ((0.50, T0), (0.70, T0 + timedelta(hours=1))):
        db_session.add(OddsSnapshot(
            event_id=ev.id, source="kalshi", outcome="home", team="Buffalo Bills",
            implied_probability=prob, price_format="probability",
            snapshot_time=t, ingested_at=t,
        ))
    db_session.add(_mk_snapshot(
        ev.id, "consensus", "home", "Buffalo Bills", 0.60,
        order_book_depth={"n_books": 4},
    ))
    db_session.flush()

    row = [r for r in compute_divergences(db_session, sport="nfl") if r.event_id == ev.id][0]
    bills = {o.team: o for o in row.outcomes}["Buffalo Bills"]
    assert bills.kalshi_probability == 0.70  # not the stale 0.50


# --- the execution axis: net edge after spread -------------------------------


def _k(team, prob, *, bid=None, ask=None, bid_size=None, ask_size=None, outcome="home"):
    return OutcomeQuote(
        outcome=outcome, team=team, implied_probability=prob, snapshot_time=T0,
        bid=bid, ask=ask, bid_size=bid_size, ask_size=ask_size,
    )


def test_edge_smaller_than_spread_is_not_tradeable():
    """The common live case: a real disagreement worth nothing.

    Kalshi mid 0.50 vs consensus 0.52 — a 2pt divergence. But the ask is 0.53,
    so buying costs more than the books think it is worth.
    """
    kalshi = [_k("Chiefs", 0.50, bid=0.47, ask=0.53)]
    consensus = [_q("Chiefs", 0.52, n_books=9)]
    status, reason, _, rows, _ = score_event(
        kalshi_quotes=kalshi, consensus_quotes=consensus
    )
    assert status is DivergenceStatus.SCORED
    row = rows[0]
    assert row.divergence is not None  # the measurement survives
    assert row.tradeable is False
    assert row.net_edge_after_spread < 0
    assert row.trade_side is None
    assert "no edge survives" in reason


def test_edge_larger_than_spread_is_tradeable_on_the_buy_side():
    """Books say 0.60, Kalshi asks 0.53 -> buy Kalshi for a 7pt edge."""
    kalshi = [_k("Chiefs", 0.50, bid=0.47, ask=0.53)]
    consensus = [_q("Chiefs", 0.60, n_books=9)]
    _, _, _, rows, _ = score_event(kalshi_quotes=kalshi, consensus_quotes=consensus)
    row = rows[0]
    assert row.tradeable is True
    assert abs(row.net_edge_after_spread - 0.07) < 1e-9
    assert row.trade_side == "buy_kalshi"


def test_tradeable_on_the_sell_side():
    """Books say 0.40, Kalshi bids 0.47 -> sell Kalshi for a 7pt edge."""
    kalshi = [_k("Chiefs", 0.50, bid=0.47, ask=0.53)]
    consensus = [_q("Chiefs", 0.40, n_books=9)]
    _, _, _, rows, _ = score_event(kalshi_quotes=kalshi, consensus_quotes=consensus)
    row = rows[0]
    assert row.tradeable is True
    assert abs(row.net_edge_after_spread - 0.07) < 1e-9
    assert row.trade_side == "sell_kalshi"


def test_net_edge_uses_raw_book_not_vig_stripped_mid():
    """The distinction that makes this axis honest.

    implied_probability is vig-stripped (belief); bid/ask are raw (execution).
    A quote whose stripped mid differs from its raw touch must price off the
    RAW side, or the edge is fiction.
    """
    # Stripped mid says 0.50, but the raw book is far away at 0.60/0.62.
    kalshi = [_k("Chiefs", 0.50, bid=0.60, ask=0.62)]
    consensus = [_q("Chiefs", 0.55, n_books=9)]
    _, _, _, rows, _ = score_event(kalshi_quotes=kalshi, consensus_quotes=consensus)
    row = rows[0]
    # Sell at 0.60 against a 0.55 belief = +0.05. Using the stripped mid would
    # have said 0.55-0.50 = +0.05 buy, i.e. the wrong SIDE entirely.
    assert row.trade_side == "sell_kalshi"
    assert abs(row.net_edge_after_spread - 0.05) < 1e-9


def test_unknown_book_is_not_assumed_tradeable():
    """No bid/ask -> tradeability is unknown, which must never read as yes."""
    kalshi = [_k("Chiefs", 0.50)]  # no book
    consensus = [_q("Chiefs", 0.60, n_books=9)]
    _, _, _, rows, _ = score_event(kalshi_quotes=kalshi, consensus_quotes=consensus)
    row = rows[0]
    assert row.divergence is not None
    assert row.net_edge_after_spread is None
    assert row.tradeable is False


def test_unscored_events_carry_no_edge_either():
    """The thin-consensus gate must suppress the trade number too."""
    kalshi = [_k("Chiefs", 0.50, bid=0.40, ask=0.42)]
    consensus = [_q("Chiefs", 0.60, n_books=1)]  # below the floor
    status, _, _, rows, _ = score_event(kalshi_quotes=kalshi, consensus_quotes=consensus)
    assert status is DivergenceStatus.INSUFFICIENT_CONSENSUS
    assert rows[0].net_edge_after_spread is None
    assert rows[0].tradeable is False


def test_resting_depth_is_weakest_link_and_not_liquidity_score():
    q = _k("Chiefs", 0.50, bid=0.47, ask=0.53, bid_size=50.0, ask_size=221.0)
    assert q.resting_depth == 50.0  # min, not max, not sum
    assert abs(q.spread - 0.06) < 1e-9


def test_spread_and_depth_are_none_without_a_book():
    q = _k("Chiefs", 0.50)
    assert q.spread is None
    assert q.resting_depth is None


def test_two_way_outcomes_are_one_bet_not_two():
    """Both sides of a two-way market can show a positive edge simultaneously.

    Selling Yes on one side IS buying Yes on the other, at a possibly better
    price. The event-level rollup must take the MAX (the better fill), never the
    sum, or a single position is counted twice. Mirrors live Packers/Vikings.
    """
    kalshi = [
        _k("Packers", 0.4802, bid=0.48, ask=0.49),
        _k("Vikings", 0.5198, bid=0.52, ask=0.53, outcome="away"),
    ]
    consensus = [
        _q("Packers", 0.4990, n_books=9),
        _q("Vikings", 0.5010, n_books=9, outcome="away"),
    ]
    status, _, _, rows, _ = score_event(kalshi_quotes=kalshi, consensus_quotes=consensus)
    assert status is DivergenceStatus.SCORED

    by_team = {r.team: r for r in rows}
    assert by_team["Packers"].tradeable and by_team["Vikings"].tradeable
    assert abs(by_team["Packers"].net_edge_after_spread - 0.0090) < 1e-9
    assert abs(by_team["Vikings"].net_edge_after_spread - 0.0190) < 1e-9

    ev = _event_divergence(rows)
    # MAX, not 0.0090 + 0.0190 = 0.028.
    assert abs(ev.best_net_edge - 0.0190) < 1e-9
    assert ev.best_trade.team == "Vikings"
    assert ev.best_trade.trade_side == "sell_kalshi"


def _event_divergence(rows):
    import uuid

    from marketedge.divergence.engine import EventDivergence
    return EventDivergence(
        event_id=uuid.uuid4(), sport="nfl", league="NFL",
        home_team="Vikings", away_team="Packers", scheduled_start=T0,
        status=DivergenceStatus.SCORED, reason="", sources=["consensus", "kalshi"],
        n_books=9, max_abs_divergence=0.0188, outcomes=rows,
    )


def test_best_trade_is_none_when_nothing_is_tradeable():
    kalshi = [_k("Chiefs", 0.50, bid=0.47, ask=0.53)]
    consensus = [_q("Chiefs", 0.52, n_books=9)]
    _, _, _, rows, _ = score_event(kalshi_quotes=kalshi, consensus_quotes=consensus)
    ev = _event_divergence(rows)
    assert ev.tradeable is False
    assert ev.best_trade is None
    # A negative best_net_edge is still reported — it says HOW FAR from tradeable.
    assert ev.best_net_edge is not None and ev.best_net_edge < 0


# --- expected value at depth -------------------------------------------------


def test_expected_value_exposes_the_thin_book_case():
    """The live Lions case: a healthy percentage on almost no size.

    +1.87% against 3.5 resting contracts is ~6 cents. The percentage looks
    respectable; the expected value makes the truth obvious without needing a
    depth floor to reject it.
    """
    kalshi = [_k("Lions", 0.7600, bid=0.7600, ask=0.7700, bid_size=3.53, ask_size=90.0)]
    consensus = [_q("Lions", 0.7413, n_books=9)]
    _, _, _, rows, _ = score_event(kalshi_quotes=kalshi, consensus_quotes=consensus)
    row = rows[0]
    assert row.tradeable is True
    assert abs(row.net_edge_after_spread - 0.0187) < 1e-9  # a healthy-looking %
    assert row.resting_depth == 3.53
    assert row.expected_value_at_depth < 0.10  # ...worth about six cents


def test_expected_value_ranks_thin_below_deep_at_equal_edge():
    """Same percentage edge, very different trades."""
    thin = OutcomeDivergence(
        join_key="A", team="A", kalshi_probability=0.5, consensus_probability=0.5,
        divergence=0.0, net_edge_after_spread=0.02, resting_depth=3.0,
    )
    deep = OutcomeDivergence(
        join_key="B", team="B", kalshi_probability=0.5, consensus_probability=0.5,
        divergence=0.0, net_edge_after_spread=0.02, resting_depth=1000.0,
    )
    assert thin.net_edge_after_spread == deep.net_edge_after_spread
    assert deep.expected_value_at_depth > thin.expected_value_at_depth
    assert abs(thin.expected_value_at_depth - 0.06) < 1e-9
    assert abs(deep.expected_value_at_depth - 20.0) < 1e-9


def test_expected_value_is_none_when_depth_unknown():
    """Unknown size must not read as zero value or as a large one."""
    row = OutcomeDivergence(
        join_key="A", team="A", kalshi_probability=0.5, consensus_probability=0.5,
        divergence=0.0, net_edge_after_spread=0.02, resting_depth=None,
    )
    assert row.expected_value_at_depth is None


def test_expected_value_is_not_a_gate():
    """A tiny-EV row is still returned and still flagged tradeable."""
    kalshi = [_k("Lions", 0.76, bid=0.76, ask=0.77, bid_size=1.0, ask_size=1.0)]
    consensus = [_q("Lions", 0.7413, n_books=9)]
    status, _, _, rows, _ = score_event(kalshi_quotes=kalshi, consensus_quotes=consensus)
    assert status is DivergenceStatus.SCORED
    assert rows[0].tradeable is True
    assert rows[0].expected_value_at_depth < 0.03


# --- arbitrage ---------------------------------------------------------------


def _c(team, prob, books, *, n_books=None, outcome="home"):
    return OutcomeQuote(
        outcome=outcome, team=team, implied_probability=prob, snapshot_time=T0,
        n_books=n_books if n_books is not None else len(books), book_prices=books,
    )


def test_arbitrage_detected_across_venues():
    """Kalshi ask 0.45 on A + a book paying +130 on B = 0.4348 -> covered for 0.885."""
    kalshi = [_k("A", 0.46, bid=0.44, ask=0.45, ask_size=100.0)]
    consensus = [
        _c("A", 0.47, {"dk": -110.0}),
        _c("B", 0.53, {"dk": 130.0}, outcome="away"),
    ]
    arb = detect_arbitrage(kalshi, consensus)
    assert arb is not None
    assert abs(arb.total_cost - (0.45 + 100.0 / 230.0)) < 1e-9
    assert arb.gross_profit > 0
    venues = {leg.team: leg.venue for leg in arb.legs}
    assert venues["A"] == "kalshi"  # cheaper than the book's -110
    assert venues["B"] == "dk"


def test_no_arbitrage_when_prices_sum_above_one():
    kalshi = [_k("A", 0.50, bid=0.49, ask=0.51, ask_size=100.0)]
    consensus = [
        _c("A", 0.50, {"dk": -110.0}),
        _c("B", 0.50, {"dk": -110.0}, outcome="away"),
    ]
    assert detect_arbitrage(kalshi, consensus) is None


def test_arbitrage_cannot_come_from_vig_stripped_probabilities():
    """The reason arbitrage prices off raw odds.

    Vig-stripped probabilities are renormalised to sum to exactly 1, so an
    implementation reading them would find arbitrage never — or, worse, always.
    With no raw book prices there is nothing to price, so the answer is None.
    """
    kalshi = [_k("A", 0.40)]  # no ask
    consensus = [
        _c("A", 0.40, {}), _c("B", 0.60, {}, outcome="away"),
    ]
    assert sum(q.implied_probability for q in consensus) == 1.0
    assert detect_arbitrage(kalshi, consensus) is None


def test_arbitrage_ignores_the_consensus_book_floor():
    """A single book can still produce REAL arbitrage.

    min_consensus_books gates whether a median is a trustworthy probability
    estimate. Arbitrage needs no estimate, so the floor must not suppress it.
    """
    kalshi = [
        _k("A", 0.46, bid=0.44, ask=0.45, ask_size=50.0),
        _k("B", 0.54, bid=0.55, ask=0.57, ask_size=50.0, outcome="away"),
    ]
    consensus = [
        _c("A", 0.47, {"dk": -110.0}, n_books=1),
        _c("B", 0.53, {"dk": 130.0}, n_books=1, outcome="away"),
    ]
    status, _, _, _, _ = score_event(kalshi_quotes=kalshi, consensus_quotes=consensus)
    assert status is DivergenceStatus.INSUFFICIENT_CONSENSUS  # not scoreable...
    assert detect_arbitrage(kalshi, consensus) is not None  # ...but still arbitrage


def test_arbitrage_requires_every_outcome_covered():
    """An uncovered outcome means the position carries risk, so it is not arb."""
    kalshi = [_k("A", 0.30, bid=0.29, ask=0.30, ask_size=100.0)]
    consensus = [_c("A", 0.31, {"dk": -110.0})]  # B never priced
    consensus.append(_c("B", 0.69, {}, outcome="away"))
    assert detect_arbitrage(kalshi, consensus) is None


def test_arbitrage_picks_the_best_book_not_the_median():
    """You place the bet at the best price available, not the consensus."""
    kalshi = [_k("A", 0.60, bid=0.59, ask=0.61, ask_size=10.0)]
    consensus = [
        _c("A", 0.60, {"dk": -200.0, "fd": -150.0}),
        _c("B", 0.40, {"dk": 180.0, "fd": 250.0}, outcome="away"),
    ]
    arb = detect_arbitrage(kalshi, consensus)
    assert arb is not None
    by_team = {leg.team: leg for leg in arb.legs}
    assert by_team["B"].venue == "fd"  # +250 beats +180
    assert abs(by_team["B"].implied_price - 100.0 / 350.0) < 1e-9


def test_arbitrage_reports_limiting_kalshi_depth():
    kalshi = [_k("A", 0.46, bid=0.44, ask=0.45, ask_size=37.0)]
    consensus = [
        _c("A", 0.47, {"dk": -110.0}),
        _c("B", 0.53, {"dk": 130.0}, outcome="away"),
    ]
    arb = detect_arbitrage(kalshi, consensus)
    assert arb.limiting_depth == 37.0


def test_best_trade_ranks_by_dollars_not_percentage():
    """Live Packers/Vikings: the lower percentage is the bigger trade.

    +0.9% on 1434 contracts is worth ~4x more than +1.9% on 170. Ranking by rate
    would name the smaller one best, and best_expected_value would then not be
    the best expected value on offer.
    """
    kalshi = [
        _k("Packers", 0.4802, bid=0.48, ask=0.49, bid_size=1434.0, ask_size=1434.0),
        _k("Vikings", 0.5198, bid=0.52, ask=0.53, bid_size=169.94, ask_size=169.94,
           outcome="away"),
    ]
    consensus = [
        _q("Packers", 0.4990, n_books=9),
        _q("Vikings", 0.5010, n_books=9, outcome="away"),
    ]
    _, _, _, rows, _ = score_event(kalshi_quotes=kalshi, consensus_quotes=consensus)
    ev = _event_divergence(rows)

    by_team = {r.team: r for r in rows}
    assert by_team["Vikings"].net_edge_after_spread > by_team["Packers"].net_edge_after_spread
    assert by_team["Packers"].expected_value_at_depth > by_team["Vikings"].expected_value_at_depth

    assert ev.best_trade.team == "Packers"  # dollars, not rate
    # The headline number must equal the max available, not some other leg's.
    assert ev.best_expected_value == max(
        r.expected_value_at_depth for r in rows if r.expected_value_at_depth is not None
    )


def test_best_trade_falls_back_to_rate_without_depth():
    kalshi = [
        _k("A", 0.50, bid=0.48, ask=0.49),
        _k("B", 0.50, bid=0.40, ask=0.42, outcome="away"),
    ]
    consensus = [
        _q("A", 0.55, n_books=9),
        _q("B", 0.45, n_books=9, outcome="away"),
    ]
    _, _, _, rows, _ = score_event(kalshi_quotes=kalshi, consensus_quotes=consensus)
    ev = _event_divergence(rows)
    assert ev.best_trade is not None
    assert ev.best_expected_value is None  # no depth -> no dollar figure claimed


# --- detail-view passthrough -------------------------------------------------


def test_book_prices_reach_the_outcome_row():
    """Per-book odds must survive into the API shape, not stop at arbitrage.

    "9 books" is abstract; nine named prices is not. The raw odds are already
    stored, so failing to carry them forward would be dropping signal we hold.
    """
    kalshi = [_k("Chiefs", 0.50, bid=0.49, ask=0.51)]
    consensus = [_c("Chiefs", 0.52, {"dk": -110.0, "fd": -105.0}, n_books=9)]
    _, _, _, rows, _ = score_event(kalshi_quotes=kalshi, consensus_quotes=consensus)
    assert rows[0].book_prices == {"dk": -110.0, "fd": -105.0}


def test_book_prices_present_even_when_unscored():
    """A thin consensus still shows its observed prices — that is the evidence
    for WHY it was not trusted."""
    kalshi = [_k("Chiefs", 0.50, bid=0.49, ask=0.51)]
    consensus = [_c("Chiefs", 0.52, {"dk": -110.0}, n_books=1)]
    status, _, _, rows, _ = score_event(kalshi_quotes=kalshi, consensus_quotes=consensus)
    assert status is DivergenceStatus.INSUFFICIENT_CONSENSUS
    assert rows[0].divergence is None  # score withheld...
    assert rows[0].book_prices == {"dk": -110.0}  # ...but observations shown
