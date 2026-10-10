import { describe, expect, it } from "vitest";
import {
  availableContracts,
  centsToField,
  formatCents,
  parseBet,
  priceToCents,
  quoteStake,
  sliderSpec,
  stopIndexFor,
} from "./stake";

/**
 * Reference outputs for a $100 bet. Each row is a live recommendation from
 * /divergences on 2026-10-08, cross-checked against the previous float
 * simulator, which produced the same contract counts for all of them.
 */
describe("quoteStake — reference outputs for a $100 bet", () => {
  it.each([
    // price, max_contracts from the API, contracts, cost, win, capped
    [0.26, 815_050.94, 384, 9_984, 28_416, false], // Dolphins, Buy Yes
    [0.24, 1_334_461.9, 416, 9_984, 31_616, false], // Eagles, Buy Yes
    [0.21, 10_492_490.88, 476, 9_996, 37_604, false], // Buccaneers, Buy Yes
    [0.39, 135.07, 135, 5_265, 8_235, true], // Seahawks, Buy No — capped
  ])("price %s, %s available", (price, max, contracts, cost, win, capped) => {
    const q = quoteStake(10_000, priceToCents(price), availableContracts(max));
    expect(q).toEqual({ contracts, costCents: cost, winCents: win, capped });
  });

  it("loses exactly what it costs", () => {
    // There is no separate loss figure to drift: the loss IS the cost.
    const q = quoteStake(10_000, 39, 135);
    expect(q.costCents).toBe(5_265);
  });

  it("does not cap when depth is unknown", () => {
    expect(quoteStake(10_000, 26, null)).toMatchObject({ contracts: 384, capped: false });
  });

  it("stays exact where floating point would not", () => {
    // 100 / 0.29 = 344.8275862068966 in floats; 10000 // 29 = 344 exactly.
    expect(quoteStake(10_000, 29, null)).toEqual({
      contracts: 344,
      costCents: 9_976,
      winCents: 24_424,
      capped: false,
    });
  });

  it("buys nothing for a non-positive bet or a price outside (0, 100)", () => {
    for (const [bet, price] of [
      [0, 39],
      [-500, 39],
      [10_000, 0],
      [10_000, 100],
    ]) {
      expect(quoteStake(bet, price, null).contracts).toBe(0);
    }
  });
});

describe("availableContracts", () => {
  it("floors, because a fraction of a contract cannot be bought", () => {
    expect(availableContracts(135.07)).toBe(135);
    expect(availableContracts(1.73)).toBe(1);
  });
  it("is null when depth is unknown", () => {
    expect(availableContracts(null)).toBeNull();
    expect(availableContracts(undefined)).toBeNull();
  });
});

describe("parseBet", () => {
  it.each([
    ["100", 10_000],
    ["$100", 10_000],
    ["$1,250.50", 125_050],
    [" 40 ", 4_000],
    ["52.65", 5_265],
    [".5", 50],
  ])("reads %j as %i cents", (raw, cents) => {
    expect(parseBet(raw, 39)).toEqual({ ok: true, cents });
  });

  it.each(["", "   ", "$", "0", "0.00", "-5", "abc", "1e3", "12.3.4", "--1"])(
    "rejects %j as invalid",
    (raw) => {
      expect(parseBet(raw, 39)).toEqual({ ok: false, error: "invalid" });
    },
  );

  it("rejects a bet below one contract, separately from an invalid one", () => {
    expect(parseBet("0.38", 39)).toEqual({ ok: false, error: "below-one-contract" });
    expect(parseBet("0.39", 39)).toEqual({ ok: true, cents: 39 });
  });
});

describe("sliderSpec", () => {
  it("is $5 to $500 in $5 steps when depth is unknown", () => {
    const s = sliderSpec(26, null);
    expect(s.show && [s.stops[0], s.stops[1], s.stops.at(-1), s.stops.length]).toEqual([
      500, 1_000, 50_000, 100,
    ]);
  });

  it("caps at $500 even when the book is far deeper", () => {
    const s = sliderSpec(21, 10_492_490);
    expect(s.show && s.stops.at(-1)).toBe(50_000);
  });

  it("uses $1 steps under a $100 max, and makes the exact max reachable", () => {
    // 135 contracts at 39¢ = $52.65. Without the appended stop, a $1-step
    // range would top out at $52 and buy two contracts fewer.
    const s = sliderSpec(39, 135);
    expect(s.show).toBe(true);
    if (!s.show) return;
    expect(s.stops[0]).toBe(500);
    expect(s.stops[1]).toBe(600);
    expect(s.stops.slice(-2)).toEqual([5_200, 5_265]);
  });

  it("uses $5 steps when the max is over $100", () => {
    const s = sliderSpec(16, 286); // $45.76 — $1 steps
    expect(s.show && s.stops[1] - s.stops[0]).toBe(100);
    const t = sliderSpec(38, 268); // $101.84 — $5 steps
    expect(t.show && t.stops[1] - t.stops[0]).toBe(500);
    expect(t.show && t.stops.at(-1)).toBe(10_184);
  });

  it("is hidden when the game cannot fill $5, and says how much it can", () => {
    expect(sliderSpec(52, 7)).toEqual({ show: false, availableCents: 364 });
    expect(sliderSpec(44, 1)).toEqual({ show: false, availableCents: 44 });
  });

  it("is hidden with nothing available when depth floors to zero", () => {
    // The API reports fractional depth like 0.02 contracts; nothing can fill.
    expect(availableContracts(0.02)).toBe(0);
    expect(sliderSpec(45, 0)).toEqual({ show: false, availableCents: 0 });
    expect(quoteStake(10_000, 45, 0)).toMatchObject({ contracts: 0, capped: true });
  });

  it("shows exactly at a $5 max", () => {
    expect(sliderSpec(50, 10)).toEqual({ show: true, stops: [500] });
  });
});

describe("stopIndexFor", () => {
  const stops = [500, 600, 700, 5_265];
  it("picks the largest stop at or below the bet", () => {
    expect(stopIndexFor(stops, 650)).toBe(1);
    expect(stopIndexFor(stops, 700)).toBe(2);
  });
  it("pins to the end above the max, and to the start below the min", () => {
    expect(stopIndexFor(stops, 10_000)).toBe(3);
    expect(stopIndexFor(stops, 100)).toBe(0);
  });
});

describe("formatting", () => {
  it("shows whole dollars without decimals in the field, cents otherwise", () => {
    expect(centsToField(10_000)).toBe("100");
    expect(centsToField(5_265)).toBe("52.65");
  });
  it("formats money with separators", () => {
    expect(formatCents(28_416)).toBe("$284.16");
    expect(formatCents(125_050)).toBe("$1,250.50");
  });
});
