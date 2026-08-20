import { describe, expect, it } from "vitest";
import { FOLD_THRESHOLD, shouldFold, splitFoldable } from "./fold";
import type { Divergence } from "./types";

/**
 * The fold hides most of the feed by default, so its exclusions are the part
 * worth pinning: every one of them is a case where folding would make the app
 * look broken. A regression here would not throw — it would quietly swallow
 * search results, which is the failure mode this product least wants.
 */

function event(id: string, status: Divergence["status"]): Divergence {
  return {
    event_id: id,
    sport: "nfl",
    league: "NFL",
    home_team: "Kansas City Chiefs",
    away_team: "Denver Broncos",
    scheduled_start: "2026-09-13T17:00:00Z",
    status,
    reason: null,
    sources: ["kalshi"],
    n_books: 1,
    home_away_source: "odds_api",
    kalshi_event_ticker: null,
    odds_api_event_id: null,
    max_abs_divergence: null,
    best_net_edge: null,
    tradeable: false,
    recommendation: null,
    kalshi_series: null,
    best_expected_value: null,
    is_arbitrage: false,
    arbitrage: null,
    best_trade: null,
    outcomes: [],
  };
}

const unscoreable = (n: number) =>
  Array.from({ length: n }, (_, i) => event(`u${i}`, "insufficient_consensus"));
const scored = (n: number) => Array.from({ length: n }, (_, i) => event(`s${i}`, "scored"));

describe("shouldFold", () => {
  it("folds in the default and All views, where the repetition is the problem", () => {
    expect(shouldFold("recommended", "")).toBe(true);
    expect(shouldFold("all", "")).toBe(true);
    expect(shouldFold("arbitrage", "")).toBe(true);
  });

  it("never folds the view that IS the unscoreable list", () => {
    expect(shouldFold("unscoreable", "")).toBe(false);
  });

  it("never folds while a search is active", () => {
    // A search that silently drops matches into a collapsed section reads as a
    // broken search, not a tidy one.
    expect(shouldFold("all", "chiefs")).toBe(false);
    expect(shouldFold("recommended", "chiefs")).toBe(false);
  });

  it("treats a whitespace-only search as no search", () => {
    expect(shouldFold("all", "   ")).toBe(true);
  });

  it("never folds the hand-picked personal views", () => {
    expect(shouldFold("my-teams", "")).toBe(false);
    expect(shouldFold("my-games", "")).toBe(false);
  });
});

describe("splitFoldable", () => {
  it("folds only unscoreable events, never a scored one", () => {
    const [shown, folded] = splitFoldable([...scored(2), ...unscoreable(5)], true);
    expect(shown.every((d) => d.status === "scored")).toBe(true);
    expect(folded.every((d) => d.status !== "scored")).toBe(true);
    expect(shown).toHaveLength(2);
    expect(folded).toHaveLength(5);
  });

  it("keeps a scored event with no recommendation visible", () => {
    // "We compared these and found nothing" is a real reading and stays a card.
    // "We could not compare these" is what folds. Collapsing the first would
    // hide the answer the reader came for.
    const [shown, folded] = splitFoldable([...scored(1), ...unscoreable(4)], true);
    expect(shown.map((d) => d.event_id)).toEqual(["s0"]);
    expect(folded).toHaveLength(4);
  });

  it("leaves a group alone when too few would fold to be worth a control", () => {
    const events = [...scored(1), ...unscoreable(FOLD_THRESHOLD - 1)];
    const [shown, folded] = splitFoldable(events, true);
    expect(folded).toHaveLength(0);
    expect(shown).toHaveLength(events.length);
  });

  it("returns everything when folding is disabled", () => {
    const events = [...scored(1), ...unscoreable(9)];
    const [shown, folded] = splitFoldable(events, false);
    expect(shown).toEqual(events);
    expect(folded).toHaveLength(0);
  });

  it("never loses an event: shown + folded is always the whole group", () => {
    for (const enabled of [true, false]) {
      for (const n of [0, 1, 3, 12]) {
        const events = [...scored(2), ...unscoreable(n)];
        const [shown, folded] = splitFoldable(events, enabled);
        expect(shown.length + folded.length).toBe(events.length);
        expect(new Set([...shown, ...folded].map((d) => d.event_id)).size).toBe(events.length);
      }
    }
  });
});
