/**
 * One-line plain-English definitions for the jargon that appears on cards.
 *
 * Single source for the "?" popovers, so a term cannot be explained one way on
 * a card and another way on /how-it-works. `anchor` is the section id on that
 * page, making each popover a doorway rather than a dead end.
 */
export interface GlossaryEntry {
  term: string;
  short: string;
  anchor: string;
}

export const GLOSSARY = {
  confidence: {
    term: "Confidence",
    short:
      "How much to trust this signal, from two things: how many sportsbooks agree, and how many contracts are actually resting at the price. It deliberately ignores the size of the edge — a big edge quoted by one book is not strong evidence.",
    anchor: "confidence",
  },
  books: {
    term: "Books",
    short:
      "How many sportsbooks have posted a price on this game. Their median is the 'consensus' we compare Kalshi against. Below the floor we refuse to score the event rather than call two books a consensus.",
    anchor: "consensus",
  },
  arbitrage: {
    term: "Arbitrage",
    short:
      "A rare case where prices on two platforms disagree enough that covering every outcome costs less than $1. It pays regardless of who wins — unlike a recommendation, which only pays if the outcome happens.",
    anchor: "arbitrage",
  },
  divergence: {
    term: "Divergence",
    short:
      "How far apart Kalshi and the sportsbooks are on what's likely. It is not money: about half of real divergences are smaller than the spread you'd pay to capture them.",
    anchor: "divergence",
  },
  netEdge: {
    term: "Net edge",
    short:
      "What's left of a divergence after paying Kalshi's buy/sell spread. This is the number that can actually be captured.",
    anchor: "divergence",
  },
  depth: {
    term: "Depth",
    short:
      "How many contracts are resting at the quoted price. An edge you can only take $5 of is not better than a smaller edge you can take $500 of.",
    anchor: "confidence",
  },
} as const satisfies Record<string, GlossaryEntry>;

export type GlossaryKey = keyof typeof GLOSSARY;
