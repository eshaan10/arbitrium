"""Normalization: raw source data -> the common odds-snapshot schema.

This module is deliberately pure (no network, no DB) so it can be unit-tested in
isolation — it is the tested core of Phase 1.

Common schema (per NormalizedSnapshot):
    {source, outcome, implied_probability, raw_price, price_format,
     liquidity_score, order_book_depth}

Design notes
------------
* Sportsbook vig is stripped **at ingestion time** (see ``strip_vig``): the
  stored ``implied_probability`` is clean, while ``raw_price`` + ``price_format``
  preserve the original for audit. We never defer vig removal to query time.
* ``strip_vig`` is N-way: it sums *all* inputs and divides, so it is correct for
  two-way (home/away) and three-way (home/away/draw) markets alike.
* Every Kalshi game is an EVENT with one independent binary market per outcome
  (2 for NFL/NBA, 3 for soccer), each its own order book. Their Yes prices do
  not sum to 1, so we strip the cross-market overround via ``strip_vig`` — see
  the single ``normalize_kalshi_event``. (This replaced the earlier
  binary/three-way split once the live API confirmed binary games are also
  multi-market.)
* v1 handles moneylines only. Outcomes: 'home' | 'away' and additionally 'draw'
  for three-way soccer.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Common schema
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NormalizedSnapshot:
    """One normalized price observation, ready to be written to odds_snapshots.

    Event linkage (``kalshi_event_ticker`` / ``odds_api_event_id``) is carried
    here so the ingestion layer can resolve it to an ``event_id`` before insert.
    """

    source: str
    outcome: str  # 'home' | 'away' | 'draw' (draw only for three-way soccer)
    implied_probability: float  # 0.0 – 1.0, vig-stripped
    price_format: str  # 'probability' | 'american' | 'decimal'
    raw_price: float | None = None
    liquidity_score: float | None = None
    order_book_depth: dict | None = None
    kalshi_event_ticker: str | None = None
    odds_api_event_id: str | None = None


# ---------------------------------------------------------------------------
# Pure price converters
# ---------------------------------------------------------------------------


def american_to_probability(odds: int | float) -> float:
    """Convert American odds to a raw (pre-vig-strip) implied probability."""
    if odds == 0:
        raise ValueError("American odds cannot be zero")
    o = float(odds)
    if o > 0:
        return 100.0 / (o + 100.0)
    return -o / (-o + 100.0)


def decimal_to_probability(decimal_odds: float) -> float:
    """Convert decimal odds to a raw implied probability."""
    if decimal_odds <= 1.0:
        raise ValueError("Decimal odds must be > 1.0")
    return 1.0 / decimal_odds


def kalshi_cents_to_probability(cents: float) -> float:
    """Convert a Kalshi contract price (0–100 cents) to an implied probability."""
    if not 0.0 <= cents <= 100.0:
        raise ValueError("Kalshi price must be between 0 and 100 cents")
    return cents / 100.0


def strip_vig(probabilities: Sequence[float]) -> list[float]:
    """Remove the bookmaker overround by normalizing probabilities to sum to 1.

    Standard approach: divide each side by the total implied probability. The
    inputs typically sum to > 1 for a sportsbook (that excess is the vig).
    """
    total = sum(probabilities)
    if total <= 0:
        raise ValueError("Sum of probabilities must be positive")
    return [p / total for p in probabilities]


# ---------------------------------------------------------------------------
# Source normalizers
# ---------------------------------------------------------------------------


def _coerce_price(value: object) -> float | None:
    """Parse a Kalshi numeric field that may be a string, a number, or None.

    Kalshi's live API returns prices/volumes as strings (e.g. "0.2400",
    "5201.32"); older responses used ints/floats. Returns None for missing or
    unparseable values rather than raising.
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _yes_prices_in_probability(market: dict) -> tuple[float | None, float | None, float | None]:
    """Return (bid, ask, last) for the Yes side, each on the 0–1 probability scale.

    Prefers the live dollar-denominated fields (``yes_bid_dollars`` etc., strings
    already on the 0–1 scale, e.g. "0.2400" == $0.24 == prob 0.24). Falls back
    per-field to the legacy integer-cent fields (``yes_bid`` = 24), converting
    cents -> probability by dividing by 100.
    """
    bid = _coerce_price(market.get("yes_bid_dollars"))
    ask = _coerce_price(market.get("yes_ask_dollars"))
    last = _coerce_price(market.get("last_price_dollars"))

    if bid is None:
        cents = _coerce_price(market.get("yes_bid"))
        bid = cents / 100.0 if cents is not None else None
    if ask is None:
        cents = _coerce_price(market.get("yes_ask"))
        ask = cents / 100.0 if cents is not None else None
    if last is None:
        cents = _coerce_price(market.get("last_price"))
        last = cents / 100.0 if cents is not None else None

    return bid, ask, last


