"""Divergence scoring: Kalshi vs sportsbook consensus, per outcome.

The comparison joins the two sources on TEAM identity, never on home/away.
Kalshi's home/away is provisional ticker ordering and can be flipped later by The
Odds API, while ``odds_snapshots.team`` is correct at write time and immutable
(see migration 0005) — so a row's team is the only thing that means the same
before and after an authoritative flip. 'draw' outcomes carry no team and are
keyed by outcome instead.

Nothing is silently dropped. Every event with at least one source is returned,
carrying an explicit status that says how much to trust it:

  * ``scored`` — both sources present and the consensus clears
    ``settings.min_consensus_books``. This is the only status with a divergence
    number.
  * ``single_source_no_divergence`` — only one source priced this game (e.g. NFL
    preseason, which Kalshi lists but The Odds API's regular-season key does not
    cover). There is nothing to diverge FROM; saying so is more honest than
    omitting the game and letting the caller assume it doesn't exist.
  * ``insufficient_consensus`` — both sources present, but the "consensus" is a
    median over fewer than ``min_consensus_books`` bookmakers. Far from kickoff
    most events have exactly one book quoting, and a divergence measured against
    one book is noise wearing a precise-looking number. The observed prices are
    still returned (they are real observations); the SCORE is withheld, because a
    number that exists will get used regardless of the badge next to it.
  * ``incomparable_outcomes`` — both sources present but their outcome keys don't
    line up (a team resolved differently on each side). A real data bug; flagged
    loudly rather than scored across mismatched outcomes.

Divergence and net edge are TWO AXES, never collapsed into one number
(design principle 2):

* **Divergence** compares vig-stripped mid probabilities. It measures how far
  apart the two sources' beliefs are — the right input for Phase 3 calibration,
  which needs every disagreement graded, including ones nobody could trade.
* **Net edge after spread** compares the consensus probability against Kalshi's
  RAW executable bid/ask. A Kalshi contract settles at $1, so its dollar price is
  already a probability; vig-stripping it here would be wrong, because you
  transact at the touch, not at a normalised mid.

These routinely disagree. On live NFL data most outcomes show a real divergence
that is SMALLER than the spread needed to capture it — a correct measurement of
a genuine disagreement that is nevertheless worth nothing. Reporting only the
divergence would make those look like opportunities.

Design principles 1 and 3 are the whole point of this module: uncertainty is
labelled, not filtered, and no probability is emitted without the context needed
to judge it.
"""

from __future__ import annotations

import uuid as uuid_mod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from sqlalchemy import select
from sqlalchemy.orm import Session

from arbitrium.config import settings
from arbitrium.db.models import Event, OddsSnapshot
from arbitrium.ingestion.normalize import american_to_probability

KALSHI_SOURCE = "kalshi"
CONSENSUS_SOURCE = "consensus"


class DivergenceStatus(str, Enum):
    SCORED = "scored"
    SINGLE_SOURCE = "single_source_no_divergence"
    INSUFFICIENT_CONSENSUS = "insufficient_consensus"
    INCOMPARABLE = "incomparable_outcomes"


@dataclass(frozen=True)
class OutcomeQuote:
    """One source's latest observation for one outcome of one event."""

    outcome: str  # 'home' | 'away' | 'draw' (provisional for Kalshi)
    team: str | None  # canonical; None for 'draw'
    implied_probability: float
    snapshot_time: datetime
    n_books: int | None = None  # consensus only: bookmakers behind the median

    # Kalshi only: the EXECUTABLE side of the book. These are raw dollar prices,
    # deliberately NOT vig-stripped — see the module docstring on why the two
    # numbers answer different questions.
    bid: float | None = None
    ask: float | None = None
    bid_size: float | None = None
    ask_size: float | None = None

    # Consensus only: each individual book's RAW American odds, vig included.
    # Arbitrage has to price off these, never off implied_probability — see
    # :func:`detect_arbitrage`.
    book_prices: dict[str, float] | None = None

    @property
    def join_key(self) -> str:
        """Team identity, falling back to outcome for team-less outcomes ('draw')."""
        return self.team if self.team is not None else f"__{self.outcome}__"

    @property
    def spread(self) -> float | None:
        """Cost of crossing this book, in probability terms."""
        if self.bid is None or self.ask is None:
            return None
        return self.ask - self.bid

    @property
    def resting_depth(self) -> float | None:
        """Weakest-link resting size at the touch.

        A NEW measure, deliberately not a redefinition of the stored
        ``liquidity_score``: that column means Kalshi's ``liquidity_dollars``
        field and keeps meaning exactly that, so no already-written row changes
        meaning. ``liquidity_dollars`` happens to be 0 on every observed market
        while real size rests at the touch, so this is derived from the sizes
        preserved in ``order_book_depth`` instead. Weakest-link (min of the two
        sides) matches how the ingestion layer already treats depth: one deep
        side cannot lend false confidence to a book you can't get out of.
        """
        sizes = [s for s in (self.bid_size, self.ask_size) if s is not None]
        return min(sizes) if sizes else None


