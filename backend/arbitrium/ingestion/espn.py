"""ESPN scoreboard — the backfill source for outcomes The Odds API missed.

WHY THIS EXISTS. The Odds API scores endpoint caps ``daysFrom`` at 3, so an
outcome not collected within ~72h of the final whistle is gone from that source
forever. That is not theoretical: a seven-day outage cost a real NFL preseason
result, which the Odds API could no longer supply and ESPN still had.

ROLE: FALLBACK, NOT PRIMARY. The Odds API stays the primary resolver because it
shares the exact ``odds_api_event_id`` we already store (verified 100/100), which
is an unambiguous join. ESPN is an undocumented endpoint with no SLA and no
shared identifier — matching has to go through the team+date matcher, which
carries real doubleheader ambiguity. Keeping ESPN second means a change in its
shape costs nothing for three days and shows up in ``ingest_runs`` first.

What it buys: unlimited history (verified back through 2022), zero cost, no API
key, and NFL team names that resolve 20/20 against the existing registry. With
it, ``unresolvable`` stops being permanent — an outcome we failed to collect can
be recovered later, so the status honestly means "we did not get it", not "it
never happened".

DATE HANDLING is the fiddly part. ESPN's ``dates`` parameter is a US calendar
date while our ``scheduled_start`` is UTC, and the two disagree for any evening
kickoff: the Aug 6 game was returned only under ``dates=20260806`` even though
its own ``date`` field read ``2026-08-07T00:00Z``. Every lookup therefore sweeps
a +/-1 day window, and dates are de-duplicated across events so one query serves
every game that day. Calls are free, so breadth costs nothing.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx

from arbitrium.ingestion.outcomes import ScoreExtract, coerce_score, decide_winner
from arbitrium.reference.teams import resolve_by_name

logger = logging.getLogger(__name__)

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"

# our sport -> ESPN's path segment. Extend alongside SERIES_CONFIG/ODDS_SPORTS.
# NOTE: 'nba' is listed for completeness but the team registry currently holds
# NFL only, so NBA payloads would be skipped on unresolved names — see
# reference/teams.py before enabling it.
ESPN_SPORTS: dict[str, str] = {
    "nfl": "football/nfl",
    "nba": "basketball/nba",
}

# ESPN's league label per sport, for the team registry lookup.
ESPN_LEAGUE: dict[str, str] = {"nfl": "NFL", "nba": "NBA"}


class EspnClient:
    """Thin wrapper over ESPN's public scoreboard. No key, no quota."""

    def __init__(self, base_url: str | None = None, timeout: float = 20.0) -> None:
        self.base_url = (base_url or ESPN_BASE).rstrip("/")
        self._client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "EspnClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def get_scoreboard(self, sport: str, date: str) -> list[dict]:
        """Games for one US calendar date (``YYYYMMDD``). Returns [] on any error.

        Deliberately swallows failures: this is a best-effort backfill behind a
        working primary, and an ESPN outage must never take down a resolution
        pass that The Odds API could still serve.
        """
        path = ESPN_SPORTS.get(sport)
        if path is None:
            logger.warning("No ESPN mapping for sport %r; skipping backfill", sport)
            return []
        try:
            resp = self._client.get(f"{self.base_url}/{path}/scoreboard", params={"dates": date})
            resp.raise_for_status()
            return resp.json().get("events", []) or []
        except Exception as exc:  # noqa: BLE001 - fallback must not break the pass
            logger.warning("ESPN scoreboard %s/%s failed: %s", sport, date, exc)
            return []


def sweep_dates(start: datetime) -> list[str]:
    """The ``YYYYMMDD`` values that could contain a game kicking off at ``start``.

    A +/-1 day sweep, because ESPN buckets by US calendar date while we store UTC.
    """
    return [(start + timedelta(days=d)).strftime("%Y%m%d") for d in (-1, 0, 1)]


def extract_espn_event(payload: dict, sport: str) -> ScoreExtract | None:
    """Build a result from one ESPN scoreboard event. None => skip, always logged.

    Reuses ``coerce_score`` and ``decide_winner`` from the resolution module, so
    both sources share one definition of "who won" and one string-score parser —
    ESPN reports scores as strings too.
    """
    comps = payload.get("competitions") or []
    if not comps:
        return None
    comp = comps[0]

    status = ((comp.get("status") or {}).get("type") or {})
    if not status.get("completed"):
        return None  # scheduled or in progress

    sides: dict[str, tuple[str, int | None]] = {}
    for c in comp.get("competitors") or []:
        side = c.get("homeAway")
        name = ((c.get("team") or {}).get("displayName")) or ""
        if side in ("home", "away"):
            sides[side] = (name, coerce_score(c.get("score")))
    if set(sides) != {"home", "away"}:
        logger.warning("ESPN event %s: missing home/away competitors; skipping", payload.get("id"))
        return None

    (home_raw, home_score), (away_raw, away_score) = sides["home"], sides["away"]
    if home_score is None or away_score is None:
        logger.warning("ESPN event %s: unparseable score(s); skipping", payload.get("id"))
        return None

    league = ESPN_LEAGUE.get(sport, sport.upper())
    home = resolve_by_name(league, home_raw)
    away = resolve_by_name(league, away_raw)
    if home is None or away is None:
        logger.warning(
            "ESPN event %s: unresolved team(s) home=%r away=%r; skipping "
            "(registry gap — extend reference/teams.py)",
            payload.get("id"), home_raw, away_raw,
        )
        return None

    if home_score == 0 and away_score == 0:
        # Same guard as the Odds API path: for the sports supported today a
        # completed 0-0 is far likelier a bad flag than a real result.
        logger.warning("ESPN event %s: completed 0-0, implausible for %s; skipping",
                       payload.get("id"), league)
        return None

    commence = _parse_espn_date(payload.get("date"))
    return ScoreExtract(
        # No shared identifier with The Odds API — resolution falls through to the
        # team+date matcher, which is why the empty-id guard in _find_event_id
        # matters.
        odds_api_event_id="",
        home_team=home.name,
        away_team=away.name,
        home_score=home_score,
        away_score=away_score,
        winner_team=decide_winner(home.name, away.name, home_score, away_score),
        commence_time=commence,
        sport=sport,
    )


def _parse_espn_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def fetch_results(
    targets: list[tuple[str, datetime]], *, client: EspnClient | None = None
) -> list[ScoreExtract]:
    """Fetch completed results covering ``(sport, kickoff)`` pairs.

    Dates are de-duplicated per sport so one call serves every game that day.
    """
    wanted: dict[str, set[str]] = {}
    for sport, start in targets:
        if start is None:
            continue
        wanted.setdefault(sport, set()).update(sweep_dates(start))

    own = client is None
    client = client or EspnClient()
    out: list[ScoreExtract] = []
    try:
        for sport, dates in wanted.items():
            for date in sorted(dates):
                for payload in client.get_scoreboard(sport, date):
                    extract = extract_espn_event(payload, sport)
                    if extract is not None:
                        out.append(extract)
    finally:
        if own:
            client.close()
    return out
