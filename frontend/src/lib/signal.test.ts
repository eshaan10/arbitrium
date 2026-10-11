import { describe, expect, it } from "vitest";
import {
  capPerSport,
  formatSignal,
  rankBySignal,
  signalFill,
  signalOf,
  signalScale,
} from "./signal";
import type { Divergence } from "./types";

function ev(
  id: string,
  {
    sport = "nfl",
    status = "scored",
    ev: value = null,
    at = "2026-10-11T17:00:00Z",
  }: { sport?: string; status?: Divergence["status"]; ev?: number | null; at?: string } = {},
): Divergence {
  return {
    event_id: id,
    sport,
    status,
    best_expected_value: value,
    scheduled_start: at,
  } as Divergence;
}

const ids = (list: Divergence[]) => list.map((d) => d.event_id);

describe("signal is the backend's number", () => {
  it("reads best_expected_value for a scored game", () => {
    expect(signalOf(ev("a", { ev: 12.5 }))).toBe(12.5);
  });

  it("never gives an unscoreable game a signal", () => {
    expect(signalOf(ev("a", { status: "insufficient_consensus", ev: 99 }))).toBeNull();
  });
});

describe("ranking", () => {
  it("puts the strongest first", () => {
    const list = [ev("low", { ev: 1 }), ev("high", { ev: 40 }), ev("mid", { ev: 6 })];
    expect(ids(rankBySignal(list))).toEqual(["high", "mid", "low"]);
  });

  it("breaks ties by kickoff", () => {
    const list = [
      ev("late", { ev: 5, at: "2026-10-11T20:00:00Z" }),
      ev("early", { ev: 5, at: "2026-10-11T17:00:00Z" }),
    ];
    expect(ids(rankBySignal(list))).toEqual(["early", "late"]);
  });

  it("ranks an unknown signal below zero, and unscoreable games after everything, unranked", () => {
    const list = [
      ev("cant-late", { status: "single_source_no_divergence", at: "2026-10-11T23:00:00Z" }),
      ev("unknown", { ev: null }),
      ev("cant-early", { status: "insufficient_consensus", ev: 1000, at: "2026-10-11T16:00:00Z" }),
      ev("zero", { ev: 0 }),
      ev("some", { ev: 3 }),
    ];
    expect(ids(rankBySignal(list))).toEqual([
      "some", "zero", "unknown", "cant-early", "cant-late",
    ]);
  });
});

describe("Today cap", () => {
  const nfl = Array.from({ length: 13 }, (_, i) => ev(`nfl-${i}`, { ev: 100 - i }));
  const nba = Array.from({ length: 4 }, (_, i) => ev(`nba-${i}`, { sport: "nba", ev: 50 - i }));

  it("keeps the ten strongest per sport and hides the rest, dropping nothing", () => {
    const ranked = rankBySignal([...nfl, ...nba]);
    const { kept, hidden } = capPerSport(ranked, 10);
    expect(kept.filter((d) => d.sport === "nfl")).toHaveLength(10);
    expect(kept.filter((d) => d.sport === "nba")).toHaveLength(4);
    expect(ids(hidden)).toEqual(["nfl-10", "nfl-11", "nfl-12"]);
    expect(kept.length + hidden.length).toBe(17);
  });

  it("hides the weakest, not the latest", () => {
    const ranked = rankBySignal([...nfl].reverse());
    const { hidden } = capPerSport(ranked, 10);
    expect(hidden.every((d) => (signalOf(d) ?? 0) <= 90)).toBe(true);
  });

  it("never hides an unscoreable game", () => {
    const cant = Array.from({ length: 12 }, (_, i) =>
      ev(`cant-${i}`, { status: "insufficient_consensus" }),
    );
    const { kept, hidden } = capPerSport(rankBySignal([...nfl, ...cant]), 10);
    expect(hidden.every((d) => d.status === "scored")).toBe(true);
    expect(kept.filter((d) => d.status !== "scored")).toHaveLength(12);
  });
});

describe("meter", () => {
  it("scales to the strongest positive signal in the list", () => {
    expect(signalScale([ev("a", { ev: 3 }), ev("b", { ev: 40 }), ev("c", { ev: -2 })])).toBe(40);
    expect(signalScale([ev("a", { ev: -1 })])).toBe(0);
  });

  it("fills the strongest row and leaves non-positive ones empty", () => {
    expect(signalFill(40, 40)).toBe(1);
    expect(signalFill(0, 40)).toBe(0);
    expect(signalFill(-3, 40)).toBe(0);
    expect(signalFill(null, 40)).toBe(0);
    expect(signalFill(5, 0)).toBe(0);
  });

  it("does not leave a mid-sized row looking empty beside a huge one", () => {
    expect(signalFill(10, 500)).toBeGreaterThan(0.35);
  });

  it.each([
    [null, "–"],
    [-4, "0"],
    [0, "0"],
    [0.04, "<0.1"],
    [3.14159, "3.1"],
    [1234.6, "1,235"],
  ])("formats %s as %s", (value, text) => {
    expect(formatSignal(value)).toBe(text);
  });
});

describe("live games are excluded from ranking", () => {
  function withLive(d: Divergence, status: "in_progress" | "halftime" | "final"): Divergence {
    return { ...d, live: { status } as Divergence["live"] };
  }

  it("gives a live game no signal, even when scored", () => {
    const d = withLive(ev("a", { ev: 99 }), "in_progress");
    expect(signalOf(d)).toBeNull();
  });

  it("ranks scheduled games above live ones", () => {
    const scheduled1 = ev("s1", { ev: 1 });
    const scheduled2 = ev("s2", { ev: 2 });
    const scheduled3 = ev("s3", { ev: 3 });
    const live1 = withLive(ev("l1", { ev: 50 }), "in_progress");
    const live2 = withLive(ev("l2", { ev: 60 }), "halftime");
    const ranked = rankBySignal([scheduled1, scheduled2, scheduled3, live1, live2]);
    expect(ids(ranked).slice(0, 3)).toEqual(["s3", "s2", "s1"]);
  });
});
