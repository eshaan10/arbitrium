"""Kalshi public-market ingestion.

Fetches sports games from Kalshi's public read API (no auth), one *event* at a
time with its nested per-outcome markets, derives event metadata, upserts the
``events`` row, then normalizes the event's markets and appends snapshots to
``odds_snapshots``. The DB-side BEFORE INSERT trigger handles dedup, so we simply
insert every observation and let unchanged prices be suppressed.

Structure (confirmed against the live API): every game is an event containing one
independent binary market per outcome — 2 for NFL/NBA (home/away), 3 for soccer
(home/away/draw). We request only the configured series (``SERIES_CONFIG``), and
``with_nested_markets`` groups each event's markets for us.

Home vs away is NOT labelled by Kalshi. Events are created with a PROVISIONAL
home/away (from ticker ordering, ``home_away_source='kalshi_provisional'``); Phase
2 confirms the authoritative assignment by matching to The Odds API.

``upsert_event`` runs the shared matcher before inserting, so a game The Odds API
already created is merged into (dual-keyed) rather than duplicated. Together with
the Odds-API-side merge this makes poll ORDER irrelevant — neither source has to
run first for the data to land on one event row.

Anything that fails to parse (unknown team, missing price, malformed ticker) is
logged and skipped — never raised — so one bad event can't abort the run.
"""

from __future__ import annotations

import logging
import re
import uuid as uuid_mod
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from marketedge.config import settings
from marketedge.db.engine import get_session
from marketedge.db.models import Event, OddsSnapshot
from marketedge.ingestion.events import find_event_by_match
from marketedge.ingestion.normalize import normalize_kalshi_event
from marketedge.ingestion.snapshots import insert_snapshots
from marketedge.matching import EventKey, MatchStatus
from marketedge.reference.teams import resolve_team

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SeriesConfig:
    """Per-series metadata. Declares the sport/league and the market shape as an
    outcome count (2 = home/away, 3 = home/away/draw) — not a separate math path,
    since ``normalize_kalshi_event`` handles any N uniformly.
    """

    sport: str
    league: str
    outcome_count: int
    has_draw: bool


# Every series in KALSHI_SERIES_TICKERS MUST appear here; run_ingest fails loud on
# an undeclared series so we never ingest a game whose shape/teams we can't map.
SERIES_CONFIG: dict[str, SeriesConfig] = {
    "KXNFLGAME": SeriesConfig("nfl", "NFL", 2, False),
    "KXNBAGAME": SeriesConfig("nba", "NBA", 2, False),
    # Soccer is three-way. Code-ready via the unified normalizer, but kept out of
    # active KALSHI_SERIES_TICKERS until a soccer team registry + a live payload
    # verification pass land (its draw-market detection is unverified).
    "KXMLSGAME": SeriesConfig("soccer", "MLS", 3, True),
    "KXLALIGAGAME": SeriesConfig("soccer", "La Liga", 3, True),
}

_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}
_DRAW_SUFFIXES = {"TIE", "DRAW"}
# KXNFLGAME-26SEP14DENKC -> series prefix, then <YY><MON><DD><matchup>.
_EVENT_TICKER_RE = re.compile(r"^(\d{2})([A-Z]{3})(\d{2})(.+)$")


