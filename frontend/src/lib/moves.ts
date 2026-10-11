import { MOVERS_LIMIT } from "./api";
import { sportLabel } from "./sports";
import type { ActivityChange, ActivityMover, ActivityResponse } from "./types";

export interface NetMove {
  /** Net change over the window, in probability (0.024 = 2.4¢). */
  delta: number;
  team: string;
  /** How many recorded changes went into it. */
  changes: number;
}

/**
 * Net price movement per event over the activity window.
 *
 * Derived from the /activity payload the page already fetches for the ticker,
 * so a card showing movement costs no extra request. This replaced a
 * hover-triggered sparkline that fetched full history PER CARD and rendered a
 * bare line with no axis, no timeframe and no label — a chart nobody could read
 * at a cost nobody could see.
 *
 * Net, not cumulative: a price that goes 40 -> 45 -> 40 has moved twice and
 * arrived nowhere, and reporting "5¢" for it would overstate what happened. The
 * change count carries the churn instead.
 *
 * Only events actually present in the window get an entry. A card with no
 * recorded movement shows nothing rather than a zero, because "flat" and "not
 * observed" are different facts.
 */
export function netMovesByEvent(activity: ActivityResponse | undefined): Map<string, NetMove> {
  const out = new Map<string, NetMove>();
  if (!activity) return out;

  // changes arrive newest-first; group per event+team so two outcomes of the
  // same game are never summed into one number.
  const perSeries = new Map<string, ActivityChange[]>();
  for (const c of activity.changes) {
    if (c.source !== "kalshi" || !c.team) continue;
    const key = `${c.event_id}|${c.team}`;
    const list = perSeries.get(key);
    if (list) list.push(c);
    else perSeries.set(key, [c]);
  }

  for (const [key, rows] of perSeries) {
    const eventId = key.slice(0, key.indexOf("|"));
    const newest = rows[0];
    const oldest = rows[rows.length - 1];
    const delta = newest.to - oldest.from;

    const existing = out.get(eventId);
    // One chip per card: keep the side that moved furthest.
    if (!existing || Math.abs(delta) > Math.abs(existing.delta)) {
      out.set(eventId, { delta, team: newest.team!, changes: rows.length });
    }
  }

  return out;
}

/**
 * Kalshi ticks below a cent, so whole-cent rounding prints "0¢" for a real
 * move. Sub-cent keeps one decimal.
 */
export function formatCentsDelta(delta: number): string {
  const cts = Math.abs(delta * 100);
  return cts < 1 ? cts.toFixed(1) : String(Math.round(cts));
}

/**
 * The "Most movement" rail card for the selected sport.
 *
 * /activity ranks movers across every sport with no sport filter, so the
 * client filters. Movers arrive capped at MOVERS_LIMIT, which leaves one case
 * the client cannot settle: if a full list holds none of this sport, the sport
 * may still have moved, just less than every game listed. The card then says
 * exactly that rather than claiming nothing moved.
 */
export function moverForSport(
  activity: ActivityResponse | undefined,
  sport: string | null,
): { mover: ActivityMover | null; empty: string } {
  if (!activity) return { mover: null, empty: "Loading recent movement…" };

  const hours = activity.window_hours;
  const movers = sport
    ? activity.movers.filter((m) => m.sport?.toLowerCase() === sport.toLowerCase())
    : activity.movers;
  if (movers.length > 0) return { mover: movers[0], empty: "" };

  if (!sport) {
    return { mover: null, empty: `No price moved more than once in the last ${hours} hours.` };
  }
  const label = sportLabel(sport);
  const mayBeCut = activity.movers.length >= MOVERS_LIMIT;
  return {
    mover: null,
    empty: mayBeCut
      ? `No ${label} game is among the ${MOVERS_LIMIT} biggest price moves in the last ${hours} hours.`
      : `No ${label} price movement recorded in the last ${hours} hours.`,
  };
}
