import { describe, expect, it } from "vitest";
import { kalshiUrl, noEdgeCopy } from "./copy";
import type { Divergence } from "./types";

describe("kalshiUrl", () => {
  it("links to the specific game, not the series", () => {
    // The series page redirects to whatever game Kalshi features, so every
    // card used to open the same unrelated matchup.
    expect(kalshiUrl("KXNFLGAME", "KXNFLGAME-26OCT18LACKC")).toBe(
      "https://kalshi.com/markets/kxnflgame/kxnflgame-26oct18lackc",
    );
  });

  it("falls back to the series page without an event ticker", () => {
    expect(kalshiUrl("KXNFLGAME", null)).toBe("https://kalshi.com/markets/kxnflgame");
    expect(kalshiUrl("KXNFLGAME")).toBe("https://kalshi.com/markets/kxnflgame");
  });

  it("refuses an event ticker from a different series", () => {
    expect(kalshiUrl("KXNFLGAME", "KXNBAGAME-26OCT20BOSDET")).toBe(
      "https://kalshi.com/markets/kxnflgame",
    );
  });

  it("has no link without a series", () => {
    expect(kalshiUrl(null, "KXNFLGAME-26OCT18LACKC")).toBeNull();
  });
});

describe("noEdgeCopy", () => {
  const game = (sport: string, status: Divergence["status"], i = 0) =>
    ({ event_id: `${sport}-${status}-${i}`, sport, status }) as Divergence;
  const many = (n: number, sport: string, status: Divergence["status"]) =>
    Array.from({ length: n }, (_, i) => game(sport, status, i));

  // The local feed this was reported against: 37 NBA games, all Kalshi-only.
  const NBA = many(37, "nba", "single_source_no_divergence");
  const NFL = [...many(26, "nfl", "scored"), ...many(2, "nfl", "single_source_no_divergence")];

  it("says plainly that a Kalshi-only sport was never compared", () => {
    const c = noEdgeCopy(NBA);
    expect(c.context).toBe("kalshi-only");
    expect(c.body).toBe(
      "NBA games are tracked from Kalshi only for now. Sportsbook odds aren't enabled for NBA " +
        "yet, so nothing can be compared or recommended.",
    );
    expect(c.edgeSlot).toContain("NBA games have Kalshi prices only");
    expect(c.arbSlot).toContain("second venue");
    // The spread wording would claim a comparison that never happened.
    for (const text of [c.title, c.body, c.edgeSlot, c.arbSlot]) {
      expect(text).not.toMatch(/surviv|real answer/);
    }
  });

  it("keeps the spread wording when games were scored and none cleared it", () => {
    const c = noEdgeCopy(NFL);
    expect(c.context).toBe("scored");
    expect(c.title).toBe("Nothing worth acting on");
    expect(c.body).toMatch(/^No edge currently survives crossing the Kalshi spread/);
    expect(c.edgeSlot).toMatch(/^No edge survives the spread right now/);
    expect(c.arbSlot).toBe("No arbitrage open. These are rare and usually short-lived.");
  });

  it("treats a mixed feed as scored when any game was compared", () => {
    // The All tab: NFL is scored, NBA is not — the spread wording is true of it.
    expect(noEdgeCopy([...NFL, ...NBA]).context).toBe("scored");
  });

  it("does not name a sport when Kalshi-only games span several", () => {
    const c = noEdgeCopy([...NBA, game("nhl", "single_source_no_divergence")]);
    expect(c.context).toBe("kalshi-only");
    expect(c.body).toMatch(/^These games are tracked from Kalshi only/);
  });

  it("does not claim a spread reading when second prices were too thin to score", () => {
    const c = noEdgeCopy([...NBA, game("nba", "insufficient_consensus")]);
    expect(c.context).toBe("unscored");
    expect(c.body).not.toMatch(/surviv/);
  });

  it("has its own wording for an empty feed", () => {
    expect(noEdgeCopy([]).context).toBe("empty");
    expect(noEdgeCopy([]).body).not.toMatch(/surviv/);
  });
});
