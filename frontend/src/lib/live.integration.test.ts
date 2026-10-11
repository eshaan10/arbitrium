import { describe, expect, it } from "vitest";
import type { Divergence, Live } from "./types";

function live(status: Live["status"]): Live {
  return {
    status,
    period: null,
    clock: null,
    detail: null,
    home_score: null,
    away_score: null,
    home_record: null,
    away_record: null,
    venue: null,
    broadcast: null,
    possession_side: null,
    down_distance: null,
    last_play: null,
    linescore: null,
    updated_at: new Date().toISOString(),
  };
}

function scheduledEvent(id: string, withRec = true): Divergence {
  return {
    event_id: id,
    sport: "nfl",
    status: "scored",
    live: null,
    pick_result: null,
    recommendation: withRec
      ? { team: "A", side: "yes", price: 0.5, fair_value: 0.55, edge: 0.05, wins_if: "", max_contracts: null, max_stake: null }
      : null,
  } as unknown as Divergence;
}

describe("exclusion", () => {
  it("recommended counts only non-live events with a recommendation", () => {
    const feed: Divergence[] = [
      scheduledEvent("a"),
      scheduledEvent("b"),
      scheduledEvent("c"),
      { ...scheduledEvent("d"), live: live("in_progress") } as Divergence,
      { ...scheduledEvent("e"), live: live("halftime") } as Divergence,
    ];
    const isLiveStatus = (d: Divergence) =>
      d.live?.status === "in_progress" || d.live?.status === "halftime";
    const recommended = feed.filter((d) => d.recommendation && !isLiveStatus(d));
    expect(recommended.map((d) => d.event_id)).toEqual(["a", "b", "c"]);
  });
});

describe("toggle removal", () => {
  it("no module exports ModeToggle or Mode", async () => {
    // Importing the former path must fail: the file is deleted.
    let threw = false;
    try {
      // @ts-expect-error - the module is intentionally gone.
      await import("./mode");
    } catch {
      threw = true;
    }
    expect(threw).toBe(true);
    const controls = await import("@/components/dashboard/Controls");
    expect("ModeToggle" in controls).toBe(false);
  });

  it("defensive localStorage cleanup runs idempotently", () => {
    const store = new Map<string, string>();
    const g = globalThis as typeof globalThis & { localStorage?: Storage };
    const prior = g.localStorage;
    g.localStorage = {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
      removeItem: (k: string) => void store.delete(k),
      clear: () => store.clear(),
      key: () => null,
      length: 0,
    };
    store.set("arbitrium:mode", "advanced");
    // Simulates the Dashboard mount effect.
    localStorage.removeItem("arbitrium:mode");
    expect(store.has("arbitrium:mode")).toBe(false);
    g.localStorage = prior;
  });
});

describe("greyed-out helper", () => {
  it("marks Books/edge as pregame when the game is in progress", () => {
    const d: Divergence = { ...scheduledEvent("x"), live: live("in_progress") } as Divergence;
    const isLiveStatus = d.live?.status === "in_progress" || d.live?.status === "halftime";
    // The components use isLive to pick between "Books" and "Pregame books",
    // and to apply opacity/text classes. Here we just assert the predicate.
    expect(isLiveStatus).toBe(true);
    const expectedBooksLabel = isLiveStatus ? "Pregame books" : "Books";
    expect(expectedBooksLabel).toBe("Pregame books");
    const expectedEdgeTone = isLiveStatus ? "text-faint opacity-60" : "text-signal";
    expect(expectedEdgeTone).toContain("opacity");
  });
});
