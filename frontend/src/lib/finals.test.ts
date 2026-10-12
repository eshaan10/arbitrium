import { describe, expect, it } from "vitest";
import { capFinals, FINALS_SHOWN, finalLive, pickHeadline, weSaid, winnerLine } from "./finals";
import { final } from "./finals.fixture";

describe("capFinals", () => {
  const games = Array.from({ length: 23 }, (_, i) => i);

  it("shows the first ten and counts the rest", () => {
    const { shown, more } = capFinals(games, false);
    expect(FINALS_SHOWN).toBe(10);
    expect(shown).toEqual(games.slice(0, 10));
    expect(more).toBe(13);
  });

  it("shows everything once expanded, still reporting how many were hidden", () => {
    const { shown, more } = capFinals(games, true);
    expect(shown).toHaveLength(23);
    expect(more).toBe(13);
  });

  it("has nothing more to show at or under the cap", () => {
    expect(capFinals(games.slice(0, 10), false)).toEqual({ shown: games.slice(0, 10), more: 0 });
  });
});

describe("weSaid", () => {
  it("states the call, the snapshot, and the result from the picked team's side", () => {
    expect(weSaid(final())).toBe(
      "We said: Ravens to lose at 54¢ (books 61¢). Result: Ravens lost 15-23. Pick hit.",
    );
  });

  it("says missed for a missed pick", () => {
    const f = final({
      flagged: { team: "Atlanta Falcons", side: "no", price: 0.4, fair_value: 0.45, flagged_at: "" },
      pick_result: "miss",
    });
    expect(weSaid(f)).toBe(
      "We said: Falcons to lose at 40¢ (books 45¢). Result: Falcons won 23-15. Pick missed.",
    );
  });

  it("drops the verdict on a tie rather than guessing", () => {
    const f = final({ home_score: 20, away_score: 20, winner_team: null, pick_result: null });
    expect(weSaid(f)).toBe(
      "We said: Ravens to lose at 54¢ (books 61¢). Result: Ravens tied 20-20.",
    );
  });

  it("is null without a flagged pick", () => {
    expect(weSaid(final({ flagged: null, pick_result: null }))).toBeNull();
    expect(pickHeadline(final({ flagged: null }))).toBeNull();
  });
});

describe("winnerLine", () => {
  it("names the winner, or calls a tie", () => {
    expect(winnerLine(final())).toBe("Falcons won");
    expect(winnerLine(final({ winner_team: null }))).toBe("Tie");
  });
});

describe("finalLive", () => {
  it("builds a final scoreboard when ESPN never wrote a row", () => {
    const live = finalLive(final());
    expect(live.status).toBe("final");
    expect([live.away_score, live.home_score]).toEqual([15, 23]);
  });

  it("keeps ESPN's linescore but takes the resolved score and status", () => {
    const live = finalLive(
      final({
        live: { ...finalLive(final()), status: "in_progress", home_score: 20, linescore: { home: [7], away: [3] } },
      }),
    );
    expect(live.status).toBe("final");
    expect(live.home_score).toBe(23);
    expect(live.linescore).toEqual({ home: [7], away: [3] });
  });
});
