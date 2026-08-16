"""Unit tests for the normalization logic (Phase 1 core)."""

from __future__ import annotations

import math

import pytest

from arbitrium.ingestion.normalize import (
    NormalizedSnapshot,
    american_to_probability,
    decimal_to_probability,
    kalshi_cents_to_probability,
    normalize_kalshi_event,
    normalize_odds_api_consensus,
    normalize_odds_api_h2h,
    strip_vig,
)


def _book(key, home_odds, away_odds, home="Kansas City Chiefs", away="Denver Broncos"):
    return {
        "key": key,
        "markets": [
            {"key": "h2h", "outcomes": [
                {"name": home, "price": home_odds},
                {"name": away, "price": away_odds},
            ]}
        ],
    }

APPROX = 1e-9


# ---------------------------------------------------------------------------
# American odds
# ---------------------------------------------------------------------------


def test_american_favorite_negative_odds():
    # -150 => 150 / (150 + 100) = 0.60
    assert american_to_probability(-150) == pytest.approx(0.60, abs=APPROX)


def test_american_underdog_positive_odds():
    # +150 => 100 / (150 + 100) = 0.40
    assert american_to_probability(150) == pytest.approx(0.40, abs=APPROX)


def test_american_even_money():
    assert american_to_probability(100) == pytest.approx(0.50, abs=APPROX)
    assert american_to_probability(-100) == pytest.approx(0.50, abs=APPROX)


def test_american_zero_raises():
    with pytest.raises(ValueError):
        american_to_probability(0)


# ---------------------------------------------------------------------------
# Decimal odds
# ---------------------------------------------------------------------------


def test_decimal_to_probability():
    assert decimal_to_probability(2.0) == pytest.approx(0.50, abs=APPROX)
    assert decimal_to_probability(4.0) == pytest.approx(0.25, abs=APPROX)


def test_decimal_invalid_raises():
    with pytest.raises(ValueError):
        decimal_to_probability(1.0)
    with pytest.raises(ValueError):
        decimal_to_probability(0.5)


# ---------------------------------------------------------------------------
# Kalshi cents
# ---------------------------------------------------------------------------


def test_kalshi_cents_to_probability():
    assert kalshi_cents_to_probability(65) == pytest.approx(0.65, abs=APPROX)
    assert kalshi_cents_to_probability(0) == 0.0
    assert kalshi_cents_to_probability(100) == 1.0


@pytest.mark.parametrize("bad", [-1, 101, 150])
def test_kalshi_cents_out_of_range_raises(bad):
    with pytest.raises(ValueError):
        kalshi_cents_to_probability(bad)


# ---------------------------------------------------------------------------
# Vig stripping
# ---------------------------------------------------------------------------


def test_strip_vig_normalizes_to_one():
    # Two -110 sides: each raw ~0.5238, sum ~1.0476 (the ~4.76% overround).
    home_raw = american_to_probability(-110)
    away_raw = american_to_probability(-110)
    cleaned = strip_vig([home_raw, away_raw])
    assert sum(cleaned) == pytest.approx(1.0, abs=APPROX)
    assert cleaned[0] == pytest.approx(0.50, abs=APPROX)
    assert cleaned[1] == pytest.approx(0.50, abs=APPROX)


def test_strip_vig_preserves_relative_weight():
    cleaned = strip_vig([0.60, 0.30])  # 2:1 ratio
    assert sum(cleaned) == pytest.approx(1.0, abs=APPROX)
    assert cleaned[0] == pytest.approx(2 / 3, abs=APPROX)
    assert cleaned[1] == pytest.approx(1 / 3, abs=APPROX)


def test_strip_vig_nonpositive_raises():
    with pytest.raises(ValueError):
        strip_vig([0.0, 0.0])


def test_strip_vig_is_n_way():
    # Three independent Yes prices that don't sum to 1 (soccer overround).
    cleaned = strip_vig([0.50, 0.32, 0.25])
    assert len(cleaned) == 3
    assert sum(cleaned) == pytest.approx(1.0, abs=APPROX)
    # Relative ordering preserved: home > away > draw.
    assert cleaned[0] > cleaned[1] > cleaned[2]


