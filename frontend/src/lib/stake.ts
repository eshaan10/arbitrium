/**
 * Stake maths for a DIRECTIONAL Kalshi bet, in integer cents.
 *
 * The one place this app turns "I'd bet $X" into contracts and outcomes. Both
 * the card's bet input and the detail page's simulator call it, so the two can
 * never quote different numbers for the same bet.
 *
 * Integer cents, not floats. A contract costs a whole number of cents, and
 * `100 / 0.29` in floating point is 344.82758620689657 — close enough to be
 * right almost always, which is the worst kind of wrong for money. Every value
 * here is an integer number of cents (or contracts) until it is formatted.
 *
 * Contracts are whole things: you cannot buy 572.76 of them, so this quotes
 * what would actually fill, and caps at the contracts actually resting at the
 * price. Everything is BEFORE FEES — the caller says so on screen.
 */

export const DEFAULT_BET_CENTS = 10_000;
export const SLIDER_MIN_CENTS = 500;
export const SLIDER_CAP_CENTS = 50_000;

/** A Kalshi price as a probability (0.39) to whole cents (39). */
export function priceToCents(price: number): number {
  return Math.round(price * 100);
}

/** Contracts resting at the price, floored, or null when depth is unknown. */
export function availableContracts(maxContracts: number | null | undefined): number | null {
  return maxContracts == null || !Number.isFinite(maxContracts)
    ? null
    : Math.max(0, Math.floor(maxContracts));
}

export interface StakeQuote {
  contracts: number;
  /** What the bet costs: contracts × price. Also what is lost if it loses. */
  costCents: number;
  /** Net gain if it wins: each contract pays 100¢, minus what was paid. */
  winCents: number;
  /** The bet asked for more contracts than are resting at this price. */
  capped: boolean;
}

/**
 * contracts = floor(bet / price), capped at the contracts available.
 * cost = contracts × price; win = contracts × 100 − cost; loss = cost.
 */
export function quoteStake(
  betCents: number,
  priceCents: number,
  available: number | null,
): StakeQuote {
  if (!(betCents > 0) || !(priceCents > 0) || priceCents >= 100) {
    return { contracts: 0, costCents: 0, winCents: 0, capped: false };
  }
  const wanted = Math.floor(betCents / priceCents);
  const capped = available != null && wanted > available;
  const contracts = capped ? available : wanted;
  const costCents = contracts * priceCents;
  return { contracts, costCents, winCents: contracts * 100 - costCents, capped };
}

export type BetInput =
  | { ok: true; cents: number }
  | { ok: false; error: "invalid" | "below-one-contract" };

/**
 * Read what someone typed into the bet field.
 *
 * Accepts "$1,250.50", "1250.5", " 40 ". Rejects anything that is not a plain
 * positive decimal — including "1e3", which Number() would happily accept —
 * and anything that would not buy a single contract.
 */
export function parseBet(raw: string, priceCents: number): BetInput {
  const cleaned = raw.replace(/[$,\s]/g, "");
  if (!/^(\d+\.?\d*|\.\d+)$/.test(cleaned)) return { ok: false, error: "invalid" };
  const cents = Math.round(Number(cleaned) * 100);
  if (!(cents > 0)) return { ok: false, error: "invalid" };
  if (priceCents > 0 && cents < priceCents) return { ok: false, error: "below-one-contract" };
  return { ok: true, cents };
}

/** The most this game can actually fill at this price, or null if unknown. */
export function maxFillCents(priceCents: number, available: number | null): number | null {
  return available == null ? null : available * priceCents;
}

export type SliderSpec =
  | { show: false; availableCents: number }
  | { show: true; stops: number[] };

/**
 * The slider's positions, in cents.
 *
 * Min $5. Max is the most the game can fill, capped at $500 ($500 when depth
 * is unknown). Step $5 above a $100 max, $1 otherwise. When the max is not a
 * multiple of the step it is appended as the final stop: a range input snaps
 * to min + n·step, so a plain max of $52.65 could never actually be reached —
 * dragging to the end would quietly buy two contracts fewer than the note says.
 *
 * Hidden when the game cannot fill even $5; the caller says how much it can.
 */
export function sliderSpec(priceCents: number, available: number | null): SliderSpec {
  const fill = maxFillCents(priceCents, available);
  if (fill != null && fill < SLIDER_MIN_CENTS) return { show: false, availableCents: fill };

  const max = fill == null ? SLIDER_CAP_CENTS : Math.min(fill, SLIDER_CAP_CENTS);
  const step = max > 10_000 ? 500 : 100;
  const stops: number[] = [];
  for (let v = SLIDER_MIN_CENTS; v <= max; v += step) stops.push(v);
  if (stops[stops.length - 1] !== max) stops.push(max);
  return { show: true, stops };
}

/**
 * The stop to show for a bet: the largest stop at or below it, or the first.
 * A bet above the max pins the slider at its end.
 */
export function stopIndexFor(stops: number[], betCents: number): number {
  let index = 0;
  for (let i = 0; i < stops.length; i++) {
    if (stops[i] <= betCents) index = i;
  }
  return index;
}

/** "52.65" or "100" — what the field shows for a value set by the slider. */
export function centsToField(cents: number): string {
  return cents % 100 === 0 ? String(cents / 100) : (cents / 100).toFixed(2);
}

/** "$1,250.50". */
export function formatCents(cents: number): string {
  return `$${(cents / 100).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}