@dataclass(frozen=True)
class OutcomeDivergence:
    """Per-outcome comparison.

    Two independent axes, never conflated (design principle 2):

    * ``divergence`` — how far apart the two sources' BELIEFS are, comparing
      vig-stripped mid probabilities. A measurement.
    * ``net_edge_after_spread`` — what is actually capturable after paying to
      cross Kalshi's book, comparing the consensus probability against the raw
      executable bid/ask. A trade.

    A large divergence with a negative net edge is a real, correctly-measured
    disagreement that you cannot profit from. Both numbers are reported; neither
    is allowed to stand in for the other.
    """

    join_key: str
    team: str | None
    kalshi_probability: float | None
    consensus_probability: float | None
    divergence: float | None  # kalshi - consensus; >0 = Kalshi prices it higher

    # Execution axis. None when the book side is unknown or the event is unscored.
    net_edge_after_spread: float | None = None
    trade_side: str | None = None  # 'buy_kalshi' | 'sell_kalshi'
    spread: float | None = None
    resting_depth: float | None = None

    # Raw per-book American odds behind the consensus median. Carried through so
    # "9 books" can be shown as nine named prices rather than an abstract count —
    # the same keep-the-raw-signal principle that preserves raw_price beside the
    # stripped probability.
    book_prices: dict[str, float] | None = None

    # Kalshi's executable touch, in dollars. Needed to say "buy at 49¢" rather
    # than only reporting an abstract edge. ask_size/bid_size are kept separate
    # from `resting_depth` (their minimum) because sizing a BUY depends on the
    # side you actually hit, not on the weaker of the two.
    kalshi_bid: float | None = None
    kalshi_ask: float | None = None
    kalshi_bid_size: float | None = None
    kalshi_ask_size: float | None = None

    @property
    def abs_divergence(self) -> float | None:
        return None if self.divergence is None else abs(self.divergence)

    @property
    def tradeable(self) -> bool:
        """Whether any edge survives crossing the spread."""
        return self.net_edge_after_spread is not None and self.net_edge_after_spread > 0

    @property
    def expected_value_at_depth(self) -> float | None:
        """Capturable edge scaled by the size actually resting at that price.

        A percentage edge says nothing about whether the trade is worth making.
        Live NFL books routinely offer a ~1.9% edge against 3.5 contracts of
        resting size — around six cents of expected profit, which is economically
        noise wearing a respectable-looking percentage.

        Deliberately a REPORTED NUMBER, not a gate. A minimum-depth floor would be
        a third magic threshold needing its own justification, and would go stale
        as liquidity builds toward kickoff; multiplying by depth makes a thin
        opportunity visibly small without inventing a cutoff. Same reasoning as
        keeping divergence and net edge on separate axes.

        Units are contract-dollars: a Kalshi contract settles at $1, so
        ``edge x contracts`` is the expected dollar profit on filling the whole
        resting size. None when either input is unknown; 0 or negative when the
        edge is not capturable.
        """
        if self.net_edge_after_spread is None or self.resting_depth is None:
            return None
        return self.net_edge_after_spread * self.resting_depth


