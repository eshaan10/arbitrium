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

    log_level: str = "INFO"

    @field_validator("kalshi_series_tickers", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        """Allow a comma-separated env string in addition to a JSON list."""
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v


settings = Settings()
