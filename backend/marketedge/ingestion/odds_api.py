"""The Odds API ingestion (Phase 2): sportsbook consensus odds.

Fetches h2h (moneyline) odds, aggregates bookmakers into a median consensus
(:func:`marketedge.ingestion.normalize.normalize_odds_api_consensus`), matches
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
from dataclasses import dataclass
from datetime import datetime

import httpx
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from marketedge.config import settings
from marketedge.db.engine import get_session
from marketedge.db.models import Event, OddsSnapshot
from marketedge.ingestion.events import find_event_by_match
from marketedge.ingestion.normalize import NormalizedSnapshot, normalize_odds_api_consensus
from marketedge.ingestion.result import IngestResult
from marketedge.ingestion.snapshots import insert_snapshots, snapshot_count
from marketedge.logging_config import UNHEALTHY_MARKER, redact
from marketedge.matching import EventKey, MatchStatus
from marketedge.reference.teams import resolve_by_name

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OddsSport:
    """Maps an Odds API sport_key to our canonical sport/league."""

    sport: str
    league: str


# Odds API sport_key -> our sport/league. Extend as leagues go live.
# Empty responses are free, so an out-of-season key costs nothing to leave here.
ODDS_SPORTS: dict[str, OddsSport] = {
    "americanfootball_nfl": OddsSport("nfl", "NFL"),
    # Preseason is a SEPARATE key: the regular-season key does not cover August
    # games, which is why Kalshi's preseason events sat single-source with no
    # consensus to compare against. Also the earliest source of real completed
    # games for outcome resolution.
    "americanfootball_nfl_preseason": OddsSport("nfl", "NFL"),
    "basketball_nba": OddsSport("nba", "NBA"),
}


# The scores endpoint's hard ceiling. daysFrom=4 returns HTTP 422 "Invalid
# daysFrom" — verified live. There is NO deeper history on this endpoint, so an
# outcome not collected inside this window is permanently unavailable from here.
MAX_SCORES_DAYS_FROM = 3


class QuotaExhausted(RuntimeError):
    """Raised instead of spending the last of the monthly API budget."""


class OddsApiClient:
    """Thin httpx wrapper over The Odds API v4 (requires an API key).

    Tracks the remaining monthly quota from response headers and refuses to spend
    below a reserve. Without that, exhaustion is indistinguishable from a quiet
    market: calls start failing, nothing is written, and no signal says why.
    """

    def __init__(self, api_key: str | None = None, base_url: str | None = None, timeout: float = 15.0) -> None:
        self.api_key = api_key or settings.odds_api_key
        self.base_url = (base_url or settings.odds_api_base).rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)
        # Only known after the first response; None means "not yet observed".
        self.quota_remaining: int | None = None
        self.quota_used: int | None = None

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "OddsApiClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _record_quota(self, resp: httpx.Response) -> None:
        """Read the quota counters the API returns on every response."""
        for header, attr in (
            ("x-requests-remaining", "quota_remaining"),
            ("x-requests-used", "quota_used"),
        ):
            raw = resp.headers.get(header)
            if raw is not None:
                try:
                    setattr(self, attr, int(float(raw)))
                except ValueError:
                    pass

    def _check_quota(self) -> None:
        """Refuse a paid call when the remaining budget is at the reserve.

        The reserve exists for resolution: odds can be re-fetched later, but a
        missed scores window loses an outcome forever, so the last credits are
        kept for the irreversible job rather than the repeatable one.
        """
        reserve = settings.odds_api_quota_reserve
        if self.quota_remaining is not None and self.quota_remaining <= reserve:
            raise QuotaExhausted(
                f"{UNHEALTHY_MARKER}: Odds API quota at {self.quota_remaining}, "
                f"at or below the reserve of {reserve}. Refusing further paid calls "
                "so the remaining budget stays available for outcome resolution."
            )

    def _get(self, path: str, params: dict) -> list[dict]:
        """Issue a checked, quota-tracked, redaction-safe GET."""
        if not self.api_key:
            raise ValueError("ODDS_API_KEY is not set")
        self._check_quota()
        resp = self._client.get(path, params={"apiKey": self.api_key, **params})
        self._record_quota(resp)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # The credential can only travel as a query parameter, so any error
            # quoting the URL discloses it. HTTPStatusError embeds the full URL
            # in its message, so it is re-raised redacted.
            raise httpx.HTTPStatusError(
                redact(str(exc)), request=exc.request, response=exc.response
            ) from None
        return resp.json()

    def get_odds(self, sport_key: str, *, regions: str = "us", markets: str = "h2h") -> list[dict]:
        """Return events with bookmaker odds.

        Costs one quota credit — but ONLY if the response contains events;
        empty responses are free (verified against the live counter).
        """
        return self._get(
            f"/sports/{sport_key}/odds",
            {"regions": regions, "markets": markets, "oddsFormat": "american"},
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
        return self._get(f"/sports/{sport_key}/scores/", {"daysFrom": days})


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

    event_id, status = find_event_by_match(session, extract.key)
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


def run_ingest(sport_keys: list[str] | None = None) -> IngestResult:
    """Fetch each configured Odds API sport and append consensus snapshots.

    Returns an :class:`IngestResult` reporting rows WRITTEN, so the scheduler's
    health tracker can distinguish a quiet market from a broken pass. Per-event
    problems are skipped and logged inside :func:`ingest_odds_event`; only
    transient network/API errors propagate, so Prefect retries cover them.

    Each sport costs one API quota unit per pass — hence the deliberately slower
    ``odds_poll_interval_seconds``.
    """
    keys = sport_keys if sport_keys is not None else list(ODDS_SPORTS)
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
                events = client.get_odds(sport_key)
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