@dataclass(frozen=True)
class EventDivergence:
    event_id: uuid_mod.UUID
    sport: str
    league: str
    home_team: str
    away_team: str
    scheduled_start: datetime
    status: DivergenceStatus
    reason: str
    sources: list[str]
    n_books: int | None
    max_abs_divergence: float | None
    outcomes: list[OutcomeDivergence]

    # Provenance. `home_away_source` says whether home/away is still Kalshi's
    # provisional ticker ordering or has been confirmed against The Odds API —
    # which is exactly the distinction that makes `team` the stable join anchor.
    home_away_source: str | None = None
    kalshi_event_ticker: str | None = None
    odds_api_event_id: str | None = None

    # The Kalshi-native directional view. None when no side is mispriced, or when
    # the consensus is not trustworthy enough to compare against.
    recommendation: KalshiRecommendation | None = None

    @property
    def kalshi_series(self) -> str | None:
        """Series ticker, for linking out to the Kalshi market."""
        if not self.kalshi_event_ticker or "-" not in self.kalshi_event_ticker:
            return None
        return self.kalshi_event_ticker.split("-", 1)[0]
    # Independent of `status`: arbitrage needs no probability estimate, so it is
    # checked even when the consensus is too thin to score a divergence against.
    arbitrage: Arbitrage | None = None

    @property
    def best_net_edge(self) -> float | None:
        """Best capturable edge across this event's outcomes, if any book is known.

        MAX, never a sum, and this is a correctness requirement rather than a
        conservative choice. An event's outcomes are mutually exclusive, so their
        per-outcome rows are ALTERNATIVE EXECUTIONS of the same directional view,
        not independent opportunities. Selling Yes on one side of a two-way market
        is economically the same position as buying Yes on the other, at a
        possibly better price — which is exactly why both rows can show a positive
        edge at once. Adding them would double-count a single bet.

        (Observed live: Packers/Vikings showed +0.90% buying the Packers' book and
        +1.90% selling the Vikings' book. One position, two routes; the second is
        simply the cheaper fill. Phase 4's combo optimiser must treat these as one
        leg — see design principle 4 on stating independence assumptions.)
        """
        edges = [
            o.net_edge_after_spread
            for o in self.outcomes
            if o.net_edge_after_spread is not None
        ]
        return max(edges) if edges else None

    @property
    def best_trade(self) -> OutcomeDivergence | None:
        """The single leg to take — ranked by expected DOLLARS, not by rate.

        Rate and value disagree, and the difference is not academic. Live
        Packers/Vikings offered +1.9% against 170 contracts on one leg and +0.9%
        against 1,434 on the other: the lower percentage is worth about four
        times more money. Ranking by percentage would name the smaller trade the
        winner, and then ``best_expected_value`` would not be the best expected
        value available — which is exactly the sort of blended-number confusion
        the two-axis design exists to prevent.

        Falls back to rate only when no leg reports depth, since with size
        unknown the per-contract edge is the only thing left to compare.
        """
        candidates = [o for o in self.outcomes if o.tradeable]
        if not candidates:
            return None
        with_value = [o for o in candidates if o.expected_value_at_depth is not None]
        if with_value:
            return max(with_value, key=lambda o: o.expected_value_at_depth or 0.0)
        return max(candidates, key=lambda o: o.net_edge_after_spread or 0.0)

    @property
    def tradeable(self) -> bool:
        return any(o.tradeable for o in self.outcomes)

    @property
    def is_arbitrage(self) -> bool:
        return self.arbitrage is not None

    @property
    def best_expected_value(self) -> float | None:
        """Expected dollars at the best fill — edge scaled by resting size."""
        trade = self.best_trade
        return trade.expected_value_at_depth if trade else None


@dataclass(frozen=True)
class KalshiRecommendation:
    """A single-platform, single-action directional view — the Kalshi user's trade.

    Categorically NOT arbitrage, and the two must never share vocabulary:

    * This is **outcome risk**. You buy one contract on one platform. It returns
      $1 if you are right and $0 if you are not, and it is only +EV *if the
      sportsbook consensus is the better probability estimate than Kalshi's
      price*. It can lose the entire stake. Nothing here is guaranteed.
    * Arbitrage is **execution risk**: every outcome covered, so the payout does
      not depend on who wins.

    Both Kalshi actions are BUYS — buy Yes, or buy No — so a directional view is
    always expressible as a purchase, never as a "sell". Buying No is priced at
    ``1 - yes_bid``, which is exact rather than an approximation: Kalshi quotes
    ``no_ask == 1 - yes_bid`` by construction (verified on 40/40 live markets).
    Without the No side, two of ten live edges would have had no expressible
    recommendation at all.
    """

    team: str
    side: str  # 'yes' | 'no' — both are buys
    price: float  # what one contract costs, 0..1
    fair_value: float  # consensus probability of THIS side winning
    edge: float  # fair_value - price, per contract
    max_contracts: float | None  # size resting at that price; None if unknown

    @property
    def wins_if(self) -> str:
        """Plain-English condition under which this contract pays $1."""
        return f"{self.team} wins" if self.side == "yes" else f"{self.team} loses"

    @property
    def max_stake(self) -> float | None:
        """Largest stake fillable at this price, in dollars."""
        return None if self.max_contracts is None else self.max_contracts * self.price


