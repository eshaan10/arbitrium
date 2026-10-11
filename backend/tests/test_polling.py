"""The Odds API client's side of the budget: headers, the ledger, and the floor.

The Phase 2 poller burned a 500-credit monthly budget in five days. The pacing
that replaced it lives in the plan and the governor (test_schedule.py,
test_governor.py); these pin what the client itself guarantees — every
response is read and logged, and no call ever dips into the reserve, whoever
makes it.
"""

from __future__ import annotations

import httpx
import pytest

from arbitrium.ingestion import governor
from arbitrium.ingestion.odds_api import OddsApiClient, QuotaExhausted
from arbitrium.logging_config import UNHEALTHY_MARKER

RESERVE = governor.reserve_credits()


def _client(handler=None, *, remaining=None):
    """A client whose ledger is a list and whose network is ``handler``."""
    calls: list[governor.CallRecord] = []
    c = OddsApiClient(api_key="dummy", recorder=calls.append)
    if handler is not None:
        c._client = httpx.Client(base_url=c.base_url, transport=httpx.MockTransport(handler))
    c.quota_remaining = remaining
    return c, calls


def _respond(body, *, status=200, **headers):
    hdrs = {f"x-requests-{k}": str(v) for k, v in headers.items()}
    return lambda request: httpx.Response(status, json=body, headers=hdrs)


# --- the floor ----------------------------------------------------------------


def test_guard_blocks_a_call_that_would_dip_into_the_reserve():
    c, _ = _client(remaining=RESERVE)
    with pytest.raises(QuotaExhausted) as exc:
        c.get_odds("americanfootball_nfl")
    assert UNHEALTHY_MARKER in str(exc.value)
    c.close()


def test_guard_allows_spending_down_to_exactly_the_reserve():
    c, _ = _client(_respond([{"id": "e1"}], remaining=RESERVE, last=1), remaining=RESERVE + 1)
    assert c.get_odds("americanfootball_nfl") == [{"id": "e1"}]
    c.close()


def test_guard_charges_a_scores_call_its_two_credits():
    c, _ = _client(remaining=RESERVE + 1)
    with pytest.raises(QuotaExhausted):
        c.get_scores("americanfootball_nfl")
    c.close()


def test_a_free_call_is_never_blocked():
    """/events is how the balance is learned, so it must work even at the floor."""
    c, calls = _client(_respond([], remaining=RESERVE, last=0), remaining=0)
    assert c.get_events("americanfootball_nfl") == []
    assert calls[0].endpoint == "events" and calls[0].credits_used == 0
    c.close()


def test_unknown_quota_does_not_block():
    """Before the first response the remaining budget is unknown, not zero."""
    c, _ = _client()
    assert c.quota_remaining is None
    c._check_quota()  # must not raise
    c.close()


def test_a_call_with_no_response_is_not_blocked_by_the_floor():
    """Above the reserve it must attempt the call (network error, not QuotaExhausted)."""
    def refuse(request):
        raise httpx.ConnectError("refused")

    c, calls = _client(refuse, remaining=RESERVE + 1)
    with pytest.raises(httpx.ConnectError):
        c.get_odds("americanfootball_nfl")
    assert calls == []  # no response, nothing spent, nothing logged
    c.close()


# --- headers and the ledger ---------------------------------------------------------


def test_quota_is_recorded_from_response_headers():
    c, _ = _client()
    c._record_quota(httpx.Response(
        200, headers={"x-requests-remaining": "461", "x-requests-used": "39",
                      "x-requests-last": "1"},
    ))
    assert (c.quota_remaining, c.quota_used, c.quota_last) == (461, 39, 1)
    c.close()


def test_every_paid_call_is_logged_with_its_header_cost():
    c, calls = _client(_respond([{"id": "a"}, {"id": "b"}], remaining=410, used=90, last=1))
    c.get_odds("americanfootball_nfl", checkpoint="close")
    (rec,) = calls
    assert rec == governor.CallRecord(
        endpoint="odds", sport_key="americanfootball_nfl", sport="nfl", checkpoint="close",
        credits_used=1, remaining=410, used=90, events_returned=2,
    )
    c.close()


def test_a_scores_call_logs_what_the_header_says_it_cost():
    c, calls = _client(_respond([], remaining=400, used=100, last=2))
    c.get_scores("basketball_nba")
    assert (calls[0].endpoint, calls[0].sport, calls[0].credits_used) == ("scores", "nba", 2)
    c.close()


def test_a_missing_cost_header_logs_the_expected_cost(caplog):
    """Over-counting a credit is safe; under-counting is how a month runs out."""
    c, calls = _client(_respond([{"id": "a"}], remaining=400))
    c.get_odds("americanfootball_nfl")
    assert calls[0].credits_used == 1
    assert "no x-requests-last" in caplog.text
    c.close()


def test_an_empty_odds_response_is_free_even_without_the_header():
    c, calls = _client(_respond([], remaining=400))
    c.get_odds("americanfootball_nfl")
    assert calls[0].credits_used == 0 and calls[0].events_returned == 0
    c.close()


def test_a_stale_cost_header_is_not_carried_into_the_next_call():
    responses = iter([_respond([{"id": "a"}], last=1), _respond([])])
    c, calls = _client(lambda request: next(responses)(request))
    c.get_odds("americanfootball_nfl")
    c.get_odds("americanfootball_nfl")
    assert [r.credits_used for r in calls] == [1, 0]
    c.close()


def test_an_error_response_is_logged_and_still_raised_redacted():
    c, calls = _client(_respond({"message": "bad"}, status=401, remaining=400, last=0))
    with pytest.raises(httpx.HTTPStatusError) as exc:
        c.get_odds("americanfootball_nfl")
    assert "dummy" not in str(exc.value)
    assert calls[0].credits_used == 0 and calls[0].events_returned is None
    c.close()


def test_default_recorder_is_the_credit_log():
    c = OddsApiClient(api_key="dummy")
    assert c._recorder is governor.record_call
    c.close()
