"""Closing-line value: did the price move our way after we called it?

The only self-assessment available before enough games resolve. Calibration needs
outcomes, and outcomes arrive at ~15 a week from September; CLV needs only price
history, which we already hold, and it becomes measurable the moment a game
KICKS OFF rather than when it finishes.

WHY IT IS WORTH MEASURING AT ALL. The closing line is the market's final,
best-informed price — the point at which the most money has been staked and the
most information absorbed. Consistently buying at prices the market later moves
past is the standard evidence that a signal is real, and it shows up in far
fewer observations than outcome calibration, because it is not diluted by the
randomness of who actually won. A team can win at 20% and a call can still have
been good.

It is NOT proof of profit and must never be presented as such: positive CLV on a
price nobody could fill, or on a market that later reverts, pays nothing. It is
evidence about the SIGNAL, not about the money.

CLV is measured in probability points on Kalshi's own executable prices, since
that is what a user would actually have paid. Sign convention: positive means the
closing price moved in the direction of the call.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from marketedge.config import settings
from marketedge.db.models import Event, OddsSnapshot
from marketedge.divergence.engine import KALSHI_SOURCE

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClvObservation:
    """One call's price at entry versus the market's closing price."""

    event_id: object
    team: str
    side: str  # 'yes' | 'no' — which side was bought
    entry_prob: float  # what Kalshi charged when the call was made
    closing_prob: float  # Kalshi's last price strictly before kickoff
    entry_at: datetime
    closing_at: datetime

    @property
    def clv(self) -> float:
        """Probability points the close moved in the call's favour.

        For a Yes buy, the price rising means the market came toward us. For a No
        buy the exposure is inverted, so the sign flips — a No bought at
        ``1 - yes_bid`` gains when the Yes price FALLS.
        """
        move = self.closing_prob - self.entry_prob
        return move if self.side == "yes" else -move

    @property
    def beat_close(self) -> bool:
        return self.clv > 0


def closing_price(
    session: Session, event_id, team: str, *, kickoff: datetime
) -> tuple[float, datetime] | None:
    """Kalshi's last price for ``team`` STRICTLY before kickoff.

    Strictly before, because a snapshot taken after kick-off is no longer a
    closing line — it is in-play, and may already reflect the result. Requires a
    minimum lead so a price captured seconds after the market opened is not
    mistaken for a settled close.
    """
    cutoff = kickoff
    row = session.execute(
        select(OddsSnapshot.implied_probability, OddsSnapshot.snapshot_time)
        .where(
            OddsSnapshot.event_id == event_id,
            OddsSnapshot.team == team,
            OddsSnapshot.source == KALSHI_SOURCE,
            OddsSnapshot.snapshot_time < cutoff,
        )
        .order_by(OddsSnapshot.snapshot_time.desc(), OddsSnapshot.id.desc())
        .limit(1)
    ).first()
    if row is None:
        return None
    return float(row.implied_probability), row.snapshot_time


def observe(
    session: Session,
    event: Event,
    *,
    team: str,
    side: str,
    entry_prob: float,
    entry_at: datetime,
) -> ClvObservation | None:
    """Build a CLV observation for one call, or None if there is no usable close.

    None is returned — never a zero — when the game has not kicked off, when no
    pre-kickoff price exists, or when the call was made too close to kickoff for
    "closing" to mean anything. A fabricated 0.0 would read as "no edge" rather
    than "not measurable".
    """
    close = closing_price(session, event.id, team, kickoff=event.scheduled_start)
    if close is None:
        return None
    closing_prob, closing_at = close

    lead = closing_at - entry_at
    if lead < timedelta(minutes=settings.clv_min_lead_minutes):
        logger.debug(
            "CLV skipped for %s/%s: only %s between entry and close",
            event.id, team, lead,
        )
        return None

    return ClvObservation(
        event_id=event.id,
        team=team,
        side=side,
        entry_prob=entry_prob,
        closing_prob=closing_prob,
        entry_at=entry_at,
        closing_at=closing_at,
    )


@dataclass(frozen=True)
class ClvSummary:
    """Aggregate CLV across calls. Reported with its own sample count."""

    n: int
    mean_clv: float | None
    beat_close: int

    @property
    def beat_rate(self) -> float | None:
        return None if self.n == 0 else self.beat_close / self.n


def summarise(observations: list[ClvObservation]) -> ClvSummary:
    """Mean CLV and how often the close was beaten.

    Both are reported because they fail differently: a single large move can carry
    a positive mean while most calls lost value, and a high beat-rate on tiny
    moves can be economically meaningless.
    """
    if not observations:
        return ClvSummary(n=0, mean_clv=None, beat_close=0)
    total = sum(o.clv for o in observations)
    return ClvSummary(
        n=len(observations),
        mean_clv=total / len(observations),
        beat_close=sum(1 for o in observations if o.beat_close),
    )