def kalshi_recommendation(
    kalshi_quotes: list[OutcomeQuote], consensus_quotes: list[OutcomeQuote]
) -> KalshiRecommendation | None:
    """Best Kalshi-native buy, or None when no side is mispriced.

    Considers buying Yes and buying No on every outcome, and returns the single
    largest positive edge. Returns None rather than manufacturing a pick when
    nothing clears — a dead-even market is a real answer, and forcing a
    recommendation onto one would be the worst kind of false confidence.
    """
    consensus = {q.join_key: q for q in consensus_quotes}
    best: KalshiRecommendation | None = None

    for k in kalshi_quotes:
        c = consensus.get(k.join_key)
        if c is None or k.team is None:
            continue
        candidates = []
        if k.ask is not None:
            # Buy Yes: costs the ask, pays $1 if this team wins.
            candidates.append(("yes", k.ask, c.implied_probability, k.ask_size))
        if k.bid is not None:
            # Buy No: costs 1 - yes_bid (exact), pays $1 if this team loses.
            candidates.append(
                ("no", 1.0 - k.bid, 1.0 - c.implied_probability, k.bid_size)
            )
        for side, price, fair, size in candidates:
            edge = fair - price
            if edge > 0 and (best is None or edge > best.edge):
                best = KalshiRecommendation(
                    team=k.team, side=side, price=price,
                    fair_value=fair, edge=edge, max_contracts=size,
                )
    return best


@dataclass(frozen=True)
class ArbitrageLeg:
    """One outcome of an arbitrage, and where to buy it cheapest."""

    join_key: str
    team: str | None
    venue: str  # 'kalshi' or a bookmaker key
    implied_price: float  # raw, vig included — what you actually pay


@dataclass(frozen=True)
class Arbitrage:
    """A position covering every outcome for less than the $1 it pays back.

    ``gross_profit`` is named gross for a reason: it models NO trading fees and
    NO execution risk. Kalshi charges a per-trade fee and sportsbooks impose
    stake limits and can move or void a line before both legs are filled, so a
    small gross number is very likely negative once real costs land. Observed
    live: a 0.02% gross arbitrage, which no fee schedule survives.

    A fee model is deliberately NOT invented here — it would need real per-venue
    fee data to be anything better than a guess, and a wrong fee model is worse
    than an honest gross figure next to a stated caveat. Callers must read
    ``gross_profit`` as an upper bound, never as realised profit.
    """

    total_cost: float  # sum of the cheapest price per outcome
    gross_profit: float  # 1 - total_cost, BEFORE fees and execution risk
    legs: list[ArbitrageLeg]
    limiting_depth: float | None  # Kalshi resting size on any Kalshi leg


