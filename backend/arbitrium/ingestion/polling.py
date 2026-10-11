"""When to spend an Odds API credit: per-sport config and the game-clock plan.

The free tier is 500 credits a month, and h2h in one region costs 1 credit per
sport per /odds call. The previous pacing was one adaptive interval across every
sport (hourly within a day of kickoff); fine for NFL alone, and three times over
budget once NBA and NHL run nightly alongside it.

So credits are no longer spent on an interval at all. Each game is priced at a
few named moments before it starts — T-24h, T-6h, T-1h and the close at T-10m —
and the close is tagged, because closing-line value is measured against it.

ONE CALL PRICES EVERY GAME IN A SPORT. That is what makes the plan affordable:
:func:`plan_passes` coalesces checkpoints across games, so an NBA night with six
tip-off times does not cost six calls per checkpoint. Each checkpoint is a
window, and passes are placed by interval stabbing — sort the windows by when
they close, fire at the earliest close, take every window that is open at that
moment, repeat. That is the minimum number of calls that hits every window.

Exact start times come from the free /events listing, not from Kalshi: Kalshi
events carry only a date parsed from their ticker, which cannot place a T-10m.

Everything that DECIDES is pure here; :mod:`arbitrium.ingestion.odds_schedule`
gathers the inputs and :mod:`arbitrium.ingestion.governor` rations the budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from arbitrium.config import settings
from arbitrium.db.models import Event, OddsCheckpoint

# ---------------------------------------------------------------------------
# Per-sport config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SeasonWindow:
    """An inclusive (month, day) range that recurs every year; may wrap New Year."""

    start: tuple[int, int]
    end: tuple[int, int]

    def contains(self, day: date) -> bool:
        md = (day.month, day.day)
        if self.start <= self.end:
            return self.start <= md <= self.end
        return md >= self.start or md <= self.end


@dataclass(frozen=True)
class SportPolling:
    """Whether, when in the year, and how often one sport may spend credits."""

    sport: str
    league: str
    # Odds API sport_key -> the part of the year it carries games. Out of
    # window, a key is not even listed (its /events call is free, but skipping
    # it keeps a stale preseason key from ever reaching a paid call).
    seasons: dict[str, SeasonWindow]
    enabled: bool
    passes_per_day: int

    def keys_in_season(self, day: date) -> list[str]:
        return sorted(k for k, w in self.seasons.items() if w.contains(day))


# Preseason keys are SEPARATE in the Odds API: the regular-season key does not
# list exhibition games. Both are listed; a pass only calls the keys that carry
# a game it is due for, so an overlap never bills twice.
SPORT_SEASONS: dict[str, tuple[str, dict[str, SeasonWindow]]] = {
    "nfl": (
        "NFL",
        {
            "americanfootball_nfl": SeasonWindow((9, 1), (2, 20)),
            "americanfootball_nfl_preseason": SeasonWindow((7, 25), (9, 5)),
        },
    ),
    "nba": (
        "NBA",
        {
            "basketball_nba": SeasonWindow((10, 1), (6, 30)),
            # Stops itself after Oct 16, the last date any NBA preseason has run.
            "basketball_nba_preseason": SeasonWindow((9, 25), (10, 16)),
        },
    ),
    "nhl": ("NHL", {"icehockey_nhl": SeasonWindow((10, 1), (6, 30))}),
}


def sport_polling() -> dict[str, SportPolling]:
    """The per-sport config, read from settings at call time (so env and tests apply)."""
    enabled = {s.lower() for s in settings.odds_sports_enabled}
    return {
        sport: SportPolling(
            sport=sport,
            league=league,
            seasons=seasons,
            enabled=sport in enabled,
            passes_per_day=getattr(settings, f"odds_passes_per_day_{sport}"),
        )
        for sport, (league, seasons) in SPORT_SEASONS.items()
    }


def active_sports(day: date) -> list[SportPolling]:
    """Enabled sports with at least one key in season on ``day``."""
    return [p for p in sport_polling().values() if p.enabled and p.keys_in_season(day)]


# ---------------------------------------------------------------------------
# Game-clock checkpoints
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Checkpoint:
    """A named moment before start, with the window a pass may land in.

    ``rank`` orders importance: when the budget is tight the governor drops the
    lowest ranks first, and the close is never dropped for pace alone.
    """

    name: str
    offset: timedelta
    early: timedelta  # the window opens this long before start - offset
    late: timedelta  # ...and closes this long after it
    rank: int

    def window(self, start: datetime) -> tuple[datetime, datetime]:
        target = start - self.offset
        return target - self.early, target + self.late


# Passes fire at a window's CLOSING edge (that is where stabbing places them),
# so ``late`` is kept small: the close lands at T-6m to T-20m, never in play.
CHECKPOINT_T24H = Checkpoint(
    "t24h", timedelta(hours=24), timedelta(hours=4), timedelta(hours=3), rank=1
)
CHECKPOINT_T6H = Checkpoint(
    "t6h", timedelta(hours=6), timedelta(hours=1, minutes=30), timedelta(minutes=45), rank=2
)
CHECKPOINT_T1H = Checkpoint(
    "t1h", timedelta(hours=1), timedelta(minutes=20), timedelta(minutes=10), rank=3
)
# The closing-line snapshot for CLV.
CHECKPOINT_CLOSE = Checkpoint(
    "close", timedelta(minutes=10), timedelta(minutes=10), timedelta(minutes=4), rank=4
)

CHECKPOINTS: tuple[Checkpoint, ...] = (
    CHECKPOINT_T24H, CHECKPOINT_T6H, CHECKPOINT_T1H, CHECKPOINT_CLOSE,
)
CHECKPOINTS_BY_NAME = {c.name: c for c in CHECKPOINTS}

# A window that closed less than this long ago is still served: the loop ticks
# every few seconds and a pass can sit behind a slow Kalshi one. Older than this
# and the moment has passed — a T-1h price taken at T-20m is not a T-1h price.
MISSED_GRACE = timedelta(minutes=5)


@dataclass(frozen=True)
class GameSlot:
    """One Kalshi-backed game the plan is responsible for."""

    event_id: object
    sport: str
    sport_key: str  # the Odds API key whose /odds call prices this game
    start: datetime  # exact, from /events
    liquidity: float | None = None  # resting Kalshi depth, $; None if unknown

    def is_thin(self) -> bool:
        return self.liquidity is None or self.liquidity < settings.odds_thin_liquidity_dollars


@dataclass(frozen=True)
class PlannedPass:
    """One /odds call per key in ``sport_keys``, covering every listed checkpoint."""

    sport: str
    at: datetime
    covers: tuple[tuple[GameSlot, Checkpoint], ...]

    @property
    def sport_keys(self) -> list[str]:
        return sorted({g.sport_key for g, _ in self.covers})

    @property
    def cost(self) -> int:
        return len(self.sport_keys)

    @property
    def has_close(self) -> bool:
        return any(c is CHECKPOINT_CLOSE for _, c in self.covers)

    @property
    def top_checkpoint(self) -> Checkpoint:
        return max((c for _, c in self.covers), key=lambda c: c.rank)

    @property
    def priority(self) -> tuple:
        """Higher sorts first: closest-to-start checkpoint, then Kalshi liquidity."""
        liquid = [g for g, _ in self.covers if not g.is_thin()]
        return (
            self.top_checkpoint.rank,
            len(liquid),
            sum(g.liquidity or 0.0 for g, _ in self.covers),
        )


def plan_passes(
    games: list[GameSlot],
    done: set[tuple[object, str]],
    *,
    now: datetime,
) -> list[PlannedPass]:
    """The minimum set of passes that lands in every outstanding checkpoint window.

    ``done`` holds (event_id, checkpoint name) pairs already captured or
    deliberately skipped; those are never planned again, which is what makes a
    restart unable to re-spend a checkpoint. Sports are planned independently
    because one call prices one sport. Returned in time order.
    """
    by_sport: dict[str, list[tuple[datetime, datetime, GameSlot, Checkpoint]]] = {}
    for game in games:
        for cp in CHECKPOINTS:
            if (game.event_id, cp.name) in done:
                continue
            opens, closes = cp.window(game.start)
            if closes < now - MISSED_GRACE:
                continue  # that moment is gone; a late price is not that checkpoint
            by_sport.setdefault(game.sport, []).append((closes, opens, game, cp))

    passes: list[PlannedPass] = []
    for sport, windows in by_sport.items():
        windows.sort(key=lambda w: (w[0], w[1]))
        while windows:
            at = max(now, windows[0][0])
            hit = [w for w in windows if w[1] <= at <= w[0] + MISSED_GRACE]
            windows = [w for w in windows if w not in hit]
            passes.append(PlannedPass(sport, at, tuple((w[2], w[3]) for w in hit)))
    passes.sort(key=lambda p: (p.at, p.sport))
    return passes


def utc_day_start(moment: datetime) -> datetime:
    return moment.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


# ---------------------------------------------------------------------------
# DB-only reads for /health (never touch the API)
# ---------------------------------------------------------------------------


# How long after a close window shuts before a missing close counts as missed.
CLOSE_MISSED_AFTER = timedelta(minutes=15)


def missed_closes(session: Session, *, now: datetime | None = None) -> int:
    """Kalshi-backed games in the last day whose close was neither taken nor skipped.

    The consensus freshness signal now that passes are hours apart by design: a
    gap means nothing, a game that kicked off without its closing checkpoint
    does. Only games with an exact start (an Odds API id) are judged, and only
    since the schedule first recorded anything, so a fresh deploy is not
    blamed for closes that predate it.
    """
    moment = now or datetime.now(timezone.utc)
    first = session.execute(select(func.min(OddsCheckpoint.captured_at))).scalar()
    if first is None:
        return 0
    latest_start = moment + CHECKPOINT_CLOSE.offset - CHECKPOINT_CLOSE.late - CLOSE_MISSED_AFTER
    taken = exists().where(
        OddsCheckpoint.event_id == Event.id,
        OddsCheckpoint.checkpoint == CHECKPOINT_CLOSE.name,
    )
    enabled = [p.sport for p in sport_polling().values() if p.enabled]
    return session.execute(
        select(func.count()).select_from(Event).where(
            Event.sport.in_(enabled),
            Event.kalshi_event_ticker.is_not(None),
            Event.odds_api_event_id.is_not(None),
            Event.scheduled_start > max(first, moment - timedelta(days=1)),
            Event.scheduled_start <= latest_start,
            ~taken,
        )
    ).scalar() or 0