def _kalshi_yes_probability(market: dict) -> float:
    """Mid-market implied probability of the Yes side, in [0, 1].

    Prefers the bid/ask midpoint (from whichever price source is available);
    falls back to the last price. Handles both the live dollar-string fields and
    legacy cent fields via :func:`_yes_prices_in_probability`.
    """
    bid, ask, last = _yes_prices_in_probability(market)
    if bid is not None and ask is not None:
        prob = (bid + ask) / 2.0
    elif last is not None:
        prob = last
    else:
        raise ValueError(f"Kalshi market {market.get('ticker')!r} has no usable price")

    if not 0.0 <= prob <= 1.0:
        raise ValueError(
            f"Kalshi market {market.get('ticker')!r} produced out-of-range "
            f"probability {prob!r}"
        )
    return prob


# liquidity_score is RESTING order-book depth at best bid/ask ONLY — the live
# ``liquidity_dollars`` field (older payloads: ``liquidity``). We deliberately do
# NOT fall through to traded volume: that would silently redefine what
# liquidity_score means. Volume is preserved separately in order_book_depth (see
# _order_book_depth) so Phase 2 confidence scoring can combine resting depth and
# volume deliberately.
_LIQUIDITY_FIELDS = ("liquidity_dollars", "liquidity")


def _market_liquidity(market: dict) -> float | None:
    """Resting order-book liquidity ($ at best bid/ask) for one Kalshi market.

    Returns None only if no resting-depth field is present. A present-but-zero
    value (a thin/dormant book) is returned as 0.0 — an honest low-confidence
    signal, not treated as missing.
    """
    for field in _LIQUIDITY_FIELDS:
        value = _coerce_price(market.get(field))
        if value is not None:
            return value
    return None


def _order_book_depth(market: dict) -> dict | None:
    """Raw per-outcome book/volume signals, preserved in
    ``odds_snapshots.order_book_depth`` (JSONB).

    Keeps best bid/ask (and their sizes), traded volume, and open interest as raw
    signals alongside — but separate from — ``liquidity_score``. This lets Phase
    2's divergence/confidence scoring combine resting depth with volume on its own
    terms, rather than the ingestion layer silently collapsing them into one
    number. Returns None if the market carries none of these fields.
    """
    raw = {
        "yes_bid": _coerce_price(market.get("yes_bid_dollars")),
        "yes_ask": _coerce_price(market.get("yes_ask_dollars")),
        "yes_bid_size": _coerce_price(market.get("yes_bid_size_fp")),
        "yes_ask_size": _coerce_price(market.get("yes_ask_size_fp")),
        "volume_fp": _coerce_price(market.get("volume_fp")),
        "open_interest_fp": _coerce_price(market.get("open_interest_fp")),
    }
    cleaned = {k: v for k, v in raw.items() if v is not None}
    return cleaned or None


def _min_liquidity(markets: Sequence[dict]) -> float | None:
    """Minimum liquidity across several markets (weakest-link confidence).

    A three-way divergence is only as trustworthy as its thinnest book, so we
    take the MIN — never an average — so one deep book can't lend false
    confidence to two thin ones. Markets with unknown (None) liquidity are
    ignored here; if all are unknown the result is None. (v1 limitation: an
    unknown book is not treated as zero liquidity.)
    """
    known = [liq for liq in (_market_liquidity(m) for m in markets) if liq is not None]
    return min(known) if known else None


def normalize_kalshi_event(
    outcome_markets: dict[str, dict],
    *,
    kalshi_event_ticker: str,
) -> list[NormalizedSnapshot]:
    """Normalize one Kalshi game (an event with N per-outcome markets).

    The real Kalshi structure — confirmed against the live API — is that every
    game is an *event* containing one INDEPENDENT binary market per outcome, each
    with its own order book:
        - binary sports (NFL/NBA): 2 markets → outcomes 'home', 'away'
        - three-way (soccer):      3 markets → outcomes 'home', 'away', 'draw'

    Because the per-outcome books are priced independently, their Yes prices do
    not sum to 1; we strip the cross-market overround by normalizing all of them
    via ``strip_vig`` (N-way). The returned ``implied_probability`` values sum
    to 1. This one function replaces the earlier binary/three-way split — there
    is a single normalization model, parameterized only by how many outcomes the
    event has.

    ``outcome_markets`` maps an outcome label ('home' | 'away' | 'draw') to that
    outcome's raw Kalshi market dict. The ingestion layer builds this mapping
    from event metadata (which team is home/away, which market is the draw).

    ``raw_price`` preserves each outcome's own Yes price (cents, pre-normalization)
    for audit. ``liquidity_score`` is the MINIMUM resting depth across the event's
    books (weakest-link confidence): every outcome inherits the same min, so one
    deep book cannot lend false confidence to a game whose other books are thin.
    ``order_book_depth`` keeps each outcome's own raw bid/ask + volume signals.
    """
    if len(outcome_markets) < 2:
        raise ValueError(
            f"Kalshi event {kalshi_event_ticker!r} needs >= 2 outcome markets, "
            f"got {len(outcome_markets)}"
        )

    outcomes = list(outcome_markets)  # stable order for the strip_vig round-trip
    yes_probs = [_kalshi_yes_probability(outcome_markets[o]) for o in outcomes]
    normalized = strip_vig(yes_probs)
    liquidity = _min_liquidity([outcome_markets[o] for o in outcomes])

    return [
        NormalizedSnapshot(
            source="kalshi",
            outcome=outcome,
            implied_probability=norm,
            price_format="probability",
            raw_price=raw_yes * 100.0,  # this outcome's own Yes cents, pre-normalization
            liquidity_score=liquidity,
            order_book_depth=_order_book_depth(outcome_markets[outcome]),
            kalshi_event_ticker=kalshi_event_ticker,
        )
        for outcome, raw_yes, norm in zip(outcomes, yes_probs, normalized)
    ]


