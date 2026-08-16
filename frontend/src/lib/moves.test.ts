import { describe, expect, it } from "vitest";
import { formatCentsDelta, netMovesByEvent } from "./moves";
import type { ActivityChange, ActivityResponse } from "./types";

function change(over: Partial<ActivityChange> = {}): ActivityChange {
  return {
    event_id: "e1",
    sport: "nfl",
    home_team: "Seattle Seahawks",
    away_team: "Dallas Cowboys",
    source: "kalshi",
    team: "Dallas Cowboys",
    from: 0.4,
    to: 0.42,
    delta: 0.02,
    at: "2026-08-11T12:00:00Z",
    ...over,
  };
}

/** Newest first, as the endpoint returns them. */
function activity(changes: ActivityChange[]): ActivityResponse {
  return {
    since: "2026-08-10T12:00:00Z",
    window_hours: 24,
    changes,
    movers: [],
    counts: { changes: changes.length, movers: 0 },
  };
}

describe("net moves by event", () => {
  it("is empty when there is no activity payload yet", () => {
    expect(netMovesByEvent(undefined).size).toBe(0);
  });

  it("measures the window end to end, not the sum of every tick", () => {
    // 40 -> 45 -> 40: moved twice, arrived nowhere.
    const move = netMovesByEvent(
      activity([
        change({ at: "2026-08-11T14:00:00Z", from: 0.45, to: 0.4 }),
        change({ at: "2026-08-11T13:00:00Z", from: 0.4, to: 0.45 }),
      ]),
    ).get("e1");

    expect(move?.delta).toBeCloseTo(0, 10);
    expect(move?.changes).toBe(2);
  });

  it("reports a genuine net move with its direction", () => {
    const move = netMovesByEvent(
      activity([
        change({ at: "2026-08-11T14:00:00Z", from: 0.45, to: 0.48 }),
        change({ at: "2026-08-11T13:00:00Z", from: 0.4, to: 0.45 }),
      ]),
    ).get("e1");

    expect(move?.delta).toBeCloseTo(0.08, 10);
  });

  it("never sums the two sides of one game together", () => {
    // Two outcomes move in opposite directions by construction.
    const moves = netMovesByEvent(
      activity([
        change({ team: "Dallas Cowboys", from: 0.4, to: 0.46 }),
        change({ team: "Seattle Seahawks", from: 0.6, to: 0.54 }),
      ]),
    );

    expect(moves.size).toBe(1);
    // Keeps the furthest-moving side, not the net of both (which would be zero).
    expect(Math.abs(moves.get("e1")!.delta)).toBeCloseTo(0.06, 10);
  });

  it("ignores consensus, which is sampled on a different cadence", () => {
    const moves = netMovesByEvent(
      activity([change({ source: "consensus", from: 0.2, to: 0.8 })]),
    );
    expect(moves.size).toBe(0);
  });

  it("keeps events apart", () => {
    const moves = netMovesByEvent(
      activity([
        change({ event_id: "a", from: 0.4, to: 0.43 }),
        change({ event_id: "b", from: 0.7, to: 0.62 }),
      ]),
    );
    expect(moves.get("a")?.delta).toBeCloseTo(0.03, 10);
    expect(moves.get("b")?.delta).toBeCloseTo(-0.08, 10);
  });
});

describe("cents delta formatting", () => {
  it("keeps a decimal below one cent, so a real move is never printed as zero", () => {
    expect(formatCentsDelta(0.0029)).toBe("0.3");
    expect(formatCentsDelta(-0.004)).toBe("0.4");
  });

  it("rounds to whole cents at or above one", () => {
    expect(formatCentsDelta(0.024)).toBe("2");
    expect(formatCentsDelta(-0.138)).toBe("14");
  });

  it("is always unsigned — the arrow carries direction", () => {
    expect(formatCentsDelta(-0.05)).toBe(formatCentsDelta(0.05));
  });
});
