"""Adaptive poll pacing and the quota guard.

The Phase 2 poller burned a 500-credit monthly budget in five days. These pin the
pacing that fixes it, and the guard that makes exhaustion loud instead of looking
exactly like a quiet market.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from arbitrium.config import settings
from arbitrium.ingestion.odds_api import OddsApiClient, QuotaExhausted
from arbitrium.ingestion.polling import poll_interval_for, projected_daily_credits
from arbitrium.logging_config import UNHEALTHY_MARKER

UTC = timezone.utc
NOW = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)


def _in(**kw):
    return NOW + timedelta(**kw)


# --- tiers -------------------------------------------------------------------


def test_near_kickoff_polls_hourly():
    assert poll_interval_for(_in(hours=3), now=NOW) == settings.odds_poll_near_seconds


def test_mid_range_polls_less_often():
    assert poll_interval_for(_in(days=3), now=NOW) == settings.odds_poll_mid_seconds


def test_far_out_polls_daily():
    assert poll_interval_for(_in(days=30), now=NOW) == settings.odds_poll_far_seconds


def test_no_scheduled_games_falls_to_the_far_tier():
    """The off-season case. Costs nothing anyway — empty responses are free."""
    assert poll_interval_for(None, now=NOW) == settings.odds_poll_far_seconds


def test_a_game_in_progress_counts_as_near():
    """Its line is still closing and its result is about to exist."""
    assert poll_interval_for(_in(hours=-1), now=NOW) == settings.odds_poll_near_seconds


def test_tier_boundaries_are_inclusive():
    assert poll_interval_for(_in(hours=24), now=NOW) == settings.odds_poll_near_seconds
    assert poll_interval_for(
        _in(hours=24, seconds=1), now=NOW
    ) == settings.odds_poll_mid_seconds
    assert poll_interval_for(_in(days=7), now=NOW) == settings.odds_poll_mid_seconds
    assert poll_interval_for(
        _in(days=7, seconds=1), now=NOW
    ) == settings.odds_poll_far_seconds


# --- the budget actually fits ------------------------------------------------


def test_adaptive_pacing_fits_the_monthly_budget():
    """The whole point: the old flat interval did not.

    Worst realistic case is one in-season sport sitting in the near tier all day.
    """
    old_flat = projected_daily_credits(900, paid_sports=1)
    assert old_flat > 90  # ~96/day — the bug

    budget_per_day = settings.odds_api_monthly_credit_budget / 30
    assert projected_daily_credits(settings.odds_poll_near_seconds) <= 24
    assert projected_daily_credits(settings.odds_poll_mid_seconds) < budget_per_day
    assert projected_daily_credits(settings.odds_poll_far_seconds) < budget_per_day


# --- quota guard -------------------------------------------------------------


def _client_with_quota(remaining: int) -> OddsApiClient:
    c = OddsApiClient(api_key="dummy")
    c.quota_remaining = remaining
    return c


def test_guard_blocks_at_the_reserve(caplog):
    c = _client_with_quota(settings.odds_api_quota_reserve)
    with caplog.at_level(logging.ERROR), pytest.raises(QuotaExhausted) as exc:
        c.get_odds("americanfootball_nfl")
    assert UNHEALTHY_MARKER in str(exc.value)
    c.close()


def test_guard_allows_above_the_reserve():
    """Above the reserve it must attempt the call (network error, not QuotaExhausted)."""
    c = _client_with_quota(settings.odds_api_quota_reserve + 1)
    c.base_url = "http://127.0.0.1:1"  # nothing listening
    c._client = httpx.Client(base_url=c.base_url, timeout=0.2)
    with pytest.raises(Exception) as exc:
        c.get_odds("americanfootball_nfl")
    assert not isinstance(exc.value, QuotaExhausted)
    c.close()


def test_unknown_quota_does_not_block():
    """Before the first response the remaining budget is unknown, not zero."""
    c = OddsApiClient(api_key="dummy")
    assert c.quota_remaining is None
    c._check_quota()  # must not raise
    c.close()


def test_quota_is_recorded_from_response_headers():
    c = OddsApiClient(api_key="dummy")
    resp = httpx.Response(
        200, headers={"x-requests-remaining": "461", "x-requests-used": "39"}
    )
    c._record_quota(resp)
    assert (c.quota_remaining, c.quota_used) == (461, 39)
    c.close()