# ---------------------------------------------------------------------------
# Unified Kalshi event normalization (N per-outcome markets)
# ---------------------------------------------------------------------------


def _binary_markets():
    # Two independent per-team books (live API shape). liquidity_dollars = resting
    # depth (feeds liquidity_score); volume_fp = traded volume (preserved in
    # order_book_depth only).
    return {
        "home": {"ticker": "KXNFLGAME-26SEP14DENKC-KC", "yes_bid_dollars": "0.5700",
                 "yes_ask_dollars": "0.5900", "liquidity_dollars": "1500.00",
                 "volume_fp": "3123.22"},
        "away": {"ticker": "KXNFLGAME-26SEP14DENKC-DEN", "yes_bid_dollars": "0.4100",
                 "yes_ask_dollars": "0.4300", "liquidity_dollars": "60.00",
                 "volume_fp": "1707.71"},
    }


def test_event_binary_two_markets_normalize_to_one():
    snaps = normalize_kalshi_event(_binary_markets(), kalshi_event_ticker="KXNFLGAME-26SEP14DENKC")
    assert {s.outcome for s in snaps} == {"home", "away"}
    by = {s.outcome: s for s in snaps}
    # Home mid $0.58, away mid $0.42; sum 1.00 here, normalized to 1 either way.
    assert sum(s.implied_probability for s in snaps) == pytest.approx(1.0, abs=APPROX)
    assert by["home"].implied_probability == pytest.approx(0.58 / 1.00, abs=APPROX)
    assert by["away"].implied_probability == pytest.approx(0.42 / 1.00, abs=APPROX)
    assert all(s.source == "kalshi" and s.price_format == "probability" for s in snaps)
    assert all(s.kalshi_event_ticker == "KXNFLGAME-26SEP14DENKC" for s in snaps)


def test_event_binary_strips_cross_book_overround():
    # Two independent books that do NOT sum to 1 (home $0.60 + away $0.45 = 1.05).
    markets = {
        "home": {"ticker": "E-A", "yes_bid_dollars": "0.59", "yes_ask_dollars": "0.61"},
        "away": {"ticker": "E-B", "yes_bid_dollars": "0.44", "yes_ask_dollars": "0.46"},
    }
    snaps = normalize_kalshi_event(markets, kalshi_event_ticker="E")
    assert sum(s.implied_probability for s in snaps) == pytest.approx(1.0, abs=APPROX)
    by = {s.outcome: s for s in snaps}
    assert by["home"].implied_probability == pytest.approx(0.60 / 1.05, abs=APPROX)
    # raw_price preserves each outcome's own Yes cents, pre-normalization.
    assert by["home"].raw_price == pytest.approx(60.0, abs=APPROX)
    assert by["away"].raw_price == pytest.approx(45.0, abs=APPROX)


def test_event_binary_liquidity_is_minimum_resting_depth():
    snaps = normalize_kalshi_event(_binary_markets(), kalshi_event_ticker="E")
    # Weakest-link across the two books' RESTING depth (1500, 60) => 60.
    # volume_fp (3123/1707) is NOT used for liquidity_score.
    assert all(s.liquidity_score == 60 for s in snaps)


def test_event_preserves_volume_and_bidask_in_order_book_depth():
    snaps = normalize_kalshi_event(_binary_markets(), kalshi_event_ticker="E")
    by = {s.outcome: s for s in snaps}
    depth = by["home"].order_book_depth
    # Volume preserved as a raw signal, separate from liquidity_score.
    assert depth["volume_fp"] == pytest.approx(3123.22, abs=APPROX)
    assert depth["yes_bid"] == pytest.approx(0.57, abs=APPROX)
    assert depth["yes_ask"] == pytest.approx(0.59, abs=APPROX)


