"""Cross-source event matching (Kalshi <-> The Odds API).

Pure, DB-free logic so every edge case is unit-testable in isolation. A game is
matched on ``(sport, unordered team pair)`` and disambiguated by start-time
proximity — NEVER by exact date equality, because the two sources legitimately
disagree on the day:
  * Kalshi's start is the ORIGINALLY scheduled date (from its event ticker);
  * The Odds API's ``commence_time`` is the current kickoff and shifts on
    postponement;
  * night games cross UTC midnight, skewing the calendar date by ~a day.

The same matcher backs both ingestion directions, so one game is never split into
two ``events`` rows (dual-key merge).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from marketedge.config import settings

# If the two nearest candidates' start times are within this of each other, the
# match is AMBIGUOUS (e.g. a doubleheader) and we skip rather than guess.
EVENT_MATCH_TIE_TOLERANCE = timedelta(hours=12)


@dataclass(frozen=True)
class EventKey:
    """The identity fields a game is matched on."""

    sport: str
    home_team: str  # canonical
    away_team: str  # canonical
    start: datetime  # tz-aware

    @property
    def team_pair(self) -> frozenset[str]:
        return frozenset({self.home_team, self.away_team})


@dataclass(frozen=True)
class MatchCandidate:
    """An existing event to match against (``identifier`` is opaque, e.g. an id)."""

    identifier: object
    key: EventKey


class MatchStatus(str, Enum):
    MATCHED = "matched"
    UNMATCHED = "unmatched"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class MatchResult:
    status: MatchStatus
    candidate: MatchCandidate | None = None
    reason: str = ""


def match_event(
    target: EventKey,
    candidates: Sequence[MatchCandidate],
    *,
    window_days: int | None = None,
    tie_tolerance: timedelta = EVENT_MATCH_TIE_TOLERANCE,
) -> MatchResult:
    """Match ``target`` against ``candidates``.

    Steps: filter to the same sport + exact unordered team pair; keep those whose
    start is within ±``window_days``; pick the nearest. If the two nearest are
    within ``tie_tolerance`` of each other the result is AMBIGUOUS (skip). No
    team-pair candidate, or none inside the window, is UNMATCHED — both leave the
    event provisional and are worth logging.
    """
    window = timedelta(days=window_days if window_days is not None else settings.event_match_window_days)

    same_pair = [
        c for c in candidates
        if c.key.sport == target.sport and c.key.team_pair == target.team_pair
    ]
    if not same_pair:
        return MatchResult(MatchStatus.UNMATCHED, reason="no candidate with the same team pair")

    within = sorted(
        ((abs(c.key.start - target.start), c) for c in same_pair),
        key=lambda pair: pair[0],
    )
    within = [(delta, c) for delta, c in within if delta <= window]
    if not within:
        return MatchResult(
            MatchStatus.UNMATCHED,
            reason=f"team pair found but nearest start is outside ±{window.days}d window",
        )

    best_delta, best = within[0]
    if len(within) >= 2 and (within[1][0] - best_delta) <= tie_tolerance:
        return MatchResult(
            MatchStatus.AMBIGUOUS,
            reason="multiple candidates within tie tolerance (possible doubleheader)",
        )

    return MatchResult(MatchStatus.MATCHED, candidate=best, reason=f"nearest start Δ={best_delta}")
