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

    # --- Odds API credit budget (see ingestion/polling.py, ingestion/governor.py)
    # The free tier is 500 credits a month, reset on the 1st at 00:00 UTC. h2h
    # in one region costs 1 credit per sport per /odds call; /events and /sports
    # are free. A flat 15-minute interval once burned the month in five days, so
    # nothing here is an interval: each game is priced at a few game-clock
    # checkpoints, and only while Kalshi has a market to compare it against.
    odds_api_monthly_credit_budget: int = 500

    # The last tenth of the month is never spent, by anything. Without a floor,
    # exhaustion looks exactly like a quiet market: calls fail, nothing is
    # written, and nothing says why.
    odds_api_reserve_fraction: float = 0.10

    # Starting balance for the governor when credit_log is EMPTY (first deploy).
    # Set at deploy time from the dashboard; the first response, even a free
    # /events one, replaces it with the real number. Unset and empty means the
    # balance is unknown, and no paid call is made until a free call reveals it.
    odds_credits_remaining_seed: int | None = None

    # Which sports may spend credits. NBA and NHL stay off until their team
    # registries land: listed but unresolvable, NBA once billed a credit a pass
    # for events that were all skipped. CSV in the env: ODDS_SPORTS_ENABLED=nfl,nba
    odds_sports_enabled: Annotated[list[str], NoDecode] = ["nfl"]

    # Cap on NON-closing /odds calls per sport per UTC day. Closing-line calls
    # are exempt (see governor.admit), so a heavy slate never loses its closes.
    odds_passes_per_day_nfl: int = 6
    odds_passes_per_day_nba: int = 4
    odds_passes_per_day_nhl: int = 4

    # Kalshi gating: a sport spends nothing unless Kalshi lists a game for it
    # starting within this horizon AND the Kalshi poller has succeeded recently.
    # A consensus price with no Kalshi market to compare it to buys nothing.
    kalshi_gate_horizon_hours: int = 36
    kalshi_gate_max_age_seconds: int = 1_800

    # How often the free /events listing is refreshed per sport key, and how
    # often the scheduler re-reads the plan between passes. Both cost nothing.
    odds_events_refresh_seconds: int = 10_800
    odds_replan_seconds: int = 300

    # Below this much resting Kalshi depth ($ at best bid/ask) a game is "thin":
    # the first to lose its non-closing checkpoints when the month is over pace.
    odds_thin_liquidity_dollars: float = 1_000.0

    # Odds passes run hours apart by design, so the generic one-hour quiet alarm
    # would fire between every pair of them.
    odds_zero_write_warn_seconds: int = 129_600  # 36h
    odds_zero_write_error_seconds: int = 259_200  # 72h

    # --- Outcome resolution (Phase 3) --------------------------------------
    # The scores endpoint caps daysFrom at 3 (4 => HTTP 422). There is NO deeper
    # history: an outcome not collected within ~3 days of the final whistle is
    # permanently unavailable from this source. Every constant here exists to buy
    # redundancy inside that non-negotiable window.
    # ESPN is the primary resolver (free). The paid scores endpoint is only asked
    # about games ESPN still has not resolved this long after kickoff, which
    # leaves it ~36h of the 84h window to recover them.
    resolution_odds_fallback_after_hours: int = 48
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

    # Fail fast: the scheduler exits non-zero (and the platform restarts it) once
    # one source has failed this many passes in a row with NO HTTP response from
    # upstream. 6 is ~30 min for Kalshi. Upstream errors (any HTTP status) never
    # count — a restart cannot fix someone else's outage. See scheduler/flows.py.
    scheduler_exit_after_consecutive_failures: int = 6

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

    @field_validator("odds_credits_remaining_seed", mode="before")
    @classmethod
    def _blank_is_unset(cls, v: object) -> object:
        """``ODDS_CREDITS_REMAINING_SEED=`` (as in .env.example) means unset, not a crash."""
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("kalshi_series_tickers", "odds_sports_enabled", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        """Allow a comma-separated env string in addition to a JSON list."""
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v


settings = Settings()