def detect_arbitrage(
    kalshi_quotes: list[OutcomeQuote], consensus_quotes: list[OutcomeQuote]
) -> Arbitrage | None:
    """Find a risk-free cross-venue position, if one exists.

    Categorically different from a divergence or a net edge, and kept on its own
    axis for that reason. A net edge is DIRECTIONAL — it pays only if the
    sportsbook consensus is a better probability estimate than Kalshi, so it
    depends on trusting the consensus. Arbitrage requires no belief at all: if
    every outcome can be bought for less than $1 in total, the position returns
    $1 whatever happens. Blending the two would let a confident guess masquerade
    as a certainty.

    Two consequences of that independence, both deliberate:

    * **Raw prices only.** ``implied_probability`` is vig-stripped and
      renormalised to sum to exactly 1, so arbitrage computed from it is
      impossible BY CONSTRUCTION. This prices off Kalshi's raw ask and each
      book's raw American odds (vig included) from ``order_book_depth``.
    * **No consensus-quality gate.** ``min_consensus_books`` exists to decide
      whether a median is a trustworthy probability ESTIMATE. Arbitrage needs no
      estimate, so a single-book event can carry a perfectly real arbitrage and
      is checked like any other.

    Per outcome we take the cheapest route across all venues — the best
    individual book, not the median, since you place the bet wherever the price
    is best. Returns None unless every outcome is priced (an uncovered outcome
    means the position is not risk-free).
    """
    by_key: dict[str, list[tuple[str, float]]] = {}

    for q in kalshi_quotes:
        if q.ask is not None:
            by_key.setdefault(q.join_key, []).append(("kalshi", q.ask))

    for q in consensus_quotes:
        for book, american in (q.book_prices or {}).items():
            try:
                by_key.setdefault(q.join_key, []).append(
                    (book, american_to_probability(american))
                )
            except ValueError:
                continue  # unusable quote from one book; others may still price it

    outcomes = {q.join_key for q in kalshi_quotes} | {q.join_key for q in consensus_quotes}
    if not outcomes or not outcomes <= set(by_key):
        return None  # an outcome we cannot cover; the position would carry risk

    teams = {q.join_key: q.team for q in (*consensus_quotes, *kalshi_quotes)}
    legs: list[ArbitrageLeg] = []
    for key in sorted(outcomes):
        venue, price = min(by_key[key], key=lambda vp: vp[1])
        legs.append(ArbitrageLeg(key, teams.get(key), venue, price))

    total = sum(leg.implied_price for leg in legs)
    if total >= 1.0:
        return None

    kalshi_depth = [
        q.ask_size
        for q in kalshi_quotes
        if q.ask_size is not None
        and any(leg.venue == "kalshi" and leg.join_key == q.join_key for leg in legs)
    ]
    return Arbitrage(
        total_cost=total,
        gross_profit=1.0 - total,
        legs=legs,
        limiting_depth=min(kalshi_depth) if kalshi_depth else None,
    )


def net_edge(kalshi: OutcomeQuote, consensus_probability: float) -> tuple[float | None, str | None]:
    """Best capturable edge on one outcome, and which side to take it.

    A Kalshi contract settles at $1, so its raw dollar price IS the executable
    probability — no vig-stripping belongs here. Vig-stripping normalises across
    an event's markets to answer "what does Kalshi BELIEVE"; this function asks
    "what can I actually transact at", and the answer is the raw touch:

      * buy Yes at the ask  -> EV = p_consensus - ask
      * sell Yes at the bid -> EV = bid - p_consensus

    Since bid <= ask at most one is positive, so the max is the only candidate.
    A non-positive result means the disagreement is real but smaller than the
    cost of crossing — the common case, and the reason this axis exists.

    Returns (None, None) when the book is unknown; a quote without bid/ask cannot
    be assessed for tradeability and must not be assumed tradeable.
    """
    if kalshi.bid is None or kalshi.ask is None:
        return None, None
    buy = consensus_probability - kalshi.ask
    sell = kalshi.bid - consensus_probability
    return (buy, "buy_kalshi") if buy >= sell else (sell, "sell_kalshi")


def _consensus_book_count(quotes: list[OutcomeQuote]) -> int | None:
    """Bookmakers behind a consensus, taken as the MINIMUM across its outcomes.

    Both outcomes normally come from the same set of books, but if they ever
    differ the weaker side is what limits how much the comparison can be trusted.
    """
    counts = [q.n_books for q in quotes if q.n_books is not None]
    return min(counts) if counts else None


