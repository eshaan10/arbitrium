"""The Odds API ingestion (Phase 2): sportsbook consensus odds.

Fetches h2h (moneyline) odds, aggregates bookmakers into a median consensus
(:func:`arbitrium.ingestion.normalize.normalize_odds_api_consensus`), matches
each game to an existing Kalshi ``events`` row via the shared matcher, and:
  * MATCHED  -> enriches that row: authoritative home/away, odds_api_event_id,
    exact ``commence_time`` as scheduled_start, home_away_source='odds_api'.
  * UNMATCHED -> creates a single-source (odds-only) event (never dropped).
  * AMBIGUOUS -> skips and logs (never guesses — see matching edge cases).

Snapshots are anchored to ``team`` (authoritative here), so a later home/away
correction never touches append-only rows.

Live fetch is wired but intentionally exercised only after fixture tests pass and
a real ODDS_API_KEY is present (same discipline as the Kalshi price-field bug).
"""

from __future__ import annotations

import logging
import uuid as uuid_mod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from arbitrium.config import settings
from arbitrium.db.engine import get_session
from arbitrium.db.models import Event, OddsSnapshot
from arbitrium.ingestion.events import find_event_by_match
from arbitrium.ingestion.governor import CallRecord, record_call, reserve_credits
from arbitrium.ingestion.normalize import NormalizedSnapshot, normalize_odds_api_consensus
from arbitrium.ingestion.polling import active_sports
from arbitrium.ingestion.result import IngestResult
from arbitrium.ingestion.snapshots import insert_snapshots, snapshot_count
from arbitrium.logging_config import UNHEALTHY_MARKER, redact
from arbitrium.matching import EventKey, MatchStatus
from arbitrium.reference.teams import resolve_by_name

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OddsSport:
    """Maps an Odds API sport_key to our canonical sport/league."""

    sport: str
    league: str


# Odds API sport_key -> our sport/league. Every key must also appear in
# polling.SPORT_SEASONS, which decides whether and when it may be called.
ODDS_SPORTS: dict[str, OddsSport] = {
    "americanfootball_nfl": OddsSport("nfl", "NFL"),
    # Preseason is a SEPARATE key: the regular-season key does not cover August
    # games, which is why Kalshi's preseason events sat single-source with no
    # consensus to compare against. Also the earliest source of real completed
    # games for outcome resolution.
    "americanfootball_nfl_preseason": OddsSport("nfl", "NFL"),
    # NBA once billed a credit every pass for events that were all skipped as
    # unresolved. It is safe to list now because a call needs a Kalshi-backed
    # game to be due (and Kalshi only stores games whose teams resolve), and
    # because NBA and NHL stay disabled in ODDS_SPORTS_ENABLED until their team
    # registries land.
    "basketball_nba": OddsSport("nba", "NBA"),
    "basketball_nba_preseason": OddsSport("nba", "NBA"),
    "icehockey_nhl": OddsSport("nhl", "NHL"),
}

# What each endpoint costs with h2h in one region (verified against the v4
# docs: /odds is markets x regions, /scores is 2 with daysFrom, /events and
# /sports are free). Used to check the reserve BEFORE a call; the ledger then
# records what the response says it actually cost.
ODDS_CALL_COST = 1
SCORES_CALL_COST = 2


# The scores endpoint's hard ceiling. daysFrom=4 returns HTTP 422 "Invalid
# daysFrom" — verified live. There is NO deeper history on this endpoint, so an
# outcome not collected inside this window is permanently unavailable from here.
MAX_SCORES_DAYS_FROM = 3


class QuotaExhausted(RuntimeError):
    """Raised instead of spending the last of the monthly API budget."""


