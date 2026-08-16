import { describe, expect, it } from "vitest";
import { changesSinceLastVisit, recSignature } from "./changes";
import type { RecentEvent } from "./storage";
import type { Divergence } from "./types";

function event(overrides: Partial<Divergence> = {}): Divergence {
  return {
    event_id: "e1",
    sport: "nfl",
    league: "NFL",
    home_team: "Seattle Seahawks",
    away_team: "Dallas Cowboys",
    scheduled_start: "2026-09-01T17:00:00Z",
    status: "scored",
    reason: null,
    sources: ["kalshi", "consensus"],
    n_books: 6,
    home_away_source: "odds_api",
    kalshi_event_ticker: null,
    odds_api_event_id: null,
    max_abs_divergence: 0.03,
    best_net_edge: 0.02,
    tradeable: true,
    recommendation: null,
    kalshi_series: "KXNFLGAME",
    best_expected_value: null,
    is_arbitrage: false,
    arbitrage: null,
    best_trade: null,
    outcomes: [],
    ...overrides,
  };
}

function rec(side: "yes" | "no", team: string, price = 0.4) {
  return {
    team,
    side,
    price,
    fair_value: price + 0.03,
    edge: 0.03,
    wins_if: `${team} wins`,
    max_contracts: 500,
    max_stake: 200,
  };
}

function seen(overrides: Partial<RecentEvent> = {}): RecentEvent {
  return {
    id: "e1",
    home: "Seattle Seahawks",
    away: "Dallas Cowboys",
    sport: "nfl",
    at: "2026-08-01T00:00:00Z",
    rec: null,
    arb: false,
    ...overrides,
  };
}

describe("recommendation signature", () => {
  it("captures side and team", () => {
    expect(recSignature(event({ recommendation: rec("yes", "Dallas Cowboys") }))).toBe(
      "yes|Dallas Cowboys",
    );
  });

  it("is null when there is no recommendation", () => {
    expect(recSignature(event())).toBeNull();
  });

  it("ignores price, so a one-cent tick is not a change", () => {
    const before = recSignature(event({ recommendation: rec("yes", "Dallas Cowboys", 0.4) }));
    const after = recSignature(event({ recommendation: rec("yes", "Dallas Cowboys", 0.47) }));
    expect(before).toBe(after);
  });
});

describe("changes since last visit", () => {
  it("reports a flipped side", () => {
    const out = changesSinceLastVisit(
      [seen({ rec: "yes|Dallas Cowboys" })],
      [event({ recommendation: rec("no", "Seattle Seahawks") })],
    );
    expect(out).toHaveLength(1);
    expect(out[0].kind).toBe("flipped");
  });

  it("reports a recommendation that appeared", () => {
    const out = changesSinceLastVisit(
      [seen({ rec: null })],
      [event({ recommendation: rec("yes", "Dallas Cowboys") })],
    );
    expect(out[0].kind).toBe("appeared");
  });

  it("reports a recommendation that went away", () => {
    const out = changesSinceLastVisit([seen({ rec: "yes|Dallas Cowboys" })], [event()]);
    expect(out[0].kind).toBe("disappeared");
  });

  it("reports a new arbitrage on an otherwise unchanged event", () => {
    const out = changesSinceLastVisit(
      [seen({ rec: "yes|Dallas Cowboys", arb: false })],
      [event({ recommendation: rec("yes", "Dallas Cowboys"), is_arbitrage: true })],
    );
    expect(out[0].kind).toBe("arbitrage");
  });

  it("says nothing when nothing changed", () => {
    const out = changesSinceLastVisit(
      [seen({ rec: "yes|Dallas Cowboys" })],
      [event({ recommendation: rec("yes", "Dallas Cowboys") })],
    );
    expect(out).toEqual([]);
  });

  it("does not report an arbitrage that was already open when last seen", () => {
    const out = changesSinceLastVisit(
      [seen({ rec: "yes|Dallas Cowboys", arb: true })],
      [event({ recommendation: rec("yes", "Dallas Cowboys"), is_arbitrage: true })],
    );
    expect(out).toEqual([]);
  });

  it("stays silent about an event that has left the feed", () => {
    // Nothing honest can be said about an event we can no longer see.
    expect(changesSinceLastVisit([seen({ id: "gone" })], [event()])).toEqual([]);
  });

  it("skips entries written before the snapshot existed", () => {
    // A v1 entry has no baseline; treating its missing `rec` as "no
    // recommendation" would invent an "appeared" that was never observed.
    const legacy = { id: "e1", home: "S", away: "D", sport: "nfl", at: "x" } as RecentEvent;
    const out = changesSinceLastVisit(
      [legacy],
      [event({ recommendation: rec("yes", "Dallas Cowboys") })],
    );
    expect(out).toEqual([]);
  });

  it("reports only one change per event, most specific first", () => {
    const out = changesSinceLastVisit(
      [seen({ rec: "yes|Dallas Cowboys", arb: false })],
      [event({ recommendation: rec("no", "Seattle Seahawks"), is_arbitrage: true })],
    );
    expect(out).toHaveLength(1);
    expect(out[0].kind).toBe("flipped");
  });
});