def score_event(
    *,
    kalshi_quotes: list[OutcomeQuote],
    consensus_quotes: list[OutcomeQuote],
    min_books: int | None = None,
) -> tuple[DivergenceStatus, str, int | None, list[OutcomeDivergence], float | None]:
    """Pure scoring for one event. DB-free so every branch is unit-testable.

    Returns (status, reason, n_books, per-outcome rows, max |divergence|).
    """
    floor = settings.min_consensus_books if min_books is None else min_books
    kalshi = {q.join_key: q for q in kalshi_quotes}
    consensus = {q.join_key: q for q in consensus_quotes}
    n_books = _consensus_book_count(consensus_quotes)

    def rows(scored: bool) -> list[OutcomeDivergence]:
        out = []
        for key in sorted(set(kalshi) | set(consensus)):
            k, c = kalshi.get(key), consensus.get(key)
            comparable = scored and k is not None and c is not None
            div = k.implied_probability - c.implied_probability if comparable else None
            edge, side = (
                net_edge(k, c.implied_probability) if comparable else (None, None)
            )
            out.append(
                OutcomeDivergence(
                    join_key=key,
                    team=(k or c).team,  # type: ignore[union-attr]
                    kalshi_probability=k.implied_probability if k else None,
                    consensus_probability=c.implied_probability if c else None,
                    divergence=div,
                    net_edge_after_spread=edge,
                    trade_side=side if edge is not None and edge > 0 else None,
                    spread=k.spread if k else None,
                    resting_depth=k.resting_depth if k else None,
                    # Present even when the event is unscored: the observed book
                    # prices are real observations, and showing them is how a
                    # reader sees WHY a thin consensus was not trusted.
                    book_prices=c.book_prices if c else None,
                    kalshi_bid=k.bid if k else None,
                    kalshi_ask=k.ask if k else None,
                    kalshi_bid_size=k.bid_size if k else None,
                    kalshi_ask_size=k.ask_size if k else None,
                )
            )
        return out

    if not kalshi or not consensus:
        present = [
            name
            for name, qs in ((KALSHI_SOURCE, kalshi), (CONSENSUS_SOURCE, consensus))
            if qs
        ]
        return (
            DivergenceStatus.SINGLE_SOURCE,
            f"only {present[0] if present else 'no'} priced this event; "
            "nothing to compare against",
            n_books,
            rows(scored=False),
            None,
        )

    if set(kalshi) != set(consensus):
        return (
            DivergenceStatus.INCOMPARABLE,
            f"outcome keys differ between sources: kalshi={sorted(kalshi)} "
            f"consensus={sorted(consensus)}",
            n_books,
            rows(scored=False),
            None,
        )

    if n_books is None or n_books < floor:
        return (
            DivergenceStatus.INSUFFICIENT_CONSENSUS,
            f"consensus is a median over {n_books if n_books is not None else 0} "
            f"bookmaker(s), below the floor of {floor}; observed prices shown, "
            "divergence deliberately not scored",
            n_books,
            rows(scored=False),
            None,
        )

    scored_rows = rows(scored=True)
    max_abs = max(
        (r.abs_divergence for r in scored_rows if r.abs_divergence is not None),
        default=None,
    )
    tradeable = [r for r in scored_rows if r.tradeable]
    reason = f"both sources present; consensus over {n_books} bookmakers"
    if not tradeable:
        # Scored and real, just not capturable. Said explicitly so nobody reads
        # a divergence number as an opportunity.
        reason += "; no edge survives the Kalshi spread"
    return (
        DivergenceStatus.SCORED,
        reason,
        n_books,
        scored_rows,
        max_abs,
    )


