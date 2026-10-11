/**
 * The frontend's team data must describe the same teams as the backend registry.
 *
 * Event rows carry the backend's canonical names, and ESPN results are resolved
 * there by ESPN team.id. If the generated visuals drifted from the registry, a
 * team would lose its logo (name mismatch) or the two sides would disagree
 * about which ESPN team a name means (id mismatch). Both would ship silently.
 *
 * The registry is read as text, not imported: it is Python, and this check must
 * not depend on running the backend.
 */

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { TEAM_ALIASES, TEAM_VISUALS } from "./teams.generated";
import { logoPath, teamInitials, teamVisual } from "./teams";

const REGISTRY = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "../../../backend/arbitrium/reference/teams.py",
);

interface RegistryTeam {
  name: string;
  league: string;
  espnId: string;
}

function readRegistry(): RegistryTeam[] {
  const src = readFileSync(REGISTRY, "utf8");
  // Team("BOS", "Boston Celtics", "<kalshi uuid>", "NBA", "2")
  const re = /Team\("\w+",\s*"([^"]+)",\s*"[^"]*",\s*"(\w+)",\s*"(\d+)"\)/g;
  return [...src.matchAll(re)].map((m) => ({ name: m[1], league: m[2], espnId: m[3] }));
}

const registry = readRegistry();

describe("team visuals match the backend registry", () => {
  it("parses both registered leagues", () => {
    const count = (league: string) => registry.filter((t) => t.league === league).length;
    expect([count("NFL"), count("NBA")]).toEqual([32, 30]);
  });

  it.each(registry.map((t) => [t.name, t] as const))(
    "%s has a visual with the registry's ESPN id and league",
    (name, team) => {
      const visual = TEAM_VISUALS[name];
      expect(visual, `${name} has no generated visual; re-run pnpm gen:teams`).toBeDefined();
      expect(visual.espnId).toBe(team.espnId);
      expect(visual.league).toBe(team.league.toLowerCase());
    },
  );

  it("has no visual the registry does not know", () => {
    const known = new Set(registry.map((t) => t.name));
    expect(Object.keys(TEAM_VISUALS).filter((n) => !known.has(n))).toEqual([]);
  });
});

describe("team lookup", () => {
  it("resolves ESPN's 'LA Clippers' to the canonical Clippers", () => {
    expect(TEAM_ALIASES["LA Clippers"]).toBe("Los Angeles Clippers");
    expect(teamVisual("LA Clippers")).toBe(TEAM_VISUALS["Los Angeles Clippers"]);
  });

  it("keeps logos of colliding abbreviations in separate league folders", () => {
    // ATL is both the Falcons and the Hawks.
    expect(logoPath(teamVisual("Atlanta Hawks")!)).toBe("/logos/nba/atl.png");
    expect(logoPath(teamVisual("Atlanta Falcons")!)).toBe("/logos/nfl/atl.png");
  });

  it("gives NBA rows short names, so they stop truncating", () => {
    expect(teamVisual("San Antonio Spurs")?.short).toBe("Spurs");
    expect(teamVisual("Phoenix Suns")?.short).toBe("Suns");
  });

  it.each([
    ["Los Angeles Lakers", "LL"],
    ["Los Angeles Clippers", "LC"],
    ["Seattle Kraken", "SK"],
    ["Thunder", "TH"],
    ["", "?"],
  ])("initials for %j are %j", (name, initials) => {
    expect(teamInitials(name)).toBe(initials);
  });
});

describe("NBA teams behave like NFL teams in the dashboard", () => {
  it("are found by short name and abbreviation in the team search", async () => {
    const { matchesTeamQuery } = await import("./teams");
    expect(matchesTeamQuery("spurs", "San Antonio Spurs")).toBe(true);
    expect(matchesTeamQuery("lac", "Los Angeles Clippers")).toBe(true);
    expect(matchesTeamQuery("clippers", "LA Clippers")).toBe(true);
  });
});
