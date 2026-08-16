"""Provider-neutral outcome primitives.

Shared by every resolution source (The Odds API scores, ESPN scoreboard) so all
of them agree on one definition of "who won" and one parser for the string-typed
scores both providers happen to send. Lives apart from any provider module
because two providers importing each other is a cycle, and because a third source
should be able to reuse these without depending on the first two.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ScoreExtract:
    """One completed game's result, with teams already canonicalised.

    ``odds_api_event_id`` is empty for providers that share no identifier with
    The Odds API (ESPN). Resolution treats an empty id as "no fast path" and
    falls through to the team+date matcher.
    """

    odds_api_event_id: str
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    winner_team: str | None  # None means DRAW, and only ever draw
    commence_time: datetime | None
    sport: str


def coerce_score(value: object) -> int | None:
    """Parse a score, which both providers send as a STRING ("5").

    Mirrors the discipline in ``normalize._coerce_price``: this exact class of
    bug — a numeric field arriving as a string — already cost this project a
    silent ingestion failure once. Returns None for missing or unparseable
    rather than defaulting to 0, because a wrong 0 fabricates a shutout.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def decide_winner(
    home_team: str, away_team: str, home_score: int, away_score: int
) -> str | None:
    """Return the winning TEAM NAME, or None for a tie.

    Deliberately never returns 'home'/'away'. The function has no concept of home
    and away beyond which score belongs to which name, so its output cannot be
    invalidated by a later authoritative home/away correction.
    """
    if home_score == away_score:
        return None
    return home_team if home_score > away_score else away_team