def normalize_odds_api_h2h(
    *,
    odds_api_event_id: str,
    source: str,
    home_odds_american: int | float,
    away_odds_american: int | float,
) -> list[NormalizedSnapshot]:
    """Normalize a sportsbook head-to-head (moneyline) market.

    Vig is stripped **here**, at ingestion time: the stored
    ``implied_probability`` is clean while ``raw_price`` preserves the original
    American odds for audit. (Wired up for use in Phase 2; the logic is pure and
    tested now.)
    """
    home_raw = american_to_probability(home_odds_american)
    away_raw = american_to_probability(away_odds_american)
    home_clean, away_clean = strip_vig([home_raw, away_raw])

    return [
        NormalizedSnapshot(
            source=source,
            outcome="home",
            implied_probability=home_clean,
            price_format="american",
            raw_price=float(home_odds_american),
            odds_api_event_id=odds_api_event_id,
        ),
        NormalizedSnapshot(
            source=source,
            outcome="away",
            implied_probability=away_clean,
            price_format="american",
            raw_price=float(away_odds_american),
            odds_api_event_id=odds_api_event_id,
        ),
    ]


def normalize_odds_api_consensus(
    *,
    odds_api_event_id: str,
    home_team: str,
    away_team: str,
    bookmakers: Sequence[dict],
) -> list[NormalizedSnapshot]:
    """Aggregate multiple bookmakers' h2h odds into a single consensus per outcome.

    For each book we vig-strip its two-way h2h prices (``strip_vig``), then take
    the MEDIAN of the per-book probabilities per outcome — median rather than mean
    so one mispriced/outlier book can't drag the consensus. The two medians are
    re-normalized to a proper distribution (independent medians need not sum to 1).

    ``source='consensus'``; the raw per-book American prices and the book count
    are preserved in ``order_book_depth`` (same keep-the-raw-signal principle as
    Kalshi), so nothing about the underlying books is lost. Team identity is
    attached by the ingestion layer (home_team/away_team here are authoritative).
    """
    home_probs: list[float] = []
    away_probs: list[float] = []
    home_books: dict[str, float] = {}
    away_books: dict[str, float] = {}

    for book in bookmakers:
        h2h = next((m for m in book.get("markets", []) if m.get("key") == "h2h"), None)
        if h2h is None:
            continue
        prices = {o.get("name"): o.get("price") for o in h2h.get("outcomes", [])}
        home_odds, away_odds = prices.get(home_team), prices.get(away_team)
        if home_odds is None or away_odds is None:
            continue
        home_clean, away_clean = strip_vig(
            [american_to_probability(home_odds), american_to_probability(away_odds)]
        )
        home_probs.append(home_clean)
        away_probs.append(away_clean)
        key = book.get("key", f"book{len(home_books)}")
        home_books[key] = float(home_odds)
        away_books[key] = float(away_odds)

    if not home_probs:
        raise ValueError(
            f"Odds API event {odds_api_event_id!r} has no usable h2h bookmaker"
        )

    home_med = statistics.median(home_probs)
    away_med = statistics.median(away_probs)
    home_final, away_final = strip_vig([home_med, away_med])
    n_books = len(home_probs)

    return [
        NormalizedSnapshot(
            source="consensus",
            outcome="home",
            implied_probability=home_final,
            price_format="consensus",
            raw_price=None,  # no single raw price; per-book odds live in depth
            order_book_depth={"n_books": n_books, "books_american": home_books},
            odds_api_event_id=odds_api_event_id,
        ),
        NormalizedSnapshot(
            source="consensus",
            outcome="away",
            implied_probability=away_final,
            price_format="consensus",
            raw_price=None,
            order_book_depth={"n_books": n_books, "books_american": away_books},
            odds_api_event_id=odds_api_event_id,
        ),
    ]
