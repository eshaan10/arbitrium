import { cents, plural } from "./format";
import type { Divergence } from "./types";

/**
 * Plain-English copy, built from the event's own numbers.
 *
 * Every sentence quotes a real value and no jargon appears in Simple mode.
 * Returned as segments rather than a string so the renderer can emphasise the
 * outcome phrase without any HTML in here.
 */
export type Segment = string | { em: string };

export function whySimple(d: Divergence, minBooks: number): Segment[] {
  const r = d.recommendation;

  if (r) {
    const books = d.n_books ?? 0;
    const gap = (r.edge * 100).toFixed(1);
    return [
      `Kalshi is selling `,
      { em: r.side === "yes" ? `${r.team} to win` : `${r.team} to lose` },
      ` for ${cents(r.price)}. ${books} ${plural(books, "sportsbook", "sportsbooks")} price the ` +
        `same outcome nearer ${cents(r.fair_value)} — about ${gap}¢ of value per contract, if ` +
        `the books are right. This is a directional bet: it pays $1 if it happens, and nothing ` +
        `if it doesn't.`,
    ];
  }

  if (d.status === "scored") {
    return [
      `No edge right now — Kalshi's prices already line up with what the ${d.n_books ?? 0} ` +
        `sportsbooks think, on both sides. Nothing worth acting on.`,
    ];
  }

  if (d.status === "insufficient_consensus") {
    const n = d.n_books ?? 0;
    return [
      `Only ${n} ${plural(n, "sportsbook has", "sportsbooks have")} posted a price, which isn't ` +
        `enough to judge whether Kalshi is off. Waiting for more books — ${minBooks} is the floor.`,
    ];
  }

  if (d.status === "incomparable_outcomes") {
    return [
      `The two sources disagree about which teams are playing, so this can't be compared. ` +
        `That's a data problem on our side, not a market signal.`,
    ];
  }

  const only = d.sources?.[0] === "kalshi" ? "Kalshi" : "the sportsbooks";
  return [`Only ${only} has priced this game, so there's nothing to compare it against yet.`];
}

/**
 * The long-form version, for the detail view. Returns null for scored events —
 * there is nothing to excuse when the numbers are there.
 */
export function unscoreableReason(d: Divergence, minBooks: number): string | null {
  if (d.status === "single_source_no_divergence") {
    const only = d.sources?.[0];
    if (only === "kalshi") {
      return (
        "Only Kalshi has priced this game. No sportsbook has posted a line yet, so there is no " +
        "second opinion to compare against — common for games still weeks out, and for NFL " +
        "preseason, which the regular-season odds feed does not cover."
      );
    }
    if (only === "consensus") {
      return "Only sportsbooks have priced this game; Kalshi has not listed a market for it.";
    }
    return "Only one source priced this game, so there is nothing to compare against.";
  }

  if (d.status === "insufficient_consensus") {
    return (
      `The "consensus" here is a median over just ${d.n_books ?? 0} bookmaker(s), below the ` +
      `floor of ${minBooks}. A median over one or two books is not a consensus, so the observed ` +
      `prices are shown but no divergence is scored.`
    );
  }

  if (d.status === "incomparable_outcomes") {
    return (
      "The two sources' outcomes do not line up — a team resolved differently on each side. " +
      "A data bug, flagged rather than scored across mismatched outcomes."
    );
  }

  return null;
}

/**
 * The card-sized version of {@link unscoreableReason}.
 *
 * Every branch here mirrors one in the long form, so a reader gets the same
 * answer in the list that they would get on the detail page — just shorter.
 * The single-source case names WHICH source, because "one source only" without
 * saying which one is the flat non-answer this replaces.
 */
export function shortUnscoreableReason(d: Divergence, minBooks: number): string | null {
  if (d.status === "scored") return null;

  if (d.status === "single_source_no_divergence") {
    const only = d.sources?.[0];
    if (only === "kalshi") {
      return "Kalshi has priced this; no sportsbook has posted a line yet, so there is nothing to compare against.";
    }
    if (only === "consensus") {
      return "The sportsbooks have priced this; Kalshi has not listed a market for it.";
    }
    return "Only one source priced this game, so there is nothing to compare against.";
  }

  if (d.status === "insufficient_consensus") {
    const n = d.n_books ?? 0;
    return `Only ${n} ${plural(n, "bookmaker", "bookmakers")} — below the floor of ${minBooks}, so no divergence is scored.`;
  }

  return "The two sources disagree about which teams are playing. A data problem on our side, not a market signal.";
}

/** Short supporting facts under the recommendation. */
export function contextLine(d: Divergence): string {
  const bits: string[] = [];
  if (d.n_books) {
    bits.push(`${d.n_books} ${plural(d.n_books, "sportsbook agrees", "sportsbooks agree")}`);
  }
  // Depth arrives as a float (it is derived from resting size), but contracts
  // are whole things — "572.76 contracts available" is not a quantity anyone
  // can buy.
  const max = d.recommendation?.max_contracts;
  if (max != null) {
    bits.push(`up to ${Math.floor(max).toLocaleString()} contracts available`);
  }
  return bits.join(" · ");
}

/** One-line label for a status badge. */
export const STATUS_LABEL: Record<Divergence["status"], string> = {
  scored: "Scored",
  single_source_no_divergence: "One source only",
  insufficient_consensus: "Thin consensus",
  incomparable_outcomes: "Data mismatch",
};

/**
 * Series page, not a per-event deep link: the per-event URL format could not be
 * verified against Kalshi, and a dead link on the one button meant to drive
 * action is worse than one extra click.
 */
export function kalshiUrl(series: string | null): string | null {
  return series ? `https://kalshi.com/markets/${series.toLowerCase()}` : null;
}
