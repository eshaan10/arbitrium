"""The credit governor: how much of the month may be spent today, and on what.

Every Odds API response carries the balance (``x-requests-remaining``) and the
cost of that call (``x-requests-last``). Each one is written to ``credit_log``,
and the governor paces the month from that ledger:

* **Reserve.** The last tenth of the monthly budget is never spent, by anything —
  not odds, not resolution. Exhaustion is the one failure that looks exactly
  like a quiet market.
* **Daily allowance.** What remains above the reserve at the start of the UTC
  day, divided by the days left until the reset on the 1st at 00:00 UTC. Taken
  at the START of the day, so it holds still while today's calls spend it.
* **Closes come off the top.** The close is what CLV is measured against, and a
  heavy slate is the normal case for a sports calendar, so **a close is never
  dropped for pace** — only the reserve stops one. To keep that promise to the
  end of the month, the allowance first sets aside the trailing week's closing
  spend for every remaining day; pace is judged on what is left.
* **Pace tiers** (non-closing spend against that remainder). Under it, every
  planned pass runs. Over it, T-24h checkpoints and thin-liquidity games go
  first. Well over it, only closes run.
* **Per-sport cap.** ``passes_per_day`` bounds the NON-closing calls a sport
  makes per UTC day. When the planned day exceeds it, the passes covering the
  highest-priority games keep the slots: nearest to start, then most liquid.

The core (:class:`Budget`, :func:`admit`) is pure; the rest reads and writes the
ledger and never raises into a pass.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from arbitrium.config import settings
from arbitrium.db.engine import get_session
from arbitrium.db.models import CreditLog
from arbitrium.ingestion.polling import (
    CHECKPOINT_T24H,
    PlannedPass,
    utc_day_start,
)

logger = logging.getLogger(__name__)

# Well past the allowance, only closes run. 1.5x lets a busy day borrow from a
# quiet one before everything but the close is shut off.
CLOSE_ONLY_PACE = 1.5

# The window the closing-spend forecast is averaged over: one week covers every
# weekday's slate shape (NFL Sundays, NBA/NHL back-to-backs).
CLOSE_RATE_WINDOW = timedelta(days=7)


def reserve_credits() -> int:
    """The untouchable floor: 10% of the monthly budget, rounded up."""
    return math.ceil(settings.odds_api_monthly_credit_budget * settings.odds_api_reserve_fraction)


def period_start(moment: datetime) -> datetime:
    """When the current quota period began: the 1st of this month, 00:00 UTC."""
    return utc_day_start(moment).replace(day=1)


def next_reset(moment: datetime) -> datetime:
    start = period_start(moment)
    return start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(
        month=start.month + 1
    )


class Tier(str, Enum):
    UNKNOWN = "unknown"  # no balance observed yet: nothing paid until one is
    NORMAL = "normal"
    OVER_PACE = "over_pace"
    CLOSE_ONLY = "close_only"
    RESERVE = "reserve"  # at the floor: nothing paid at all


@dataclass(frozen=True)
class Budget:
    """The month's position at one moment."""

    remaining: int | None
    spent_today: int
    now: datetime
    close_spent_today: int = 0
    # Expected closing-line credits per day (trailing average). Set aside before
    # any other checkpoint is allowed to spend.
    close_rate: float = 0.0

    @property
    def reserve(self) -> int:
        return reserve_credits()

    @property
    def days_left(self) -> int:
        """Whole UTC days from the start of today until the reset, at least 1."""
        delta = next_reset(self.now) - utc_day_start(self.now)
        return max(1, delta.days)

    @property
    def daily_allowance(self) -> float:
        if self.remaining is None:
            return 0.0
        at_day_start = self.remaining + self.spent_today
        return max(0.0, (at_day_start - self.reserve) / self.days_left)

    @property
    def non_close_allowance(self) -> float:
        """Today's share for everything that is not a close."""
        return max(0.0, self.daily_allowance - self.close_rate)

    def affordable(self, cost: int) -> bool:
        """Whether ``cost`` can be spent without dipping into the reserve."""
        return self.remaining is not None and self.remaining - cost >= self.reserve

    def tier(self, cost: int = 1) -> Tier:
        if self.remaining is None:
            return Tier.UNKNOWN
        if not self.affordable(cost):
            return Tier.RESERVE
        allowance = self.non_close_allowance
        spent = self.spent_today - self.close_spent_today
        if spent >= CLOSE_ONLY_PACE * allowance:
            return Tier.CLOSE_ONLY
        if spent >= allowance:
            return Tier.OVER_PACE
        return Tier.NORMAL