class KalshiClient:
    """Thin httpx wrapper over Kalshi's public read endpoints."""

    def __init__(self, base_url: str | None = None, timeout: float = 15.0) -> None:
        self.base_url = (base_url or settings.kalshi_api_base).rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "KalshiClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def get_events(
        self,
        *,
        series_ticker: str,
        status: str = "open",
        limit: int = 200,
        max_pages: int = 20,
    ) -> list[dict]:
        """Return events (with nested markets) for a series, following pagination.

        Public endpoint — no auth. ``with_nested_markets`` returns each event's
        per-outcome markets inline, giving us the grouping for free.
        """
        events: list[dict] = []
        cursor: str | None = None
        for _ in range(max_pages):
            params: dict[str, str | int] = {
                "series_ticker": series_ticker,
                "status": status,
                "limit": limit,
                "with_nested_markets": "true",
            }
            if cursor:
                params["cursor"] = cursor
            resp = self._client.get("/events", params=params)
            resp.raise_for_status()
            data = resp.json()
            events.extend(data.get("events", []))
            cursor = data.get("cursor") or None
            if not cursor:
                break
        return events

    def get_orderbook(self, ticker: str, *, depth: int = 10) -> dict:
        """Return the order book for a market (bids/asks per side)."""
        resp = self._client.get(f"/markets/{ticker}/orderbook", params={"depth": depth})
        resp.raise_for_status()
        return resp.json().get("orderbook", {})


@dataclass(frozen=True)
class KalshiEventMetadata:
    """Everything needed to upsert an ``events`` row and normalize its markets."""

    kalshi_event_ticker: str
    sport: str
    league: str
    home_team: str  # canonical name (PROVISIONAL home/away — see home_away_source)
    away_team: str
    scheduled_start: datetime  # date-only for now (midnight UTC); time refined in Phase 2
    outcome_markets: dict[str, dict] = field(default_factory=dict)  # 'home'|'away'|'draw' -> market
    home_away_source: str = "kalshi_provisional"


def _parse_event_ticker(event_ticker: str) -> tuple[datetime, str] | None:
    """Parse (scheduled_start date, matchup segment) from an event ticker.

    ``KXNFLGAME-26SEP14DENKC`` -> (2026-09-14 UTC midnight, "DENKC"). Returns None
    if the ticker doesn't match the expected shape.
    """
    if not event_ticker or "-" not in event_ticker:
        return None
    rest = event_ticker.split("-", 1)[1]
    m = _EVENT_TICKER_RE.match(rest)
    if not m:
        return None
    yy, mon, dd, matchup = m.groups()
    month = _MONTHS.get(mon)
    if month is None:
        return None
    try:
        game_date = datetime(2000 + int(yy), month, int(dd), tzinfo=timezone.utc)
    except ValueError:
        return None
    return game_date, matchup


def _market_suffix(market: dict) -> str:
    return (market.get("ticker") or "").rsplit("-", 1)[-1]


def extract_event_metadata(event: dict, cfg: SeriesConfig) -> KalshiEventMetadata | None:
    """Derive event metadata from a Kalshi event payload. None => skip this event.

    Teams are resolved from each market's suffix code + custom_strike UUID via the
    canonical registry. Home/away is PROVISIONAL, taken from ticker ordering
    (first team = away, second = home) — a placeholder until Phase 2 confirms it
    against The Odds API. Draw is unambiguous (its market carries no team).
    """
    event_ticker = event.get("event_ticker")
    parsed = _parse_event_ticker(event_ticker)
    if parsed is None:
        logger.warning("Could not parse event ticker %r; skipping event", event_ticker)
        return None
    game_date, matchup = parsed

    team_markets: dict[str, dict] = {}  # team code -> market
    draw_market: dict | None = None
    for market in event.get("markets") or []:
        suffix = _market_suffix(market)
        team_uuid = (market.get("custom_strike") or {}).get("football_team")
        team = resolve_team(cfg.league, suffix, team_uuid)
        if team is not None:
            team_markets[team.code] = market
        elif cfg.has_draw and suffix in _DRAW_SUFFIXES:
            draw_market = market
        else:
            logger.warning(
                "Event %s: market suffix %r did not resolve to a %s team; skipping event",
                event_ticker, suffix, cfg.league,
            )
            return None

    if len(team_markets) != 2:
        logger.warning(
            "Event %s: expected 2 team markets, found %d; skipping event",
            event_ticker, len(team_markets),
        )
        return None
    if cfg.has_draw and draw_market is None:
        logger.warning("Event %s: expected a draw market, found none; skipping event", event_ticker)
        return None

    # Provisional home/away: the team whose code the matchup starts with is away.
    codes = list(team_markets)
    away_code = next((c for c in codes if matchup.startswith(c)), codes[0])
    home_code = codes[1] if codes[0] == away_code else codes[0]

    away_team = resolve_team(cfg.league, away_code)
    home_team = resolve_team(cfg.league, home_code)
    assert away_team and home_team  # both resolved above

    outcome_markets = {"home": team_markets[home_code], "away": team_markets[away_code]}
    if draw_market is not None:
        outcome_markets["draw"] = draw_market

    return KalshiEventMetadata(
        kalshi_event_ticker=event_ticker,
        sport=cfg.sport,
        league=cfg.league,
        home_team=home_team.name,
        away_team=away_team.name,
        scheduled_start=game_date,
        outcome_markets=outcome_markets,
    )


