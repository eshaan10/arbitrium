import { describe, expect, it } from "vitest";
import { browseAllHref, sportTabs, type SportTab } from "./sports";
import type { Divergence } from "./types";

function games(sport: string, n: number): Divergence[] {
  return Array.from({ length: n }, (_, i) => ({ event_id: `${sport}-${i}`, sport }) as Divergence);
}

// The live shape this bug was reported against: 245 = 207 NFL + 38 NBA.
const NFL = games("nfl", 207);
const NBA = games("nba", 38);
const ALL = [...NFL, ...NBA];

const byKey = (tabs: SportTab[]) => Object.fromEntries(tabs.map((t) => [t.key ?? "all", t]));

describe("sport tabs", () => {
  it("keeps NBA live while the NFL tab is selected", () => {
    // The bug: availability came from the NFL-filtered list, so NBA read
    // "not ingested" the moment NFL was clicked.
    const tabs = byKey(sportTabs({ activeSport: "nfl", filtered: NFL, unfiltered: ALL }));
    expect(tabs.nba).toMatchObject({ state: "available", count: 38 });
    expect(tabs.nfl).toMatchObject({ state: "available", count: 207 });
  });

  it("keeps NFL live while the NBA tab is selected", () => {
    const tabs = byKey(sportTabs({ activeSport: "nba", filtered: NBA, unfiltered: ALL }));
    expect(tabs.nfl).toMatchObject({ state: "available", count: 207 });
  });

  it("gives every tab the same state whichever sport is selected", () => {
    const views = [
      sportTabs({ activeSport: null, filtered: ALL, unfiltered: ALL }),
      sportTabs({ activeSport: "nfl", filtered: NFL, unfiltered: ALL }),
      sportTabs({ activeSport: "nba", filtered: NBA, unfiltered: ALL }),
      sportTabs({ activeSport: "nhl", filtered: [], unfiltered: ALL }),
    ];
    for (const v of views) expect(v).toEqual(views[0]);
  });

  it("says 'not ingested' only for a sport with no games in the feed", () => {
    const tabs = byKey(sportTabs({ activeSport: "nfl", filtered: NFL, unfiltered: ALL }));
    expect(tabs.mlb).toMatchObject({ state: "empty", count: 0 });
    expect(tabs.nhl).toMatchObject({ state: "empty", count: 0 });
    expect(tabs.all).toMatchObject({ state: "available", count: 245 });
  });

  it("claims nothing before the unfiltered feed has loaded", () => {
    const tabs = sportTabs({ activeSport: "nfl", filtered: NFL, unfiltered: undefined });
    expect(tabs.every((t) => t.state === "unknown" && t.count === null)).toBe(true);
  });

  it("on the All tab, the list on screen is the unfiltered feed", () => {
    const tabs = byKey(sportTabs({ activeSport: null, filtered: ALL, unfiltered: undefined }));
    expect(tabs.nba).toMatchObject({ state: "available", count: 38 });
  });

  it("still gives an unexpected sport its own tab", () => {
    const tabs = sportTabs({ activeSport: null, filtered: undefined, unfiltered: games("wnba", 3) });
    expect(tabs.at(-1)).toEqual({ key: "wnba", label: "WNBA", state: "available", count: 3 });
  });
});

describe("browseAllHref", () => {
  it("keeps the sport, so NBA's 'Browse all 37' lands on NBA's 37", () => {
    expect(browseAllHref("nba")).toBe("/?sport=nba&view=all");
  });

  it("is the whole feed on the All tab", () => {
    expect(browseAllHref(null)).toBe("/?view=all");
  });
});