@dataclass(frozen=True)
class Decision:
    admitted: bool
    reason: str


def admit(
    candidate: PlannedPass,
    budget: Budget,
    *,
    cap: int,
    non_close_calls_today: int,
    later_today: list[PlannedPass] = (),
) -> Decision:
    """Whether to spend on ``candidate`` now. Pure.

    ``later_today`` is the rest of the sport's plan before the next UTC
    midnight; it is how the cap prefers the most valuable passes rather than
    simply the earliest ones.
    """
    tier = budget.tier(candidate.cost)
    if tier is Tier.UNKNOWN:
        return Decision(False, "balance_unknown")
    if tier is Tier.RESERVE:
        return Decision(False, "reserve")
    if candidate.has_close:
        # Exempt from pace and from the cap: see the module docstring.
        return Decision(True, f"close:{tier.value}")
    if tier is Tier.CLOSE_ONLY:
        return Decision(False, "close_only")
    if tier is Tier.OVER_PACE and not any(
        cp.rank > CHECKPOINT_T24H.rank and not game.is_thin() for game, cp in candidate.covers
    ):
        return Decision(False, "over_pace")

    slots = cap - non_close_calls_today
    if slots < candidate.cost:
        return Decision(False, "daily_cap")
    rivals = [p for p in later_today if not p.has_close]
    # Highest priority first; among equals, the earlier pass.
    ahead = sorted(
        rivals + [candidate], key=lambda p: (p.priority, -p.at.timestamp()), reverse=True
    )
    used = 0
    for p in ahead:
        if p is candidate:
            return Decision(True, tier.value) if used + p.cost <= slots else Decision(
                False, "daily_cap_priority"
            )
        used += p.cost
    raise AssertionError("unreachable")  # pragma: no cover


# ---------------------------------------------------------------------------
# The ledger
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CallRecord:
    """What one Odds API response cost, read from its headers."""

    endpoint: str  # odds | scores | events
    sport_key: str
    credits_used: int
    remaining: int | None
    used: int | None
    events_returned: int | None
    sport: str | None = None
    checkpoint: str | None = None


def record_call(record: CallRecord, *, called_at: datetime | None = None) -> None:
    """Append one call to credit_log in its own committed transaction.

    Separate from the ingest transaction for the same reason ingest_runs is:
    the credit was spent whether or not the rows that followed were stored.
    Never raises — but a failure is loud, because an unlogged credit makes the
    governor think the month is richer than it is.
    """
    try:
        session = get_session()
        try:
            values = dict(record.__dict__)
            if called_at is not None:
                values["called_at"] = called_at
            session.add(CreditLog(**values))
            session.commit()
        finally:
            session.close()
    except Exception:  # noqa: BLE001
        logger.error(
            "Could not record an Odds API call in credit_log (%s %s, %s credits); "
            "the governor will under-count today's spend.",
            record.endpoint, record.sport_key, record.credits_used, exc_info=True,
        )


@dataclass(frozen=True)
class Balance:
    remaining: int | None
    source: str  # credit_log | period_reset | seed | unknown
    observed_at: datetime | None = None


def current_balance(session: Session, *, now: datetime | None = None) -> Balance:
    """The best-known remaining balance.

    The latest logged header in THIS period wins. A log that only reaches into
    an earlier period means the quota has reset since, so the month is full.
    An empty log falls back to the deploy-time seed; with no seed the balance
    is unknown and no paid call is admitted until a free one reveals it.
    """
    moment = now or datetime.now(timezone.utc)
    latest = session.execute(
        select(CreditLog.remaining, CreditLog.called_at)
        .where(CreditLog.remaining.is_not(None))
        .order_by(CreditLog.called_at.desc(), CreditLog.id.desc())
        .limit(1)
    ).first()
    if latest is not None:
        if latest.called_at >= period_start(moment):
            return Balance(latest.remaining, "credit_log", latest.called_at)
        return Balance(settings.odds_api_monthly_credit_budget, "period_reset", latest.called_at)
    if settings.odds_credits_remaining_seed is not None:
        return Balance(settings.odds_credits_remaining_seed, "seed")
    return Balance(None, "unknown")