def _claim_existing_event(session, event_id: uuid_mod.UUID, meta: KalshiEventMetadata) -> None:
    """Attach this Kalshi ticker to an event another source already created.

    Only the Kalshi-side key is written. home/away, home_away_source and
    scheduled_start are LEFT ALONE: the existing row's values came from The Odds
    API and are authoritative, while Kalshi's are provisional ticker ordering and
    a date-only kickoff. Downgrading them here would undo the Phase-2 enrichment.
    """
    session.execute(
        update(Event)
        .where(Event.id == event_id)
        .values(kalshi_event_ticker=meta.kalshi_event_ticker, updated_at=func.now())
    )


def _insert_kalshi_event(session, meta: KalshiEventMetadata) -> uuid_mod.UUID:
    """Insert a Kalshi-sourced event, refreshing it if the ticker already exists.

    On conflict we refresh ``scheduled_start``/``updated_at`` only — we do NOT
    overwrite home/away or home_away_source, so a Phase-2 authoritative
    assignment is never clobbered by a later provisional pass.
    """
    stmt = (
        pg_insert(Event)
        .values(
            sport=meta.sport,
            league=meta.league,
            home_team=meta.home_team,
            away_team=meta.away_team,
            scheduled_start=meta.scheduled_start,
            status="scheduled",
            kalshi_event_ticker=meta.kalshi_event_ticker,
            home_away_source=meta.home_away_source,
        )
        .on_conflict_do_update(
            index_elements=["kalshi_event_ticker"],
            set_={"scheduled_start": meta.scheduled_start, "updated_at": func.now()},
        )
        .returning(Event.id)
    )
    return session.execute(stmt).scalar_one()


def upsert_event(session, meta: KalshiEventMetadata) -> uuid_mod.UUID:
    """Resolve this Kalshi event to an ``events`` row id, merging if one exists.

    This is the reciprocal of the Odds-API-side merge, and it is what makes poll
    ORDER irrelevant. Previously Kalshi inserted blind on its own ticker, so a
    game the Odds API had already created would be split into two rows the moment
    Odds API polled first. The three cases:

      * ticker already known -> fast path, refresh it (the steady state);
      * matches an existing (odds-only) event -> claim it, one row, dual-keyed;
      * no match -> insert a new Kalshi-only event.

    AMBIGUOUS (a doubleheader, where merging into either candidate would be a
    guess) creates a Kalshi-only event rather than skipping. Kalshi is the primary
    source, so dropping its prices to avoid a duplicate would trade a recoverable
    problem (an extra row, mergeable later) for an unrecoverable one (a gap in
    append-only price history).
    """
    existing = session.execute(
        select(Event.id).where(Event.kalshi_event_ticker == meta.kalshi_event_ticker)
    ).scalar_one_or_none()
    if existing is not None:
        return _insert_kalshi_event(session, meta)  # known ticker: refresh via upsert

    key = EventKey(meta.sport, meta.home_team, meta.away_team, meta.scheduled_start)
    event_id, status = find_event_by_match(session, key)
    if event_id is not None:
        logger.info(
            "Kalshi event %s merged into existing event %s (created by another source)",
            meta.kalshi_event_ticker, event_id,
        )
        _claim_existing_event(session, event_id, meta)
        return event_id

    if status is MatchStatus.AMBIGUOUS:
        logger.warning(
            "Kalshi event %s: ambiguous match (possible doubleheader); creating a "
            "Kalshi-only event rather than guessing which existing row to merge into",
            meta.kalshi_event_ticker,
        )

    return _insert_kalshi_event(session, meta)


