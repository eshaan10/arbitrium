import type { ActivityChange, ActivityResponse } from "./types";

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
