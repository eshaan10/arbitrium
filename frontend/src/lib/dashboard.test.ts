import { describe, expect, it } from "vitest";
import { GROUP_ORDER, groupEvents, groupFor } from "./grouping";
import { matchesTeamQuery, matchupVisuals } from "./teams";
import { TEAM_VISUALS } from "./teams.generated";
import type { Divergence } from "./types";

const NOW = new Date("2026-08-10T12:00:00Z").getTime();

function event(id: string, startIso: string): Divergence {
  return {
    event_id: id,
    sport: "nfl",
    league: "NFL",
    home_team: "Seattle Seahawks",
    away_team: "Dallas Cowboys",
    scheduled_start: startIso,
    status: "scored",
    reason: null,
    sources: ["kalshi", "consensus"],
    n_books: 6,
    home_away_source: "odds_api",
    kalshi_event_ticker: null,
    odds_api_event_id: null,
    max_abs_divergence: 0.02,
    best_net_edge: 0.01,
    tradeable: true,
    recommendation: null,
    kalshi_series: "KXNFLGAME",
    best_expected_value: null,
    is_arbitrage: false,
    arbitrage: null,
    best_trade: null,
    outcomes: [],
  };
}

describe("date grouping", () => {
  it("puts a kickoff that has passed in 'started'", () => {
    expect(groupFor("2026-08-10T11:00:00Z", NOW)).toBe("started");
  });

  it("puts a later-today kickoff in 'today'", () => {
    // Same calendar day in the runner's timezone, an hour after `now`.
    const later = new Date(NOW + 60 * 60 * 1000);
    const end = new Date(NOW);
    end.setHours(23, 59, 59, 999);
    if (later.getTime() <= end.getTime()) {
      expect(groupFor(later.toISOString(), NOW)).toBe("today");
    }
  });

  it("puts a kickoff inside seven days in 'week', and beyond it in 'later'", () => {
    expect(groupFor("2026-08-14T17:00:00Z", NOW)).toBe("week");
    expect(groupFor("2026-09-20T17:00:00Z", NOW)).toBe("later");
  });

  it("never drops an event: every input lands in exactly one group", () => {
    const events = [
      event("a", "2026-08-09T17:00:00Z"),
      event("b", "2026-08-13T17:00:00Z"),
      event("c", "2026-10-01T17:00:00Z"),
      event("d", "2026-12-25T17:00:00Z"),
    ];
    const groups = groupEvents(events, NOW);
    const total = groups.reduce((n, g) => n + g.events.length, 0);
    expect(total).toBe(events.length);
  });

  it("emits groups in fixed order and omits empty ones", () => {
    const groups = groupEvents([event("a", "2026-10-01T17:00:00Z")], NOW);
    expect(groups.map((g) => g.key)).toEqual(["later"]);

    const many = groupEvents(
      [event("a", "2026-08-09T17:00:00Z"), event("b", "2026-10-01T17:00:00Z")],
      NOW,
    );
    const order = many.map((g) => g.key);
    expect(order).toEqual([...order].sort((x, y) => GROUP_ORDER.indexOf(x) - GROUP_ORDER.indexOf(y)));
  });

  it("treats an unparseable kickoff as 'later' rather than throwing", () => {
    expect(groupFor("not-a-date", NOW)).toBe("later");
  });
});

describe("matchup accents", () => {
  it("breaks the shared-colour collision so two bars are never identical", () => {
    // Dallas, New England and Seattle all ship #002a5c upstream.
    const { homeAccent, awayAccent } = matchupVisuals("Seattle Seahawks", "Dallas Cowboys");
    expect(homeAccent).toBe(TEAM_VISUALS["Seattle Seahawks"].accent);
    expect(awayAccent).not.toBe(homeAccent);
    expect(awayAccent).toBe(TEAM_VISUALS["Dallas Cowboys"].alt);
  });

  it("leaves distinct teams on their primary accents", () => {
    const { homeAccent, awayAccent } = matchupVisuals("Buffalo Bills", "Miami Dolphins");
    expect(homeAccent).toBe(TEAM_VISUALS["Buffalo Bills"].accent);
    expect(awayAccent).toBe(TEAM_VISUALS["Miami Dolphins"].accent);
  });

  it("falls back to a neutral for an unknown team instead of throwing", () => {
    const { homeAccent, away } = matchupVisuals("Some Expansion Team", null);
    expect(homeAccent).toBe("var(--neutral)");
    expect(away).toBeNull();
  });
});

describe("team search", () => {
  it("matches on full name, short name, and abbreviation", () => {
    expect(matchesTeamQuery("cowboys", "Seattle Seahawks", "Dallas Cowboys")).toBe(true);
    expect(matchesTeamQuery("dal", "Seattle Seahawks", "Dallas Cowboys")).toBe(true);
    expect(matchesTeamQuery("seahawks", "Seattle Seahawks", "Dallas Cowboys")).toBe(true);
  });

  it("is case- and whitespace-insensitive", () => {
    expect(matchesTeamQuery("  BILLS ", "Buffalo Bills", "Miami Dolphins")).toBe(true);
  });

  it("returns everything for an empty query, and nothing for a miss", () => {
    expect(matchesTeamQuery("", "Buffalo Bills", "Miami Dolphins")).toBe(true);
    expect(matchesTeamQuery("packers", "Buffalo Bills", "Miami Dolphins")).toBe(false);
  });
});
