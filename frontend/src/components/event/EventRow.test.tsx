import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { EventRow } from "./EventRow";
import type { Divergence, Live } from "@/lib/types";

function live(status: Live["status"]): Live {
  return {
    status,
    period: 3,
    clock: "4:12",
    detail: "Q3 4:12",
    home_score: 17,
    away_score: 10,
    home_record: null,
    away_record: null,
    venue: null,
    broadcast: null,
    possession_side: null,
    down_distance: null,
    last_play: null,
    linescore: null,
    updated_at: "2026-10-11T20:00:00Z",
  };
}

const ROW = {
  event_id: "e1",
  sport: "nfl",
  league: "NFL",
  home_team: "Atlanta Falcons",
  away_team: "Baltimore Ravens",
  // An hour ago: in play, and well inside the six hours a row may read LIVE.
  scheduled_start: new Date(Date.now() - 60 * 60 * 1000).toISOString(),
  status: "scored",
  live: null,
  pick_result: null,
  n_books: 6,
  kalshi_series: null,
  kalshi_event_ticker: null,
  is_arbitrage: false,
  arbitrage: null,
  recommendation: {
    team: "Atlanta Falcons",
    side: "yes",
    price: 0.54,
    fair_value: 0.61,
    edge: 0.07,
    wins_if: "",
    max_contracts: 100,
    max_stake: null,
  },
} as unknown as Divergence;

function collapsed(d: Divergence): string {
  return renderToStaticMarkup(
    <EventRow
      d={d}
      minBooks={3}
      isFavoriteGame={false}
      onToggleFavoriteGame={() => {}}
      onOpen={() => {}}
      open={false}
      onToggle={() => {}}
    />,
  );
}

describe("collapsed row, live game", () => {
  it("tags the greyed books price and edge once instead of prefixing each", () => {
    const html = collapsed({ ...ROW, live: live("in_progress") });
    expect(html).not.toMatch(/>Pregame/);
    expect(html.match(/>pregame</g)).toHaveLength(1);
    expect(html).toContain("Books 61¢");
    expect(html).toContain(">+7¢<");
  });

  it("shows no pregame tag before kickoff", () => {
    const html = collapsed({ ...ROW, scheduled_start: "2099-01-01T00:00:00Z" });
    expect(html).not.toMatch(/pregame/i);
    expect(html).toContain("Books 61¢");
  });
});

describe("collapsed row, stale in-progress row", () => {
  it("reads Started, not LIVE, seven hours after kickoff", () => {
    const html = collapsed({
      ...ROW,
      scheduled_start: new Date(Date.now() - 7 * 60 * 60 * 1000).toISOString(),
      live: live("in_progress"),
    });
    expect(html).toContain("Started");
    expect(html).not.toContain("LIVE");
  });

  it("still reads LIVE five hours after kickoff", () => {
    const html = collapsed({
      ...ROW,
      scheduled_start: new Date(Date.now() - 5 * 60 * 60 * 1000).toISOString(),
      live: live("in_progress"),
    });
    expect(html).toContain("LIVE");
  });
});
