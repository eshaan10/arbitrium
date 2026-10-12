import type { FinalGame } from "./types";

/** A settled Ravens @ Falcons with a hit "Ravens to lose" call, for tests. */
export function final(overrides: Partial<FinalGame> = {}): FinalGame {
  return {
    event_id: "f1",
    sport: "nfl",
    league: "NFL",
    home_team: "Atlanta Falcons",
    away_team: "Baltimore Ravens",
    scheduled_start: "2026-10-11T17:00:00Z",
    home_score: 23,
    away_score: 15,
    winner_team: "Atlanta Falcons",
    kalshi_event_ticker: null,
    live: null,
    pick_result: "hit",
    flagged: {
      team: "Baltimore Ravens",
      side: "no",
      price: 0.54,
      fair_value: 0.61,
      flagged_at: "2026-10-11T11:00:00Z",
    },
    ...overrides,
  };
}
