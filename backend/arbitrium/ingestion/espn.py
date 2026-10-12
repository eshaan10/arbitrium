"""ESPN scoreboard — the primary source of outcomes.

WHY THIS EXISTS. The Odds API scores endpoint caps ``daysFrom`` at 3, so an
outcome not collected within ~72h of the final whistle is gone from that source
forever. That is not theoretical: a seven-day outage cost a real NFL preseason
result, which the Odds API could no longer supply and ESPN still had.

ROLE: PRIMARY (it used to be the fallback). Each scores call costs 2 credits,
and with NFL, NBA and NHL in season together, resolving everything through The
Odds API would spend a sizeable share of a 500-credit month on data ESPN gives
away. The cost of the switch is the join: ESPN has no shared identifier, so a
result goes through the team+date matcher, which carries doubleheader
ambiguity in principle (none of NFL/NBA/NHL plays them). The Odds API remains
the fallback for anything ESPN has not resolved well inside the window — see
``resolution.run_resolution``.

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
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from arbitrium.ingestion.outcomes import ScoreExtract, coerce_score, decide_winner
from arbitrium.reference.teams import Team, resolve_by_name, team_by_espn_id

logger = logging.getLogger(__name__)

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"

# our sport -> ESPN's path segment. Extend alongside SERIES_CONFIG/ODDS_SPORTS.
ESPN_SPORTS: dict[str, str] = {
    "nfl": "football/nfl",
    "nba": "basketball/nba",
    "nhl": "hockey/nhl",
}

# ESPN's league label per sport, for the team registry lookup.
ESPN_LEAGUE: dict[str, str] = {"nfl": "NFL", "nba": "NBA", "nhl": "NHL"}

# Leagues resolved by ESPN's numeric ``team.id`` rather than display name. NFL
# names resolve 20/20 against the registry, so NFL keeps the name path; NBA and
# NHL go by id from the start, which no rename or "LA"/"Los Angeles" spelling
# can break.
ESPN_ID_LEAGUES = frozenset({"NBA", "NHL"})


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


def resolve_by_espn_id(league: str, espn_id: str | None) -> Team | None:
    """Registry lookup by ESPN ``team.id``, scoped to the league.

    Ids collide across leagues (ESPN id 1 is both the Falcons and the Hawks),
    so the league is never optional. A league with no registry yet (NHL today)
    resolves nothing, and its results are skipped and logged, never guessed
    from a name.
    """
    return team_by_espn_id(league, espn_id)


def _resolve_espn_team(league: str, team: dict) -> Team | None:
    if league in ESPN_ID_LEAGUES:
        return resolve_by_espn_id(league, team.get("id"))
    return resolve_by_name(league, team.get("displayName") or "")


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

    sides: dict[str, tuple[dict, int | None]] = {}
    for c in comp.get("competitors") or []:
        side = c.get("homeAway")
        if side in ("home", "away"):
            sides[side] = (c.get("team") or {}, coerce_score(c.get("score")))
    if set(sides) != {"home", "away"}:
        logger.warning("ESPN event %s: missing home/away competitors; skipping", payload.get("id"))
        return None

    (home_raw, home_score), (away_raw, away_score) = sides["home"], sides["away"]
    if home_score is None or away_score is None:
        logger.warning("ESPN event %s: unparseable score(s); skipping", payload.get("id"))
        return None

    league = ESPN_LEAGUE.get(sport, sport.upper())
    home = _resolve_espn_team(league, home_raw)
    away = _resolve_espn_team(league, away_raw)
    if home is None or away is None:
        logger.warning(
            "ESPN event %s: unresolved team(s) home=%r (id %s) away=%r (id %s); "
            "skipping (registry gap — extend reference/teams.py)",
            payload.get("id"), home_raw.get("displayName"), home_raw.get("id"),
            away_raw.get("displayName"), away_raw.get("id"),
        )
        return None

    if home_score == 0 and away_score == 0:
        # Same guard as the Odds API path: for the sports supported today (NHL
        # included — it settles ties in a shootout) a completed 0-0 is far
        # likelier a bad flag than a real result.
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


# Preseason exhibitions schedule a partner team against a non-partner (e.g.
# Trail Blazers vs London Lions), and ESPN returns that card on every poll.
# The team registry correctly fails to resolve the exhibition side; without
# this a legitimate "we skipped a real game" warning gets drowned in a tick-
# cadence repeat of the exhibition every 30s. Dedup is per process.
_warned_unresolved: set[str] = set()


LIVE_STATUS_SCHEDULED = "scheduled"
LIVE_STATUS_IN_PROGRESS = "in_progress"
LIVE_STATUS_HALFTIME = "halftime"
LIVE_STATUS_FINAL = "final"
LIVE_STATUS_POSTPONED = "postponed"

LIVE_STATUSES = frozenset({
    LIVE_STATUS_SCHEDULED,
    LIVE_STATUS_IN_PROGRESS,
    LIVE_STATUS_HALFTIME,
    LIVE_STATUS_FINAL,
    LIVE_STATUS_POSTPONED,
})


@dataclass(frozen=True)
class LiveState:
    """Parsed live state for one ESPN scoreboard event.

    All fields except ``status``, ``home_team`` and ``away_team`` are optional:
    scheduled games have no clock, non-NFL has no down/distance, a pre-game
    poll has no last play. The poller writes whatever is present and leaves
    the rest NULL.
    """

    sport: str
    espn_event_id: str
    home_team: str
    away_team: str
    commence_time: datetime | None
    status: str
    period: int | None = None
    clock: str | None = None
    detail: str | None = None
    home_score: int | None = None
    away_score: int | None = None
    home_record: str | None = None
    away_record: str | None = None
    venue: str | None = None
    broadcast: str | None = None
    possession_side: str | None = None
    down_distance: str | None = None
    last_play: str | None = None
    linescore: dict[str, list[int]] | None = None


# ESPN status.type.name values that mean "not actually in play". The scoreboard
# distinguishes STATUS_HALFTIME (own value), STATUS_END_PERIOD, delays, and so
# on; only halftime gets its own ``halftime`` status here. Everything else that
# ESPN groups under ``state == 'in'`` reads as in_progress.
_HALFTIME_NAMES = frozenset({"STATUS_HALFTIME"})
_POSTPONED_NAMES = frozenset({"STATUS_POSTPONED", "STATUS_CANCELED"})


def _map_status(status_type: dict) -> str | None:
    """ESPN status -> our enum. Returns None when ESPN says nothing useful."""
    name = (status_type.get("name") or "").upper()
    state = (status_type.get("state") or "").lower()
    if name in _POSTPONED_NAMES:
        return LIVE_STATUS_POSTPONED
    if state == "pre":
        return LIVE_STATUS_SCHEDULED
    if state == "in":
        return LIVE_STATUS_HALFTIME if name in _HALFTIME_NAMES else LIVE_STATUS_IN_PROGRESS
    if state == "post":
        return LIVE_STATUS_FINAL
    return None


def _period_label(sport: str, period: int | None) -> str:
    """Sport-aware period label used in the detail string.

    NFL periods 1-4 are Q1..Q4; period >= 5 is OT (not labelled "5OT"). NBA
    periods 1-4 are Q1..Q4; period 5 is OT, 6 is 2OT, etc. NHL is P1..P3 and
    then OT / shootout, but ESPN already shortDetail-labels NHL cleanly, so
    the fallback below is only used when shortDetail is missing.
    """
    if period is None:
        return ""
    if sport == "nhl":
        return f"P{period}" if period <= 3 else "OT"
    if sport == "nba":
        if period <= 4:
            return f"Q{period}"
        return "OT" if period == 5 else f"{period - 4}OT"
    # nfl + anything else
    if period <= 4:
        return f"Q{period}"
    return "OT"


def _build_detail(sport: str, status: str, status_type: dict, period: int | None,
                  clock: str | None) -> str | None:
    """Short string suitable for the collapsed-row subline (e.g. "Q3 4:12")."""
    short = status_type.get("shortDetail") or status_type.get("detail")
    if status == LIVE_STATUS_HALFTIME:
        return "Halftime"
    if status == LIVE_STATUS_FINAL:
        return short or "Final"
    if status == LIVE_STATUS_POSTPONED:
        return short or "Postponed"
    if status == LIVE_STATUS_IN_PROGRESS:
        label = _period_label(sport, period)
        if label and clock:
            return f"{label} {clock}"
        return short
    if status == LIVE_STATUS_SCHEDULED:
        return short
    return short


def _linescore(competitor: dict) -> list[int]:
    """Per-period scores for one competitor. Non-numeric periods become 0."""
    out: list[int] = []
    for row in competitor.get("linescores") or []:
        val = row.get("value") if isinstance(row, dict) else row
        try:
            out.append(int(val))
        except (TypeError, ValueError):
            out.append(0)
    return out


def _possession_side(situation: dict, competitors: list[dict]) -> str | None:
    """Map ESPN ``situation.possession`` (a competitor id) to 'home'/'away'."""
    pos_id = situation.get("possession")
    if not pos_id:
        return None
    for c in competitors:
        if str(c.get("id") or (c.get("team") or {}).get("id")) == str(pos_id):
            side = c.get("homeAway")
            return side if side in ("home", "away") else None
    return None


def _broadcast(comp: dict) -> str | None:
    """Readable broadcast name from the slate, or None if not announced."""
    for b in comp.get("broadcasts") or []:
        names = b.get("names") if isinstance(b, dict) else None
        if names:
            return names[0]
    geo = (comp.get("geoBroadcasts") or [])
    for b in geo:
        media = (b.get("media") or {}) if isinstance(b, dict) else {}
        name = media.get("shortName") or media.get("name")
        if name:
            return name
    return None


def extract_live_state(payload: dict, sport: str) -> LiveState | None:
    """Build a :class:`LiveState` from one ESPN scoreboard event. None => skip."""
    comps = payload.get("competitions") or []
    if not comps:
        return None
    comp = comps[0]

    status_block = comp.get("status") or {}
    status_type = status_block.get("type") or {}
    status = _map_status(status_type)
    if status is None:
        logger.warning(
            "ESPN event %s: unmapped status state=%r name=%r; skipping",
            payload.get("id"), status_type.get("state"), status_type.get("name"),
        )
        return None

    competitors = comp.get("competitors") or []
    sides: dict[str, dict] = {}
    for c in competitors:
        side = c.get("homeAway")
        if side in ("home", "away"):
            sides[side] = c
    if set(sides) != {"home", "away"}:
        logger.warning("ESPN event %s: missing home/away competitors; skipping",
                       payload.get("id"))
        return None

    league = ESPN_LEAGUE.get(sport, sport.upper())
    home = _resolve_espn_team(league, sides["home"].get("team") or {})
    away = _resolve_espn_team(league, sides["away"].get("team") or {})
    if home is None or away is None:
        key = f"{sport}:{payload.get('id') or ''}"
        if key not in _warned_unresolved:
            _warned_unresolved.add(key)
            logger.warning(
                "ESPN event %s: unresolved team(s) home=%r (id %s) away=%r (id %s); "
                "skipping live state (registry gap)",
                payload.get("id"),
                (sides["home"].get("team") or {}).get("displayName"),
                (sides["home"].get("team") or {}).get("id"),
                (sides["away"].get("team") or {}).get("displayName"),
                (sides["away"].get("team") or {}).get("id"),
            )
        return None

    # Scores are present for in_progress and final; absent for scheduled.
    home_score = coerce_score(sides["home"].get("score"))
    away_score = coerce_score(sides["away"].get("score"))
    if status == LIVE_STATUS_SCHEDULED:
        home_score = None
        away_score = None

    period_raw = status_block.get("period")
    try:
        period = int(period_raw) if period_raw is not None else None
    except (TypeError, ValueError):
        period = None
    if status == LIVE_STATUS_SCHEDULED:
        period = None
    clock = status_block.get("displayClock") or None
    if status in (LIVE_STATUS_SCHEDULED, LIVE_STATUS_HALFTIME, LIVE_STATUS_POSTPONED):
        clock = None

    detail = _build_detail(sport, status, status_type, period, clock)

    situation = comp.get("situation") or {}
    possession_side = None
    down_distance = None
    last_play = None
    if sport == "nfl":
        possession_side = _possession_side(situation, competitors)
        down_distance = (
            situation.get("shortDownDistanceText")
            or situation.get("downDistanceText")
            or None
        )
        last_play_block = situation.get("lastPlay") or {}
        if isinstance(last_play_block, dict):
            last_play = last_play_block.get("text") or None

    home_line = _linescore(sides["home"])
    away_line = _linescore(sides["away"])
    linescore: dict[str, list[int]] | None = None
    if home_line or away_line:
        linescore = {"home": home_line, "away": away_line}

    def _record(c: dict) -> str | None:
        for rec in c.get("records") or []:
            if isinstance(rec, dict) and rec.get("summary"):
                return rec["summary"]
        return None

    venue_name: str | None = None
    venue_block = comp.get("venue") or {}
    if isinstance(venue_block, dict):
        venue_name = venue_block.get("fullName") or venue_block.get("displayName") or None

    return LiveState(
        sport=sport,
        espn_event_id=str(payload.get("id") or ""),
        home_team=home.name,
        away_team=away.name,
        commence_time=_parse_espn_date(payload.get("date")),
        status=status,
        period=period,
        clock=clock,
        detail=detail,
        home_score=home_score,
        away_score=away_score,
        home_record=_record(sides["home"]),
        away_record=_record(sides["away"]),
        venue=venue_name,
        broadcast=_broadcast(comp),
        possession_side=possession_side,
        down_distance=down_distance,
        last_play=last_play,
        linescore=linescore,
    )


def fetch_live_states(
    sport: str, *, now: datetime | None = None, client: EspnClient | None = None,
) -> list[LiveState]:
    """Fetch the sport's live scoreboard. Returns one state per ESPN event.

    Sweeps yesterday and today (ESPN buckets by US calendar date while we store
    UTC), de-duplicating by ESPN event id — a late-evening game appears under
    both buckets and we want each event parsed once.
    """
    return _fetch_states(sport, range(-1, 1), now=now, client=client)


def fetch_upcoming_states(
    sport: str, *, days: int, now: datetime | None = None,
    client: EspnClient | None = None,
) -> list[LiveState]:
    """Fetch yesterday through ``days`` ahead: the slate the live sweep never
    reaches, plus yesterday for finals of games that left the fast poll.

    One call per date. ESPN's ``dates=START-END`` range form answers 400
    ("Failed to get events endpoint") for every range tried, and the month form
    is capped at 100 events, so neither covers a week reliably. Calls are free.
    """
    return _fetch_states(sport, range(-1, days + 1), now=now, client=client)


def _fetch_states(
    sport: str, offsets: range, *, now: datetime | None, client: EspnClient | None,
) -> list[LiveState]:
    moment = now or datetime.now(timezone.utc)
    own = client is None
    client = client or EspnClient()
    seen_ids: set[str] = set()
    out: list[LiveState] = []
    try:
        for date in sorted({(moment + timedelta(days=d)).strftime("%Y%m%d")
                            for d in offsets}):
            for payload in client.get_scoreboard(sport, date):
                state = extract_live_state(payload, sport)
                if state is None:
                    continue
                if state.espn_event_id and state.espn_event_id in seen_ids:
                    continue
                seen_ids.add(state.espn_event_id)
                out.append(state)
    finally:
        if own:
            client.close()
    return out


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