def test_nodet_market_extraction_precedence():
    # Regression for the real KXNFLGAME-26SEP13NODET-NO payload. The live market
    # carries liquidity_dollars="0.0000" (thin resting book) alongside real
    # volume. Confirms: price from *_dollars mid; liquidity_score = resting depth
    # (0.0, NOT volume); volume preserved in order_book_depth.
    from arbitrium.ingestion.normalize import (
        _kalshi_yes_probability,
        _market_liquidity,
        _order_book_depth,
    )

    market = {
        "ticker": "KXNFLGAME-26SEP13NODET-NO",
        "yes_bid_dollars": "0.2400", "yes_ask_dollars": "0.2800",
        "liquidity_dollars": "0.0000",
        "open_interest_fp": "3573.02", "volume_fp": "5201.32",
    }
    assert _kalshi_yes_probability(market) == pytest.approx(0.26, abs=APPROX)
    assert _market_liquidity(market) == pytest.approx(0.0, abs=APPROX)  # resting depth, not volume
    depth = _order_book_depth(market)
    assert depth["volume_fp"] == pytest.approx(5201.32, abs=APPROX)
    assert depth["open_interest_fp"] == pytest.approx(3573.02, abs=APPROX)


def _three_way_markets():
    # Three independent books with dollar-STRING Yes mids 0.50 / 0.32 / 0.25
    # (sum 1.07 overround). liquidity_dollars = resting depth (feeds liquidity_score).
    return {
        "home": {"ticker": "KXMLSGAME-CHIVAN-CHI", "yes_bid_dollars": "0.4900",
                 "yes_ask_dollars": "0.5100", "liquidity_dollars": "1000.00"},
        "away": {"ticker": "KXMLSGAME-CHIVAN-VAN", "yes_bid_dollars": "0.3100",
                 "yes_ask_dollars": "0.3300", "liquidity_dollars": "50.00"},
        "draw": {"ticker": "KXMLSGAME-CHIVAN-TIE", "yes_bid_dollars": "0.2400",
                 "yes_ask_dollars": "0.2600", "liquidity_dollars": "800.00"},
    }


def test_event_three_way_normalizes_independent_prices_to_one():
    snaps = normalize_kalshi_event(_three_way_markets(), kalshi_event_ticker="KXMLSGAME-CHIVAN")
    assert {s.outcome for s in snaps} == {"home", "away", "draw"}
    assert sum(s.implied_probability for s in snaps) == pytest.approx(1.0, abs=APPROX)
    by = {s.outcome: s for s in snaps}
    assert by["home"].implied_probability == pytest.approx(0.50 / 1.07, abs=APPROX)
    assert by["away"].implied_probability == pytest.approx(0.32 / 1.07, abs=APPROX)
    assert by["draw"].implied_probability == pytest.approx(0.25 / 1.07, abs=APPROX)


def test_event_three_way_liquidity_is_minimum_and_ignores_unknown():
    m = _three_way_markets()
    snaps = normalize_kalshi_event(m, kalshi_event_ticker="X")
    assert all(s.liquidity_score == 50 for s in snaps)  # min(1000, 50, 800)
    m["home"].pop("liquidity_dollars")  # unknown resting depth on one book
    snaps2 = normalize_kalshi_event(m, kalshi_event_ticker="X")
    assert all(s.liquidity_score == 50 for s in snaps2)  # min over known (50, 800)


def test_event_raises_when_a_book_has_no_price():
    m = _binary_markets()
    m["away"] = {"ticker": "no-price"}
    with pytest.raises(ValueError):
        normalize_kalshi_event(m, kalshi_event_ticker="X")


def test_event_raises_with_fewer_than_two_markets():
    with pytest.raises(ValueError):
        normalize_kalshi_event({"home": _binary_markets()["home"]}, kalshi_event_ticker="X")


# ---------------------------------------------------------------------------
# Sportsbook (Odds API) normalization — vig stripped at ingestion
# ---------------------------------------------------------------------------


def test_normalize_odds_api_strips_vig_and_preserves_raw():
    snaps = normalize_odds_api_h2h(
        odds_api_event_id="evt123",
        source="draftkings",
        home_odds_american=-110,
        away_odds_american=-110,
    )
    assert len(snaps) == 2
    home = next(s for s in snaps if s.outcome == "home")
    away = next(s for s in snaps if s.outcome == "away")

    # Clean probabilities sum to exactly 1 (vig removed at ingestion time).
    assert home.implied_probability + away.implied_probability == pytest.approx(1.0, abs=APPROX)
    assert home.implied_probability == pytest.approx(0.50, abs=APPROX)
    # Raw American odds preserved for audit; price_format tags the original.
    assert home.raw_price == -110
    assert home.price_format == "american"
    assert home.odds_api_event_id == "evt123"
    assert home.source == "draftkings"