def _latest_quotes(session: Session, event_ids: list[uuid_mod.UUID]) -> dict[
    tuple[uuid_mod.UUID, str], list[OutcomeQuote]
]:
    """Latest snapshot per (event, source, outcome/team), as {(event_id, source): quotes}.

    ``odds_snapshots`` is append-only, so "current price" is always the newest row
    rather than a mutated one. DISTINCT ON does that in one pass; the id tiebreak
    keeps it deterministic when two rows share a snapshot_time.
    """
    if not event_ids:
        return {}
    stmt = (
        select(
            OddsSnapshot.event_id,
            OddsSnapshot.source,
            OddsSnapshot.outcome,
            OddsSnapshot.team,
            OddsSnapshot.implied_probability,
            OddsSnapshot.snapshot_time,
            OddsSnapshot.order_book_depth,
        )
        .where(OddsSnapshot.event_id.in_(event_ids))
        .distinct(
            OddsSnapshot.event_id,
            OddsSnapshot.source,
            OddsSnapshot.outcome,
            OddsSnapshot.team,
        )
        .order_by(
            OddsSnapshot.event_id,
            OddsSnapshot.source,
            OddsSnapshot.outcome,
            OddsSnapshot.team,
            OddsSnapshot.snapshot_time.desc(),
            OddsSnapshot.id.desc(),
        )
    )
    out: dict[tuple[uuid_mod.UUID, str], list[OutcomeQuote]] = {}
    for r in session.execute(stmt).all():
        depth = r.order_book_depth if isinstance(r.order_book_depth, dict) else {}
        out.setdefault((r.event_id, r.source), []).append(
            OutcomeQuote(
                outcome=r.outcome,
                team=r.team,
                implied_probability=float(r.implied_probability),
                snapshot_time=r.snapshot_time,
                n_books=depth.get("n_books"),
                # Kalshi's executable book. Absent for consensus rows, which have
                # no single book to cross.
                bid=_as_float(depth.get("yes_bid")),
                ask=_as_float(depth.get("yes_ask")),
                bid_size=_as_float(depth.get("yes_bid_size")),
                ask_size=_as_float(depth.get("yes_ask_size")),
                # Consensus only: raw per-book American odds, for arbitrage.
                book_prices=depth.get("books_american"),
            )
        )
    return out


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def compute_divergences(
    session: Session,
    *,
    sport: str | None = None,
    event_id: uuid_mod.UUID | None = None,
    status: DivergenceStatus | None = None,
    min_divergence: float | None = None,
    tradeable_only: bool = False,
    limit: int = 200,
) -> list[EventDivergence]:
    """Score every scheduled event, biggest capturable edge first.

    ``event_id`` narrows to a single event WITHOUT relaxing the scheduled-only
    rule. A finished game still has last-known quotes, and scoring them would
    emit a divergence and a recommendation for a bet nobody can place — so a
    past event returns an empty list here, and the caller reports what actually
    happened instead of a stale-looking edge.

    Filters are applied AFTER scoring so that a filter can never turn "we don't
    trust this" into "this doesn't exist" — an event excluded by ``status`` was
    still evaluated and still says why.

    Ordering leads on net edge rather than raw divergence: the largest
    disagreement is usually not the most actionable one, and sorting by
    divergence alone would put uncapturable gaps at the top of the list.
    """
    ev_stmt = select(
        Event.id,
        Event.sport,
        Event.league,
        Event.home_team,
        Event.away_team,
        Event.scheduled_start,
        Event.home_away_source,
        Event.kalshi_event_ticker,
        Event.odds_api_event_id,
    ).where(Event.status == "scheduled")
    if sport:
        ev_stmt = ev_stmt.where(Event.sport == sport)
    if event_id is not None:
        ev_stmt = ev_stmt.where(Event.id == event_id)
    events = session.execute(ev_stmt.order_by(Event.scheduled_start)).all()

    quotes = _latest_quotes(session, [e.id for e in events])

    results: list[EventDivergence] = []
    for e in events:
        st, reason, n_books, rows, max_abs = score_event(
            kalshi_quotes=quotes.get((e.id, KALSHI_SOURCE), []),
            consensus_quotes=quotes.get((e.id, CONSENSUS_SOURCE), []),
        )
        results.append(
            EventDivergence(
                event_id=e.id,
                sport=e.sport,
                league=e.league,
                home_team=e.home_team,
                away_team=e.away_team,
                scheduled_start=e.scheduled_start,
                status=st,
                reason=reason,
                sources=sorted(
                    s for s in (KALSHI_SOURCE, CONSENSUS_SOURCE) if quotes.get((e.id, s))
                ),
                n_books=n_books,
                max_abs_divergence=max_abs,
                outcomes=rows,
                arbitrage=detect_arbitrage(
                    quotes.get((e.id, KALSHI_SOURCE), []),
                    quotes.get((e.id, CONSENSUS_SOURCE), []),
                ),
                home_away_source=e.home_away_source,
                kalshi_event_ticker=e.kalshi_event_ticker,
                odds_api_event_id=e.odds_api_event_id,
                # Gated on SCORED: recommending a side off a one-book "consensus"
                # would be exactly the false precision min_consensus_books exists
                # to prevent.
                recommendation=(
                    kalshi_recommendation(
                        quotes.get((e.id, KALSHI_SOURCE), []),
                        quotes.get((e.id, CONSENSUS_SOURCE), []),
                    )
                    if st is DivergenceStatus.SCORED
                    else None
                ),
            )
        )

    if status is not None:
        results = [r for r in results if r.status is status]
    if min_divergence is not None:
        # Only scored events carry a number, so this implicitly selects them —
        # by design: you cannot filter by a magnitude we refused to compute.
        results = [
            r for r in results
            if r.max_abs_divergence is not None and r.max_abs_divergence >= min_divergence
        ]
    if tradeable_only:
        results = [r for r in results if r.tradeable]

    # Tradeable events first (ranked by capturable edge), then the rest ranked by
    # raw divergence. Keeping the unscored tail visible rather than truncating it
    # is the same rule as everywhere else here: excluded is not the same as absent.
    results.sort(
        key=lambda r: (
            r.tradeable,
            r.best_net_edge if r.tradeable else 0.0,
            r.max_abs_divergence or 0.0,
        ),
        reverse=True,
    )
    return results[:limit]
