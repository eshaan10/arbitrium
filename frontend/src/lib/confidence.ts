import type { Divergence } from "./types";

/**
 * Confidence in a recommendation, from BOOK COUNT and AVAILABLE DEPTH.
 *
 * Two independent ways a recommendation fails — too few books to trust the
 * consensus, or almost no size behind the price — and neither substitutes for
 * the other. Deliberately does NOT fold in edge size: a huge edge quoted by one
 * book is not high confidence, and letting a big number raise the bars would
 * turn the weakest signals into the loudest ones.
 */
export interface Confidence {
  bars: 0 | 1 | 2 | 3 | 4;
  label: "" | "Weak" | "Moderate" | "Good" | "Strong";
}

const LABELS = ["", "Weak", "Moderate", "Good", "Strong"] as const;

export function confidence(d: Divergence, minBooks: number): Confidence {
  const rec = d.recommendation;
  if (!rec) return { bars: 0, label: "" };

  const books = d.n_books ?? 0;
  const size = rec.max_contracts ?? 0;

  const bookScore = books >= 9 ? 2 : books >= 5 ? 1.5 : books >= minBooks ? 1 : 0;
  const depthScore =
    size >= 500 ? 2 : size >= 100 ? 1.5 : size >= 25 ? 1 : size > 0 ? 0.5 : 0;

  // FLOOR, not round. Rounding let 6-of-9 books plus deep size (3.5) present as
  // "Strong", which is the top of the scale claimed by a consensus that is a
  // third short — overstating confidence is the one direction this product is
  // not allowed to err in. Flooring reserves "Strong" for 9+ books and real depth.
  const bars = Math.max(1, Math.min(4, Math.floor(bookScore + depthScore))) as 1 | 2 | 3 | 4;
  return { bars, label: LABELS[bars] };
}

/** How much this row's numbers should be trusted, 0–1. Drives the fade. */
export function confidenceOf(d: Divergence): number {
  if (d.status === "single_source_no_divergence") return 0.12;
  if (d.status === "incomparable_outcomes") return 0.22;
  if (d.status === "insufficient_consensus") return 0.34;
  return 0.55 + 0.45 * Math.min((d.n_books ?? 0) / 9, 1);
}

/**
 * Opacity for a row, floored at --fade-floor so the dimmest state still clears
 * 4.5:1 against the page. Fading is reinforcement for the explicit confidence
 * label, never the only carrier — an unreadable low-confidence row would be a
 * hidden one, which is the thing this product refuses to do.
 *
 * Arbitrage is never dimmed: the fade expresses trust in a probability
 * estimate, and an arbitrage does not rest on one.
 */
export const FADE_FLOOR = 0.62;

export function opacityOf(d: Divergence): number {
  if (d.is_arbitrage) return 1;
  return Number((FADE_FLOOR + (1 - FADE_FLOOR) * confidenceOf(d)).toFixed(3));
}

/**
 * Value a REFERENCE stake could actually realise, used only for ordering.
 * Capped by resting size: an edge you can take $1 of is not a better
 * opportunity than a smaller edge you can take $100 of. Never displayed — the
 * confidence bars and the stake simulator carry that to the user.
 */
const REFERENCE_STAKE = 100;

export function reachableValue(d: Divergence): number {
  const r = d.recommendation;
  if (!r || !r.price) return -1;
  const affordable = REFERENCE_STAKE / r.price;
  const contracts = r.max_contracts == null ? affordable : Math.min(affordable, r.max_contracts);
  return r.edge * contracts;
}

/** Actionable first by reachable value, then everything else by kickoff. */
export function sortForDisplay(list: Divergence[]): Divergence[] {
  return [...list].sort((a, b) => {
    const av = reachableValue(a);
    const bv = reachableValue(b);
    if (av >= 0 || bv >= 0) return bv - av;
    return new Date(a.scheduled_start).getTime() - new Date(b.scheduled_start).getTime();
  });
}