def test_normalize_odds_api_asymmetric_line():
    # Favorite -200 (raw 0.6667) vs underdog +170 (raw 0.3704); sum ~1.037 vig.
    snaps = normalize_odds_api_h2h(
        odds_api_event_id="evt",
        source="fanduel",
        home_odds_american=-200,
        away_odds_american=170,
    )
    total = sum(s.implied_probability for s in snaps)
    assert total == pytest.approx(1.0, abs=APPROX)
    home = next(s for s in snaps if s.outcome == "home")
    # Home stays the favorite after stripping vig.
    assert home.implied_probability > 0.5


# ---------------------------------------------------------------------------
# Sportsbook consensus (median of vig-stripped per-book probabilities)
# ---------------------------------------------------------------------------


def test_consensus_median_two_books():
    snaps = normalize_odds_api_consensus(
        odds_api_event_id="evt",
        home_team="Kansas City Chiefs",
        away_team="Denver Broncos",
        bookmakers=[_book("draftkings", -150, 130), _book("fanduel", -145, 125)],
    )
    assert {s.outcome for s in snaps} == {"home", "away"}
    assert all(s.source == "consensus" and s.price_format == "consensus" for s in snaps)
    # Proper distribution after re-normalizing the two medians.
    assert sum(s.implied_probability for s in snaps) == pytest.approx(1.0, abs=APPROX)
    home = next(s for s in snaps if s.outcome == "home")
    assert home.implied_probability > 0.5  # KC is the favorite in both books
    # Raw per-book American prices preserved as a signal.
    assert home.order_book_depth == {"n_books": 2, "books_american": {"draftkings": -150.0, "fanduel": -145.0}}


def test_consensus_median_ignores_outlier_book():
    # Two clustered books (~-150) + one wild outlier (-900). Median must track the
    # cluster, not get dragged toward the outlier the way a mean would.
    snaps = normalize_odds_api_consensus(
        odds_api_event_id="evt",
        home_team="Kansas City Chiefs",
        away_team="Denver Broncos",
        bookmakers=[
            _book("a", -150, 130),
            _book("b", -150, 130),
            _book("outlier", -900, 600),
        ],
    )
    home = next(s for s in snaps if s.outcome == "home")
    # Clustered books imply ~0.58; a mean would be pulled toward ~0.86.
    assert home.implied_probability < 0.62
    assert home.order_book_depth["n_books"] == 3


def test_consensus_skips_book_missing_team_or_market():
    snaps = normalize_odds_api_consensus(
        odds_api_event_id="evt",
        home_team="Kansas City Chiefs",
        away_team="Denver Broncos",
        bookmakers=[
            _book("good", -150, 130),
            {"key": "no_h2h", "markets": [{"key": "spreads", "outcomes": []}]},
            _book("wrong_team", -150, 130, home="Los Angeles Rams"),  # home team absent
        ],
    )
    home = next(s for s in snaps if s.outcome == "home")
    assert home.order_book_depth["n_books"] == 1  # only the usable book counted


def test_consensus_no_usable_book_raises():
    with pytest.raises(ValueError):
        normalize_odds_api_consensus(
            odds_api_event_id="evt",
            home_team="Kansas City Chiefs",
            away_team="Denver Broncos",
            bookmakers=[{"key": "x", "markets": []}],
        )


# ---------------------------------------------------------------------------
# Dataclass sanity
# ---------------------------------------------------------------------------


def test_normalized_snapshot_is_frozen():
    snap = NormalizedSnapshot(
        source="kalshi",
        outcome="home",
        implied_probability=0.5,
        price_format="probability",
    )
    with pytest.raises((AttributeError, TypeError)):
        snap.implied_probability = 0.6  # type: ignore[misc]
    assert math.isclose(snap.implied_probability, 0.5)
