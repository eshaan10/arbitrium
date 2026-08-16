import { beforeEach, describe, expect, it } from "vitest";
import { FAVORITE_GAMES_KEY, FOLLOWED_TEAMS_KEY, migrateLegacyFavorites } from "./storage";

const LEGACY = "arbitrium:favorites:v1";

/** Minimal localStorage, since these tests run in node. */
function installStorage(seed: Record<string, string> = {}) {
  const store = new Map(Object.entries(seed));
  const localStorage = {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  };
  // @ts-expect-error – test double
  globalThis.window = { localStorage, addEventListener() {}, removeEventListener() {} };
  return store;
}

describe("legacy favourites migration", () => {
  beforeEach(() => {
    // @ts-expect-error – reset between cases
    delete globalThis.window;
  });

  it("renames the old list onto followed teams", () => {
    const store = installStorage({ [LEGACY]: JSON.stringify(["Dallas Cowboys", "Buffalo Bills"]) });

    migrateLegacyFavorites();

    expect(JSON.parse(store.get(FOLLOWED_TEAMS_KEY)!)).toEqual([
      "Dallas Cowboys",
      "Buffalo Bills",
    ]);
  });

  it("removes the legacy key, so it can never run twice", () => {
    const store = installStorage({ [LEGACY]: JSON.stringify(["Dallas Cowboys"]) });

    migrateLegacyFavorites();
    expect(store.has(LEGACY)).toBe(false);

    // The user then unfollows everything. The old list must not come back.
    store.set(FOLLOWED_TEAMS_KEY, JSON.stringify([]));
    migrateLegacyFavorites();
    expect(JSON.parse(store.get(FOLLOWED_TEAMS_KEY)!)).toEqual([]);
  });

  it("never clobbers an existing followed list", () => {
    const store = installStorage({
      [LEGACY]: JSON.stringify(["Dallas Cowboys"]),
      [FOLLOWED_TEAMS_KEY]: JSON.stringify(["Seattle Seahawks"]),
    });

    migrateLegacyFavorites();

    expect(JSON.parse(store.get(FOLLOWED_TEAMS_KEY)!)).toEqual(["Seattle Seahawks"]);
    expect(store.has(LEGACY)).toBe(false);
  });

  it("does not invent a followed list when there was no legacy one", () => {
    const store = installStorage();
    migrateLegacyFavorites();
    expect(store.has(FOLLOWED_TEAMS_KEY)).toBe(false);
  });

  it("discards a corrupt legacy value rather than throwing", () => {
    const store = installStorage({ [LEGACY]: "{not json" });
    expect(() => migrateLegacyFavorites()).not.toThrow();
    expect(store.has(FOLLOWED_TEAMS_KEY)).toBe(false);
    expect(store.has(LEGACY)).toBe(false);
  });

  it("ignores a legacy value of the wrong shape", () => {
    // Team names only. Anything else is not a followed-teams list.
    const store = installStorage({ [LEGACY]: JSON.stringify([1, 2, 3]) });
    migrateLegacyFavorites();
    expect(store.has(FOLLOWED_TEAMS_KEY)).toBe(false);
  });

  it("leaves favourited games alone — the two lists are independent", () => {
    const store = installStorage({
      [LEGACY]: JSON.stringify(["Dallas Cowboys"]),
      [FAVORITE_GAMES_KEY]: JSON.stringify(["event-1"]),
    });

    migrateLegacyFavorites();

    expect(JSON.parse(store.get(FAVORITE_GAMES_KEY)!)).toEqual(["event-1"]);
  });
});

describe("pre-rename prefix migration", () => {
  beforeEach(() => {
    // @ts-expect-error – reset between cases
    delete globalThis.window;
  });

  it("carries MarketEdge-era keys onto the Arbitrium prefix", () => {
    const store = installStorage({
      "marketedge:followedTeams:v1": JSON.stringify(["Buffalo Bills"]),
      "marketedge:favoriteGames:v1": JSON.stringify(["event-9"]),
      "marketedge:recent:v2": JSON.stringify([]),
      "marketedge:dismissed:v1": JSON.stringify({ explainer: true }),
    });

    migrateLegacyFavorites();

    expect(JSON.parse(store.get(FOLLOWED_TEAMS_KEY)!)).toEqual(["Buffalo Bills"]);
    // Chains straight through the v1 -> v2 pin upgrade: the id survives and
    // `rec` is null, because the old format never recorded what the call was.
    expect(JSON.parse(store.get(FAVORITE_GAMES_KEY)!)).toEqual([
      { id: "event-9", rec: null, at: "" },
    ]);
    expect(store.get("arbitrium:dismissed:v1")).toBe(JSON.stringify({ explainer: true }));
  });

  it("removes every old-prefix key so it cannot run twice", () => {
    const store = installStorage({
      "marketedge:followedTeams:v1": JSON.stringify(["Buffalo Bills"]),
    });

    migrateLegacyFavorites();
    expect(store.has("marketedge:followedTeams:v1")).toBe(false);

    // User unfollows everything; the old list must not come back.
    store.set(FOLLOWED_TEAMS_KEY, JSON.stringify([]));
    migrateLegacyFavorites();
    expect(JSON.parse(store.get(FOLLOWED_TEAMS_KEY)!)).toEqual([]);
  });

  it("never clobbers a value already written under the new prefix", () => {
    const store = installStorage({
      "marketedge:followedTeams:v1": JSON.stringify(["Buffalo Bills"]),
      [FOLLOWED_TEAMS_KEY]: JSON.stringify(["Seattle Seahawks"]),
    });

    migrateLegacyFavorites();

    expect(JSON.parse(store.get(FOLLOWED_TEAMS_KEY)!)).toEqual(["Seattle Seahawks"]);
    expect(store.has("marketedge:followedTeams:v1")).toBe(false);
  });

  it("chains the prefix move into the follow/favourite split", () => {
    // A browser that last used the pre-split, pre-rename build.
    const store = installStorage({
      "marketedge:favorites:v1": JSON.stringify(["Chicago Bears"]),
    });

    migrateLegacyFavorites();

    expect(JSON.parse(store.get(FOLLOWED_TEAMS_KEY)!)).toEqual(["Chicago Bears"]);
    expect(store.has("marketedge:favorites:v1")).toBe(false);
    expect(store.has("arbitrium:favorites:v1")).toBe(false);
  });
});
