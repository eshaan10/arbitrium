import type { Divergence } from "./types";

/**
 * Signal: how much a game's divergence is worth acting on, as the backend
 * already measures it. This module ranks and scales; it computes nothing new.
 *
 * The number is `best_expected_value` from /divergences
 * (backend/arbitrium/divergence/engine.py, Outcome.expected_value_at_depth on
 * the best fill): the edge left after crossing Kalshi's spread, multiplied by
 * the contracts resting at that price. So a big edge with nothing behind it
 * stays small. Units are contract-dollars, but it is shown as a RELATIVE
 * signal, not a probability and not a promised profit: whether a given value
 * means the same thing across sports is not yet calibrated.
 *
 * Deliberately distinct from "Strength" (lib/confidence.ts), which rates how
 * far to TRUST a recommendation from book count and depth and ignores edge
 * size on purpose.
 */

/** Signal for a scored game; null when it cannot be ranked. */
export function signalOf(d: Divergence): number | null {
  if (d.status !== "scored") return null;
  return d.best_expected_value;
}

/** Scored games can be ranked; anything else keeps its kickoff order, unranked. */
export const isRanked = (d: Divergence): boolean => d.status === "scored";

const kickoffMs = (d: Divergence) => new Date(d.scheduled_start).getTime() || 0;

/**
 * Strongest first, kickoff breaking ties. A scored game with no signal (no
 * depth reported) ranks below every number, including zero. Unscored games
 * come last, in kickoff order — they are never ranked against anything.
 */
export function rankBySignal(events: Divergence[]): Divergence[] {
  const ranked = events.filter(isRanked);
  const unranked = events.filter((d) => !isRanked(d));
  const key = (d: Divergence) => signalOf(d) ?? Number.NEGATIVE_INFINITY;
  ranked.sort((a, b) => key(b) - key(a) || kickoffMs(a) - kickoffMs(b));
  unranked.sort((a, b) => kickoffMs(a) - kickoffMs(b));
  return [...ranked, ...unranked];
}

/** How many ranked games per sport the Today section shows before "Show more". */
export const TODAY_PER_SPORT = 10;

/**
 * Keep the strongest `cap` ranked games per sport; the rest are `hidden`.
 * Order is preserved, and unranked games are never hidden: they are not
 * competing on signal, so a cap on signal says nothing about them.
 */
export function capPerSport(
  ranked: Divergence[],
  cap: number = TODAY_PER_SPORT,
): { kept: Divergence[]; hidden: Divergence[] } {
  const seen = new Map<string, number>();
  const kept: Divergence[] = [];
  const hidden: Divergence[] = [];
  for (const d of ranked) {
    if (!isRanked(d)) {
      kept.push(d);
      continue;
    }
    const sport = d.sport ?? "";
    const n = seen.get(sport) ?? 0;
    seen.set(sport, n + 1);
    (n < cap ? kept : hidden).push(d);
  }
  return { kept, hidden };
}

/** The largest positive signal in a list: the top of every meter drawn beside it. */
export function signalScale(events: Divergence[]): number {
  let max = 0;
  for (const d of events) {
    const s = signalOf(d);
    if (s != null && s > max) max = s;
  }
  return max;
}

/**
 * Meter fill, 0..1, relative to `scale`. Logarithmic because the values are
 * heavily skewed (one deep book can be 50x the next), and on a linear meter
 * every row but the top one would read as empty. Display only: ranking uses
 * the raw number.
 */
export function signalFill(value: number | null, scale: number): number {
  if (value == null || value <= 0 || scale <= 0) return 0;
  return Math.min(1, Math.log1p(value) / Math.log1p(scale));
}

/** The number shown beside the meter. */
export function formatSignal(value: number | null): string {
  if (value == null) return "–";
  if (value <= 0) return "0";
  // Positive but below what one decimal can show; "0.0" would read as none.
  if (value < 0.1) return "<0.1";
  if (value >= 100) return Math.round(value).toLocaleString("en-US");
  return value.toFixed(1);
}
