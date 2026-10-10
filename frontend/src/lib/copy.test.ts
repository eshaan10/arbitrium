import { describe, expect, it } from "vitest";
import { kalshiUrl } from "./copy";

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
