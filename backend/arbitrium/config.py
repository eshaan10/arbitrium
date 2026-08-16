"""Application settings, loaded from environment / .env."""

from __future__ import annotations

from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql+psycopg://arbitrium:arbitrium@localhost:5432/arbitrium"

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
    #
    # Only a FLOOR now — the effective interval is chosen adaptively per pass by
    # arbitrium.ingestion.polling. Kept as the scheduler's tick for the source.
    odds_poll_interval_seconds: int = 900

    # --- Adaptive Odds API pacing (see ingestion/polling.py) ----------------
    # The plan allows 500 credits/month (~16/day) and bills only requests that
    # return events. A flat 900s interval costs ~96/day and burns the month in
    # five days. These tiers spend the budget near kickoff, where lines actually
    # move and where closing-line value is measured, instead of spreading it
    # evenly over games that are weeks away.
    odds_poll_near_horizon_seconds: int = 86_400  # "near" = within 24h of kickoff
    odds_poll_mid_horizon_seconds: int = 604_800  # "mid"  = within 7d
    odds_poll_near_seconds: int = 3_600  # hourly inside 24h
    odds_poll_mid_seconds: int = 21_600  # 4x/day inside 7d
    odds_poll_far_seconds: int = 86_400  # daily beyond that, or no games at all

    # Stop making PAID calls once the remaining monthly quota falls below this.
    # Without it, exhaustion looks exactly like a quiet market: calls fail, no
    # rows are written, and nothing says why. Reserve leaves room for resolution,
    # which is perishable (a missed 3-day window loses an outcome permanently).
    odds_api_quota_reserve: int = 50

    # --- Outcome resolution (Phase 3) --------------------------------------
    # The scores endpoint caps daysFrom at 3 (4 => HTTP 422). There is NO deeper
    # history: an outcome not collected within ~3 days of the final whistle is
    # permanently unavailable from this source. Every constant here exists to buy
    # redundancy inside that non-negotiable window.
    resolution_poll_interval_seconds: int = 21_600  # 6h => ~14 chances per game
    resolution_days_from: int = 3  # provider HARD MAX; validated client-side
    resolution_grace_minutes: int = 180  # don't ask before a game could be final
    resolution_unresolvable_after_hours: int = 84  # 3.5d; past this the data is gone

    # Resolution legitimately writes nothing for weeks in the off-season, so the
    # generic zero-write alarm is the WRONG signal here — it would scream all
    # summer and say nothing during the one week it matters. The real alarm is
    # `hours_until_next_data_loss` in /health. These are set effectively off.
    resolution_zero_write_warn_seconds: int = 2_592_000  # 30d
    resolution_zero_write_error_seconds: int = 7_776_000  # 90d

    # Documentation-as-config: the ceiling every pacing decision above answers to.
    odds_api_monthly_credit_budget: int = 500

    # --- Calibration (Phase 3) ---------------------------------------------
    # Sample-size gates. This system starts at n=1 and a full NFL season is only
    # ~290 games, so these are set to keep a first-season curve honest rather
    # than to unlock features quickly. Counted in GAMES, never in outcome rows:
    # the two sides of a two-way market are perfectly anti-correlated, so
    # counting both would shrink every interval by sqrt(2) for free.
    calibration_min_report_samples: int = 25  # below this, no rate at all
    calibration_min_fit_samples: int = 200  # below this, no isotonic fit
    calibration_trusted_samples: int = 1000  # below this, always "provisional"

    # How often to record standing recommendations. Frequent enough that a call
    # existing only briefly still gets captured before kickoff, but this is a
    # pure database pass — no API cost — so the interval is about coverage, not
    # budget.
    calibration_poll_interval_seconds: int = 1_800  # 30 min

    # Reliability-curve bins. Few, because 290 games across 10 bins is ~29 each.
    calibration_bins: int = 5

    # Closing-line value: the last snapshot strictly before kickoff is the
    # "closing" price. A game needs at least this many minutes of pre-kickoff
    # history for the close to mean anything.
    clv_min_lead_minutes: int = 30

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