def ingest_event(session, event: dict, cfg: SeriesConfig) -> int:
    """Upsert one event and queue its snapshots. Returns snapshot rows attempted.

    Returns 0 when the event is skipped (metadata could not be derived). Rows
    actually persisted may be fewer than returned, since the dedup trigger drops
    unchanged prices.
    """
    meta = extract_event_metadata(event, cfg)
    if meta is None:
        return 0

    event_id = upsert_event(session, meta)
    snaps = normalize_kalshi_event(
        meta.outcome_markets, kalshi_event_ticker=meta.kalshi_event_ticker
    )
    now = datetime.now(timezone.utc)
    # Anchor each row to its team at write time. home/away here is provisional and
    # may be flipped later by The Odds API; team never changes, which is the whole
    # point of the column (see migration 0005). 'draw' carries no team.
    team_for = {"home": meta.home_team, "away": meta.away_team, "draw": None}
    return insert_snapshots(
        session,
        [
            {
                "event_id": event_id,
                "source": snap.source,
                "outcome": snap.outcome,
                "team": team_for.get(snap.outcome),
                "implied_probability": snap.implied_probability,
                "raw_price": snap.raw_price,
                "price_format": snap.price_format,
                "liquidity_score": snap.liquidity_score,
                "order_book_depth": snap.order_book_depth,
                "ingested_at": now,
                "snapshot_time": now,
            }
            for snap in snaps
        ],
    )


def run_ingest(series_tickers: list[str] | None = None) -> int:
    """Fetch configured Kalshi series as events, upsert each, and append snapshots.

    Returns snapshot rows attempted. Events that can't be parsed are skipped and
    logged; only transient network/API errors propagate (so Prefect retries them).
    """
    series = series_tickers if series_tickers is not None else settings.kalshi_series_tickers
    if not series:
        logger.warning(
            "No Kalshi series configured (KALSHI_SERIES_TICKERS is empty); skipping "
            "ingest. Set the target series to enable ingestion."
        )
        return 0

    undeclared = [s for s in series if s not in SERIES_CONFIG]
    if undeclared:
        raise ValueError(
            f"Undeclared Kalshi series: {undeclared}. Add each to SERIES_CONFIG "
            "(sport, league, outcome count, draw?) before ingesting."
        )

    total = 0
    skipped = 0
    with KalshiClient() as client:
        session = get_session()
        try:
            for series_ticker in series:
                cfg = SERIES_CONFIG[series_ticker]
                events = client.get_events(series_ticker=series_ticker)
                if not events:
                    logger.info(
                        "Series %s returned 0 open events (dormant/off-season); nothing to ingest.",
                        series_ticker,
                    )
                    continue
                for event in events:
                    event_ticker = event.get("event_ticker", "<unknown>")
                    try:
                        rows = ingest_event(session, event, cfg)
                    except ValueError as exc:
                        # Non-transient (e.g. a market with no usable price). Skip
                        # and log — do NOT raise (would burn retries).
                        skipped += 1
                        logger.warning("Skipping event %s: %s", event_ticker, exc)
                        continue
                    if rows == 0:
                        skipped += 1
                    total += rows
            # Only touch the DB if something was queued (keeps all-skipped runs
            # free of an empty commit).
            if total:
                session.commit()
        finally:
            session.close()
    logger.info(
        "Kalshi ingest complete: %d snapshot rows attempted, %d events skipped",
        total,
        skipped,
    )
    return total