class OddsApiClient:
    """Thin httpx wrapper over The Odds API v4 (requires an API key).

    Reads the quota headers from EVERY response, free or paid, and hands each
    call to ``recorder`` (``credit_log`` by default) so the governor paces the
    month from a ledger that survives restarts. Independently of the governor,
    it refuses any call that would dip into the reserve: exhaustion is otherwise
    indistinguishable from a quiet market.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 15.0,
        *,
        recorder: Callable[[CallRecord], None] | None = record_call,
    ) -> None:
        self.api_key = api_key or settings.odds_api_key
        self.base_url = (base_url or settings.odds_api_base).rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)
        self._recorder = recorder
        # Only known after the first response; None means "not yet observed".
        self.quota_remaining: int | None = None
        self.quota_used: int | None = None
        self.quota_last: int | None = None

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "OddsApiClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _record_quota(self, resp: httpx.Response) -> None:
        """Read the quota counters the API returns on every response."""
        self.quota_last = None
        for header, attr in (
            ("x-requests-remaining", "quota_remaining"),
            ("x-requests-used", "quota_used"),
            ("x-requests-last", "quota_last"),
        ):
            raw = resp.headers.get(header)
            if raw is not None:
                try:
                    setattr(self, attr, int(float(raw)))
                except ValueError:
                    pass

    def _check_quota(self, cost: int = ODDS_CALL_COST) -> None:
        """Refuse a call that would leave less than the reserve.

        A last line of defence behind the governor, which normally stops well
        before this: it holds even for a caller that skipped the governor.
        """
        reserve = reserve_credits()
        if cost and self.quota_remaining is not None and self.quota_remaining - cost < reserve:
            raise QuotaExhausted(
                f"{UNHEALTHY_MARKER}: Odds API quota at {self.quota_remaining}; a "
                f"{cost}-credit call would dip into the reserve of {reserve}. "
                "Refusing further paid calls."
            )

    def _get(
        self,
        path: str,
        params: dict,
        *,
        endpoint: str,
        sport_key: str,
        cost: int,
        checkpoint: str | None = None,
    ) -> list[dict]:
        """Issue a checked, quota-tracked, ledger-recorded, redaction-safe GET."""
        if not self.api_key:
            raise ValueError("ODDS_API_KEY is not set")
        self._check_quota(cost)
        resp = self._client.get(path, params={"apiKey": self.api_key, **params})
        self._record_quota(resp)
        body = resp.json() if resp.is_success else None
        self._log_call(resp, body, endpoint=endpoint, sport_key=sport_key, cost=cost,
                       checkpoint=checkpoint)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # The credential can only travel as a query parameter, so any error
            # quoting the URL discloses it. HTTPStatusError embeds the full URL
            # in its message, so it is re-raised redacted.
            raise httpx.HTTPStatusError(
                redact(str(exc)), request=exc.request, response=exc.response
            ) from None
        return body

    def _log_call(
        self, resp: httpx.Response, body: object, *, endpoint: str, sport_key: str,
        cost: int, checkpoint: str | None,
    ) -> None:
        """Hand this response's cost to the recorder.

        ``x-requests-last`` is the truth. If it is missing on a paid call, the
        expected cost is logged instead: over-counting a credit is safe,
        under-counting one is how a month runs out early. An empty /odds list
        is free (verified), so it is never charged an estimate.
        """
        if self._recorder is None:
            return
        returned = len(body) if isinstance(body, list) else None
        used = self.quota_last
        if used is None:
            used = 0 if (returned == 0 or not resp.is_success) else cost
            if used:
                logger.warning(
                    "Odds API %s %s: no x-requests-last header; logging the expected "
                    "%d credit(s)", endpoint, sport_key, used,
                )
        cfg = ODDS_SPORTS.get(sport_key)
        self._recorder(
            CallRecord(
                endpoint=endpoint,
                sport_key=sport_key,
                sport=cfg.sport if cfg else None,
                checkpoint=checkpoint,
                credits_used=used,
                remaining=self.quota_remaining,
                used=self.quota_used,
                events_returned=returned,
            )
        )

    def get_events(self, sport_key: str) -> list[dict]:
        """Upcoming games with exact ``commence_time``. FREE.

        "This endpoint does not count against the usage quota" (v4 docs). Its
        response still carries the quota headers, which is how the governor
        learns the real balance without spending anything.
        """
        return self._get(
            f"/sports/{sport_key}/events", {}, endpoint="events", sport_key=sport_key, cost=0
        )

    def get_odds(
        self,
        sport_key: str,
        *,
        regions: str = "us",
        markets: str = "h2h",
        checkpoint: str | None = None,
    ) -> list[dict]:
        """Return events with bookmaker odds.

        Costs markets x regions credits — 1 for h2h in one region — but ONLY if
        the response contains events; empty responses are free (verified
        against the live counter).
        """
        return self._get(
            f"/sports/{sport_key}/odds",
            {"regions": regions, "markets": markets, "oddsFormat": "american"},
            endpoint="odds", sport_key=sport_key, cost=ODDS_CALL_COST, checkpoint=checkpoint,
        )

    def get_scores(self, sport_key: str, *, days_from: int | None = None) -> list[dict]:
        """Return events with final/live scores. 2 credits with days_from, 1 without.

        ``days_from`` is validated locally rather than letting the API 422: a
        config typo must not cost both a credit and a resolution pass inside a
        window that cannot be revisited.
        """
        days = settings.resolution_days_from if days_from is None else days_from
        if not 1 <= days <= MAX_SCORES_DAYS_FROM:
            raise ValueError(
                f"days_from must be between 1 and {MAX_SCORES_DAYS_FROM} "
                f"(the API's ceiling); got {days}"
            )
        return self._get(
            f"/sports/{sport_key}/scores/", {"daysFrom": days},
            endpoint="scores", sport_key=sport_key, cost=SCORES_CALL_COST,
        )


def _parse_commence_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)  # 3.11+ parses trailing 'Z'
    except ValueError:
        return None


@dataclass(frozen=True)
class OddsEventExtract:
    key: EventKey
    odds_api_event_id: str
    snapshots: list[NormalizedSnapshot]


def extract_odds_event(event: dict, sport_cfg: OddsSport) -> OddsEventExtract | None:
    """Resolve teams + build the consensus snapshots for one Odds API event.

    None => skip (unresolved team name or unusable payload) — logged, never guessed.
    """
    odds_id = event.get("id")
    home_raw = event.get("home_team")
    away_raw = event.get("away_team")
    home = resolve_by_name(sport_cfg.league, home_raw or "")
    away = resolve_by_name(sport_cfg.league, away_raw or "")
    if home is None or away is None:
        logger.warning(
            "Odds event %s: unresolved team(s) home=%r away=%r; skipping",
            odds_id, home_raw, away_raw,
        )
        return None

    commence = _parse_commence_time(event.get("commence_time"))
    if commence is None:
        logger.warning("Odds event %s: unparseable commence_time %r; skipping",
                       odds_id, event.get("commence_time"))
        return None

    try:
        snaps = normalize_odds_api_consensus(
            odds_api_event_id=odds_id,
            home_team=home.name,
            away_team=away.name,
            bookmakers=event.get("bookmakers", []),
        )
    except ValueError as exc:
        logger.warning("Odds event %s: %s; skipping", odds_id, exc)
        return None

    key = EventKey(sport_cfg.sport, home.name, away.name, commence)
    return OddsEventExtract(key=key, odds_api_event_id=odds_id, snapshots=snaps)


def _create_odds_only_event(session: Session, extract: OddsEventExtract) -> uuid_mod.UUID:
    """Create a single-source event from Odds API data (home/away authoritative)."""
    key = extract.key
    stmt = (
        pg_insert(Event)
        .values(
            sport=key.sport,
            league=_league_for_sport(key.sport),
            home_team=key.home_team,
            away_team=key.away_team,
            scheduled_start=key.start,
            status="scheduled",
            odds_api_event_id=extract.odds_api_event_id,
            home_away_source="odds_api",
        )
        .on_conflict_do_update(
            index_elements=["odds_api_event_id"],
            set_={"scheduled_start": key.start, "updated_at": func.now()},
        )
        .returning(Event.id)
    )
    return session.execute(stmt).scalar_one()


def _league_for_sport(sport: str) -> str:
    for cfg in ODDS_SPORTS.values():
        if cfg.sport == sport:
            return cfg.league
    return sport.upper()


def _enrich_matched_event(session: Session, event_id: uuid_mod.UUID, extract: OddsEventExtract) -> None:
    """Set authoritative home/away + odds id + exact kickoff on a matched event."""
    key = extract.key
    session.execute(
        update(Event)
        .where(Event.id == event_id)
        .values(
            home_team=key.home_team,
            away_team=key.away_team,
            scheduled_start=key.start,
            odds_api_event_id=extract.odds_api_event_id,
            home_away_source="odds_api",
            updated_at=func.now(),
        )
    )


BOOK_COUNT_STALE_MARKER = "CONSENSUS_BOOK_COUNT_STALE"


def _warn_if_book_count_would_be_lost(
    session: Session, event_id: uuid_mod.UUID, outcome: str, prob: float, n_books: int | None
) -> None:
    """Detect the one case where the dedup trigger drops information we need.

    The trigger (migration 0002) suppresses a snapshot whose implied_probability
    is unchanged, keyed on PRICE ALONE. If the consensus median holds steady while
    the number of contributing bookmakers changes, the new row is dropped and
    ``n_books`` stays at its old value — which could leave an event stuck below
    ``min_consensus_books`` and silently suppress its recommendation.

    Measured incidence is currently ZERO (stored matched live on 272/272 events),
    because adding or removing a book almost always moves the median. And the
    residual risk sits where it matters least: a median is likeliest to hold when
    many books already agree, which is the regime already above the floor.

    So this instruments rather than fixes. Widening the trigger to remove a
    failure nobody has observed would put a correctness-critical piece of the
    dedup guarantee at risk for no measured benefit. If this marker ever appears,
    the assumption has broken and the structural fix becomes justified.
    """
    if n_books is None:
        return
    stored = session.execute(
        select(OddsSnapshot.implied_probability, OddsSnapshot.order_book_depth)
        .where(
            OddsSnapshot.event_id == event_id,
            OddsSnapshot.source == "consensus",
            OddsSnapshot.outcome == outcome,
        )
        .order_by(OddsSnapshot.snapshot_time.desc(), OddsSnapshot.id.desc())
        .limit(1)
    ).first()
    if stored is None:
        return
    depth = stored.order_book_depth if isinstance(stored.order_book_depth, dict) else {}
    stored_books = depth.get("n_books")
    if stored_books is None or stored_books == n_books:
        return
    if float(stored.implied_probability) != float(prob):
        return  # price moved, so the row lands and the new count is recorded
    logger.warning(
        "%s: event %s outcome %s — median unchanged at %.4f but book count moved "
        "%s -> %s. The dedup trigger will drop this row, leaving n_books stale. "
        "This was measured at zero incidence; its appearance means that no longer holds.",
        BOOK_COUNT_STALE_MARKER, event_id, outcome, float(prob), stored_books, n_books,
    )


def _insert_consensus_snapshots(session: Session, event_id: uuid_mod.UUID, extract: OddsEventExtract) -> int:
    """Insert consensus snapshots, anchoring each to its authoritative team."""
    key = extract.key
    now = datetime.now(tz=key.start.tzinfo) if key.start.tzinfo else datetime.utcnow()
    team_for = {"home": key.home_team, "away": key.away_team, "draw": None}
    for snap in extract.snapshots:
        _warn_if_book_count_would_be_lost(
            session, event_id, snap.outcome, snap.implied_probability,
            (snap.order_book_depth or {}).get("n_books"),
        )
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
                "liquidity_score": snap.liquidity_score,  # None for sportsbooks
                "order_book_depth": snap.order_book_depth,
                "ingested_at": now,
                "snapshot_time": now,
            }
            for snap in extract.snapshots
        ],
    )


def ingest_odds_event(session: Session, event: dict, sport_cfg: OddsSport) -> int:
    """Match/enrich-or-create one Odds API event and queue its consensus snapshots.

    Returns snapshot rows attempted (0 if skipped). Ambiguous matches are skipped
    and logged rather than guessed.
    """
    extract = extract_odds_event(event, sport_cfg)
    if extract is None:
        return 0

    # A row already keyed to a DIFFERENT Odds API id is provably another game —
    # typically the other half of an NBA repeat matchup a day or two away.
    event_id, status = find_event_by_match(
        session, extract.key, claimed=("odds_api", extract.odds_api_event_id)
    )
    if status is MatchStatus.AMBIGUOUS:
        logger.warning(
            "Odds event %s: ambiguous match (possible doubleheader); skipping",
            extract.odds_api_event_id,
        )
        return 0

    if event_id is not None:
        _enrich_matched_event(session, event_id, extract)  # dual-key merge
    else:
        event_id = _create_odds_only_event(session, extract)  # single-source, never dropped

    return _insert_consensus_snapshots(session, event_id, extract)


def in_season_keys(day: datetime | None = None) -> list[str]:
    """Odds API keys of every enabled sport that are in season on ``day``."""
    moment = (day or datetime.now(timezone.utc)).date()
    return sorted(k for p in active_sports(moment) for k in p.keys_in_season(moment))


def run_ingest(
    sport_keys: list[str] | None = None, *, checkpoint: str | None = None
) -> IngestResult:
    """Fetch the given Odds API sport keys and append consensus snapshots.

    Returns an :class:`IngestResult` reporting rows WRITTEN, so the scheduler's
    health tracker can distinguish a quiet market from a broken pass. Per-event
    problems are skipped and logged inside :func:`ingest_odds_event`; only
    transient network/API errors propagate, so the scheduler's with_retries covers them.

    Each key costs one credit. The scheduler never calls this bare: it passes
    exactly the keys a planned, governor-admitted pass needs (see
    ingestion.odds_schedule). Bare, it defaults to the in-season keys of enabled
    sports, never to everything in ODDS_SPORTS.
    """
    keys = sport_keys if sport_keys is not None else in_season_keys()
    undeclared = [k for k in keys if k not in ODDS_SPORTS]
    if undeclared:
        raise ValueError(
            f"Undeclared Odds API sport keys: {undeclared}. Add each to ODDS_SPORTS "
            "(sport, league) before ingesting."
        )
    if not settings.odds_api_key:
        logger.warning("ODDS_API_KEY is not set; skipping Odds API ingest.")
        return IngestResult(source="odds_api")

    seen = skipped = attempted = written = 0
    with OddsApiClient() as client:
        session = get_session()
        try:
            before = snapshot_count(session)
            for sport_key in keys:
                cfg = ODDS_SPORTS[sport_key]
                events = client.get_odds(sport_key, checkpoint=checkpoint)
                if not events:
                    logger.info(
                        "Odds API sport %s returned 0 events (off-season); nothing to ingest.",
                        sport_key,
                    )
                    continue
                seen += len(events)
                for event in events:
                    rows = ingest_odds_event(session, event, cfg)
                    if rows == 0:
                        skipped += 1
                    attempted += rows
            if attempted:
                # Measured before the commit, while the inserts are still visible
                # to this transaction.
                written = snapshot_count(session) - before
                session.commit()
        finally:
            session.close()

    result = IngestResult(
        source="odds_api",
        events_seen=seen,
        events_skipped=skipped,
        rows_attempted=attempted,
        rows_written=written,
    )
    logger.info("Odds API ingest complete: %s", result)
    return result