def spent_since(session: Session, since: datetime, *, sport: str | None = None,
                endpoint: str | None = None, checkpoint: str | None = None,
                exclude_checkpoint: str | None = None) -> int:
    stmt = select(func.coalesce(func.sum(CreditLog.credits_used), 0)).where(
        CreditLog.called_at >= since
    )
    if sport is not None:
        stmt = stmt.where(CreditLog.sport == sport)
    if endpoint is not None:
        stmt = stmt.where(CreditLog.endpoint == endpoint)
    if checkpoint is not None:
        stmt = stmt.where(CreditLog.checkpoint == checkpoint)
    if exclude_checkpoint is not None:
        stmt = stmt.where(
            (CreditLog.checkpoint.is_(None)) | (CreditLog.checkpoint != exclude_checkpoint)
        )
    return int(session.execute(stmt).scalar() or 0)


def load_budget(session: Session, *, now: datetime | None = None) -> Budget:
    moment = now or datetime.now(timezone.utc)
    today = utc_day_start(moment)
    week = spent_since(session, moment - CLOSE_RATE_WINDOW, endpoint="odds", checkpoint="close")
    return Budget(
        remaining=current_balance(session, now=moment).remaining,
        spent_today=spent_since(session, today),
        now=moment,
        close_spent_today=spent_since(session, today, endpoint="odds", checkpoint="close"),
        close_rate=week / CLOSE_RATE_WINDOW.days,
    )


def non_close_odds_calls_today(session: Session, sport: str, *, now: datetime) -> int:
    """Credits a sport has spent today on non-closing /odds calls — the cap's meter."""
    return spent_since(
        session, utc_day_start(now), sport=sport, endpoint="odds", exclude_checkpoint="close"
    )


def usage_report(session: Session, *, now: datetime | None = None, recent: int = 20) -> dict:
    """Everything /usage shows. DB-only: never calls the API."""
    moment = now or datetime.now(timezone.utc)
    start = period_start(moment)
    balance = current_balance(session, now=moment)
    budget = load_budget(session, now=moment)
    by_sport = session.execute(
        select(
            CreditLog.sport,
            CreditLog.endpoint,
            func.coalesce(func.sum(CreditLog.credits_used), 0),
            func.count(),
        )
        .where(CreditLog.called_at >= start)
        .group_by(CreditLog.sport, CreditLog.endpoint)
        .order_by(CreditLog.sport, CreditLog.endpoint)
    ).all()
    rows = session.execute(
        select(CreditLog).order_by(CreditLog.called_at.desc(), CreditLog.id.desc()).limit(recent)
    ).scalars()
    return {
        "period_start": start.isoformat(),
        "next_reset": next_reset(moment).isoformat(),
        "monthly_budget": settings.odds_api_monthly_credit_budget,
        "reserve": reserve_credits(),
        "remaining": balance.remaining,
        "remaining_source": balance.source,
        "remaining_observed_at": balance.observed_at.isoformat() if balance.observed_at else None,
        "spent_this_period": spent_since(session, start),
        "spent_today": budget.spent_today,
        "daily_allowance": round(budget.daily_allowance, 2),
        "close_rate_per_day": round(budget.close_rate, 2),
        "non_close_allowance": round(budget.non_close_allowance, 2),
        "days_until_reset": budget.days_left,
        "tier": budget.tier().value,
        "by_sport": [
            {"sport": s, "endpoint": e, "credits": int(c), "calls": int(n)}
            for s, e, c, n in by_sport
        ],
        "recent_calls": [
            {
                "called_at": r.called_at.isoformat(),
                "sport": r.sport,
                "sport_key": r.sport_key,
                "endpoint": r.endpoint,
                "checkpoint": r.checkpoint,
                "credits_used": r.credits_used,
                "remaining": r.remaining,
                "events_returned": r.events_returned,
            }
            for r in rows
        ],
    }


def resolution_affordable(cost: int, *, now: datetime | None = None) -> bool:
    """Resolution is irreversible, so it ignores pace — but never the reserve."""
    session = get_session()
    try:
        return load_budget(session, now=now).affordable(cost)
    finally:
        session.close()

