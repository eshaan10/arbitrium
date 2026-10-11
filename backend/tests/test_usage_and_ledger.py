"""/usage, the append-only ledger tables, and the API's promise never to call out.

The Odds API is only ever called by the scheduler. A user-facing request that
spent a credit would put the monthly budget in the hands of whoever refreshes a
page, so these pin that every endpoint reads the database and nothing else.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from arbitrium.api import main as api
from arbitrium.config import settings
from arbitrium.db.models import CreditLog, Event, OddsCheckpoint
from arbitrium.ingestion import governor

UTC = timezone.utc


def _log(db, *, at, credits, remaining, sport="nfl", endpoint="odds", checkpoint=None):
    db.add(CreditLog(called_at=at, sport=sport, sport_key="americanfootball_nfl",
                     endpoint=endpoint, checkpoint=checkpoint, credits_used=credits,
                     remaining=remaining, used=500 - remaining))
    db.flush()


def test_usage_reports_the_period_from_the_ledger(db_session):
    now = datetime(2099, 5, 10, 18, tzinfo=UTC)
    _log(db_session, at=now - timedelta(days=8), credits=1, remaining=480)  # earlier this period
    _log(db_session, at=now - timedelta(hours=5), credits=0, remaining=470, endpoint="events")
    _log(db_session, at=now - timedelta(hours=3), credits=1, remaining=469, checkpoint="t6h")
    _log(db_session, at=now - timedelta(hours=1), credits=1, remaining=468, sport="nba",
         checkpoint="close")

    out = governor.usage_report(db_session, now=now)

    assert out["remaining"] == 468 and out["remaining_source"] == "credit_log"
    assert out["period_start"] == "2099-05-01T00:00:00+00:00"
    assert out["next_reset"] == "2099-06-01T00:00:00+00:00"
    assert out["reserve"] == 50
    assert out["spent_today"] == 2
    assert out["spent_this_period"] == 3
    assert out["days_until_reset"] == 22
    assert out["daily_allowance"] == pytest.approx((470 - 50) / 22, abs=0.01)
    assert {(r["sport"], r["endpoint"]): r["credits"] for r in out["by_sport"]} == {
        ("nfl", "odds"): 2, ("nfl", "events"): 0, ("nba", "odds"): 1,
    }
    assert out["recent_calls"][0]["checkpoint"] == "close"


def test_usage_with_an_empty_ledger_says_where_its_number_came_from(monkeypatch):
    class _Empty:
        def execute(self, *a, **k):
            class R:
                def first(self):
                    return None

                def scalar(self):
                    return 0

                def all(self):
                    return []

                def scalars(self):
                    return []

            return R()

    monkeypatch.setattr(settings, "odds_credits_remaining_seed", None)
    out = governor.usage_report(_Empty(), now=datetime(2026, 10, 10, tzinfo=UTC))
    assert (out["remaining"], out["remaining_source"], out["tier"]) == (None, "unknown", "unknown")

    monkeypatch.setattr(settings, "odds_credits_remaining_seed", 212)
    out = governor.usage_report(_Empty(), now=datetime(2026, 10, 10, tzinfo=UTC))
    assert (out["remaining"], out["remaining_source"]) == (212, "seed")


# --- append-only, enforced by the database ---------------------------------------


@pytest.mark.parametrize("table", ["credit_log", "odds_checkpoints"])
@pytest.mark.parametrize("statement", ["UPDATE {t} SET id = id", "DELETE FROM {t}"])
def test_ledger_tables_reject_update_and_delete(db_session, table, statement):
    ev = Event(sport="nfl", league="NFL", home_team="Seattle Seahawks",
               away_team="Los Angeles Rams", scheduled_start=datetime(2099, 1, 1, tzinfo=UTC))
    db_session.add(ev)
    db_session.flush()
    _log(db_session, at=datetime(2099, 1, 1, tzinfo=UTC), credits=1, remaining=1)
    db_session.add(OddsCheckpoint(event_id=ev.id, sport="nfl", checkpoint="close",
                                  status="captured"))
    db_session.flush()

    nested = db_session.begin_nested()
    with pytest.raises(DBAPIError, match="append-only"):
        db_session.execute(text(statement.format(t=table)))
    nested.rollback()


# --- the API never calls out --------------------------------------------------------


@pytest.fixture
def no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("a user-facing request made an outbound HTTP call")

    monkeypatch.setattr(httpx.Client, "send", refuse)
    monkeypatch.setattr(httpx.AsyncClient, "send", refuse)
    monkeypatch.setattr(settings, "odds_api_key", "would-be-spent")


def test_usage_and_health_read_only_the_database(db_session, no_network):
    from fastapi import Response

    api.usage(db=db_session)
    api.health(strict=False, response=Response(), db=db_session)


def test_the_api_module_has_no_route_to_the_paid_client():
    import inspect

    source = inspect.getsource(api)
    for name in ("OddsApiClient", "run_ingest", "run_due_passes", "get_odds", "get_scores"):
        assert name not in source
