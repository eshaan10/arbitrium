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
from marketedge.db.models import Event, OddsSnapshot
from marketedge.ingestion.events import find_event_by_match
from marketedge.ingestion.normalize import NormalizedSnapshot, normalize_odds_api_consensus
from marketedge.matching import EventKey, MatchStatus
from marketedge.reference.teams import resolve_by_name

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OddsSport:
    """Maps an Odds API sport_key to our canonical sport/league."""

    sport: str
    league: str


# Odds API sport_key -> our sport/league. Extend as leagues go live.
ODDS_SPORTS: dict[str, OddsSport] = {
    "americanfootball_nfl": OddsSport("nfl", "NFL"),
    "basketball_nba": OddsSport("nba", "NBA"),
}


class OddsApiClient:
    """Thin httpx wrapper over The Odds API v4 (requires an API key)."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None, timeout: float = 15.0) -> None:
        self.api_key = api_key or settings.odds_api_key
        self.base_url = (base_url or settings.odds_api_base).rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "OddsApiClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def get_odds(self, sport_key: str, *, regions: str = "us", markets: str = "h2h") -> list[dict]:
        """Return events with bookmaker odds. Costs one quota unit per call."""
        if not self.api_key:
            raise ValueError("ODDS_API_KEY is not set")
        resp = self._client.get(
            f"/sports/{sport_key}/odds",
            params={
                "apiKey": self.api_key,
                "regions": regions,
                "markets": markets,
                "oddsFormat": "american",
            },
        )
        resp.raise_for_status()
        return resp.json()


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


def _insert_consensus_snapshots(session: Session, event_id: uuid_mod.UUID, extract: OddsEventExtract) -> int:
    """Insert consensus snapshots, anchoring each to its authoritative team."""
    key = extract.key
    now = datetime.now(tz=key.start.tzinfo) if key.start.tzinfo else datetime.utcnow()
    team_for = {"home": key.home_team, "away": key.away_team, "draw": None}
    for snap in extract.snapshots:
        session.add(
            OddsSnapshot(
                event_id=event_id,
                source=snap.source,
                outcome=snap.outcome,
                team=team_for.get(snap.outcome),
                implied_probability=snap.implied_probability,
                raw_price=snap.raw_price,
                price_format=snap.price_format,
                liquidity_score=snap.liquidity_score,  # None for sportsbooks
                order_book_depth=snap.order_book_depth,
                ingested_at=now,
                snapshot_time=now,
            )
        )
    return len(extract.snapshots)


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
