"""Application settings, loaded from environment / .env."""

from __future__ import annotations

from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql+psycopg://marketedge:marketedge@localhost:5432/marketedge"

    # Kalshi (Phase 1) — public market reads require no auth.
    kalshi_api_base: str = "https://api.elections.kalshi.com/trade-api/v2"
    kalshi_poll_interval_seconds: int = 300

    # Ingestion scoping (Phase 1). Only these Kalshi series are fetched
    # (server-side filter). Empty => ingest nothing and log a warning, rather
    # than falling back to every open Kalshi market. Accepts a comma-separated
    # list in the env, e.g. KALSHI_SERIES_TICKERS=KXNFLGAME,KXNBAGAME.
    #
    # NoDecode suppresses pydantic-settings' automatic JSON-decode of complex
    # (list) fields from env vars, which would otherwise json.loads() the raw
    # "KXNFLGAME,KXNBAGAME" string and raise BEFORE _split_csv runs. With
    # NoDecode the raw string reaches the mode="before" validator intact.
    kalshi_series_tickers: Annotated[list[str], NoDecode] = []

    # Client-side guard: a market's ticker must match this regex to be ingested.
    # The default screens out multi-game / cross-category / parlay markets that
    # share Kalshi's KX prefix but aren't single-game moneylines. Tighten per
    # sport once the exact ticker format for your target series is known.
    kalshi_moneyline_pattern: str = r"^(?!.*(?:MULTIGAME|CROSSCATEGORY|MULTI|PARLAY)).+$"

    # The Odds API (Phase 2)
    odds_api_base: str = "https://api.the-odds-api.com/v4"
    odds_api_key: str | None = None

    # Kalshi <-> Odds API event matching: a game is matched on sport + unordered
    # team pair, with the two sources' start times allowed to differ by up to this
    # many days (absorbs postponements and UTC-midnight date skew). Beyond this,
    # an event stays provisional and is logged as unmatched. Named/config, not a
    # literal, so we can tune it once real unmatched-event logs come in.
    event_match_window_days: int = 3

    # Minimum bookmakers required before a sportsbook consensus is trusted enough
    # to score a divergence against. A "median" over one or two books is not a
    # consensus, and far from kickoff most events have exactly one book quoting.
    # Below this floor the event is still stored and still returned by
    # /divergences, but flagged 'insufficient_consensus' with NO divergence score
    # — an excluded event is honest, a precise-looking number over one book is not.
    min_consensus_books: int = 3

    # The Odds API poll interval. Separate from Kalshi's: sportsbook lines move
    # more slowly than a live order book, and each call costs API quota, so this
    # is deliberately less frequent. Poll ORDER does not matter — both ingestion
    # paths run the shared matcher, so whichever arrives first creates the event.
    odds_poll_interval_seconds: int = 900

    # --- Ingest health (see scheduler/health.py) ---------------------------
    # A pass that raises is unambiguously broken, so the failure threshold is
    # tight: 3 consecutive failures (~15 min at a 300s Kalshi interval) escalates
    # to ERROR. This is the signal that the 896-failure outage would have tripped.
    ingest_max_consecutive_failures: int = 3

    # Zero rows written is NOT inherently an error — the dedup trigger suppresses
    # unchanged prices, so a quiet market legitimately writes nothing for a long
    # time. These thresholds are therefore generous, and expressed in SECONDS of
    # continuous silence rather than run counts, so they mean the same thing
    # regardless of poll interval.
    ingest_zero_write_warn_seconds: int = 3600  # ~1h quiet -> WARNING
    ingest_zero_write_error_seconds: int = 21600  # ~6h quiet -> ERROR

    # /health marks a source stale when its newest snapshot is older than this
    # multiple of that source's poll interval. 6x absorbs a couple of transient
    # failures without crying wolf, while still surfacing an outage in ~30 min.
    ingest_staleness_interval_multiple: int = 6

    log_level: str = "INFO"

    @field_validator("kalshi_series_tickers", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        """Allow a comma-separated env string in addition to a JSON list."""
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v


settings = Settings()
