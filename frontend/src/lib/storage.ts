"use client";

import { useCallback, useMemo, useSyncExternalStore } from "react";

/**
 * localStorage-backed state. No accounts, no sync, no server.
 *
 * Keys are VERSIONED. A shape change ships under a new suffix rather than
 * trying to migrate whatever is in a stranger's browser, and anything that
 * fails to parse degrades to the default instead of throwing — a corrupt
 * favourites list must not be able to take the dashboard down.
 *
 * Implemented over useSyncExternalStore because localStorage IS an external
 * store: the server snapshot is the default, so the first client render matches
 * the server exactly and the stored value arrives immediately after. It also
 * makes changes propagate across tabs for free.
 */

/**
 * Two INDEPENDENT personalisation lists, deliberately not one.
 *
 *   followedTeams — "I care about this team." Keyed by canonical team name, so
 *                   it outlives the fixture that prompted it and surfaces every
 *                   future game they play.
 *   favoriteGames — "I care about this specific matchup." Keyed by event id,
 *                   and says nothing about either team.
 *
 * Merging them into one "favourites" list would make those two statements
 * indistinguishable, and there is no rule that recovers which one a user meant.
 */
export const FOLLOWED_TEAMS_KEY = "arbitrium:followedTeams:v1";
/**
 * v2 stores the call that was live WHEN YOU PINNED, alongside the id. Without
 * it a resolved game can only ever say who won, never whether the thing you
 * pinned it for turned out right — and reconstructing the old call from today's
 * data would be inventing a record that was never kept.
 */
export const FAVORITE_GAMES_KEY = "arbitrium:favoriteGames:v2";
const FAVORITE_GAMES_KEY_V1 = "arbitrium:favoriteGames:v1";

/** Pre-split key (already under the current prefix). */
const LEGACY_FAVORITES_KEY = "arbitrium:favorites:v1";

/**
 * The product was called MarketEdge until the rename, and every key was
 * namespaced with it. A browser that used the old build still holds those keys,
 * so the rename would silently discard someone's follows and pins unless they
 * are carried across.
 */
const LEGACY_PREFIX = "marketedge:";
const CURRENT_PREFIX = "arbitrium:";
const MIGRATED_SUFFIXES = [
  "followedTeams:v1",
  "favoriteGames:v2",
  "favoriteGames:v1",
  "favorites:v1",
  "recent:v2",
  "recent:v1",
  "dismissed:v1",
];
// v2 adds the recommendation snapshot needed by "what changed since your last
// visit". Bumped rather than migrated: a v1 entry has no baseline to compare
// against, and inventing one would report a change that was never observed.
export const RECENT_KEY = "arbitrium:recent:v2";
export const RECENT_LIMIT = 8;

/** Same-tab listeners. The `storage` event only fires in OTHER tabs. */
const listeners = new Set<() => void>();

function emit() {
  for (const l of listeners) l();
}

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  window.addEventListener("storage", onChange);
  return () => {
    listeners.delete(onChange);
    window.removeEventListener("storage", onChange);
  };
}

function readRaw(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeRaw(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Quota or private-mode failures are not worth surfacing: the feature is a
    // convenience and the app is fully usable without it.
  }
  emit();
}

/**
 * Returns the RAW string, not a parsed object: useSyncExternalStore compares
 * snapshots by identity, and parsing on every read would hand back a fresh
 * object each time and spin forever. Parsing happens once, in a memo.
 */
function useRawItem(key: string): string | null {
  return useSyncExternalStore(
    subscribe,
    () => readRaw(key),
    () => null,
  );
}

function useJsonItem<T>(key: string, fallback: T) {
  const raw = useRawItem(key);

  const value = useMemo(() => {
    if (raw == null) return fallback;
    try {
      return JSON.parse(raw) as T;
    } catch {
      return fallback;
    }
    // `fallback` is a literal at every call site; keying on it would defeat the memo.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [raw]);

  const update = useCallback(
    (next: T | ((prev: T) => T)) => {
      const current = (() => {
        const r = readRaw(key);
        if (r == null) return fallback;
        try {
          return JSON.parse(r) as T;
        } catch {
          return fallback;
        }
      })();
      const resolved = typeof next === "function" ? (next as (p: T) => T)(current) : next;
      writeRaw(key, JSON.stringify(resolved));
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [key],
  );

  // False during SSR and the hydration pass — callers use it to avoid rendering
  // a control whose state the server could not have known.
  const ready = useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  );

  return { value, update, ready };
}

/* --- followed teams / favourited games ----------------------------------- */

const EMPTY: string[] = [];

/**
 * Moves a pre-split favourites list onto the followed-teams key.
 *
 * The old list held team names, which is exactly what "follow" now means, so
 * the migration is a rename and nothing is reinterpreted. It DELETES the legacy
 * key afterwards, which makes it self-idempotent: once gone it can never run
 * again, so a user who later unfollows everything does not have their old list
 * resurrected on the next load.
 *
 * Runs once on the client, mounted by <StorageMigrations />.
 */
function migrateLegacyPrefix(): void {
  for (const suffix of MIGRATED_SUFFIXES) {
    const from = LEGACY_PREFIX + suffix;
    const to = CURRENT_PREFIX + suffix;
    try {
      const value = window.localStorage.getItem(from);
      if (value == null) continue;
      // Never clobber a value written under the new name.
      if (window.localStorage.getItem(to) == null) {
        window.localStorage.setItem(to, value);
      }
      // Removed unconditionally, which is what makes this idempotent: once the
      // old key is gone it can never re-run and never resurrect stale data.
      window.localStorage.removeItem(from);
    } catch {
      // One unreadable key must not stop the rest from migrating.
    }
  }
}

export function migrateLegacyFavorites(): void {
  try {
    // Carry pre-rename keys over first, so the follow/favourite split below
    // sees them.
    migrateLegacyPrefix();
    migrateFavoriteGamesV1();

    const legacy = window.localStorage.getItem(LEGACY_FAVORITES_KEY);
    if (legacy == null) {
      emit();
      return;
    }

    // Never clobber a real followed list if both somehow exist.
    if (window.localStorage.getItem(FOLLOWED_TEAMS_KEY) == null) {
      // Parsing is fenced separately so a corrupt value cannot skip the
      // removal below — otherwise the migration would fail, leave the bad key
      // in place, and retry on every single page load forever.
      let teams: string[] | null = null;
      try {
        const parsed: unknown = JSON.parse(legacy);
        if (Array.isArray(parsed) && parsed.every((t) => typeof t === "string")) {
          teams = parsed as string[];
        }
      } catch {
        teams = null;
      }
      if (teams) {
        window.localStorage.setItem(FOLLOWED_TEAMS_KEY, JSON.stringify(teams));
      }
    }

    window.localStorage.removeItem(LEGACY_FAVORITES_KEY);
    emit();
  } catch {
    // A browser that will not let us touch storage simply starts empty.
  }
}

function useStringSet(key: string) {
  const { value, update, ready } = useJsonItem<string[]>(key, EMPTY);

  const toggle = useCallback(
    (id: string) =>
      update((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id])),
    [update],
  );

  const has = useCallback(
    (id: string | null | undefined) => !!id && value.includes(id),
    [value],
  );

  return { value, toggle, has, ready };
}

/** "Follow" — every game this team plays. Keyed by canonical team name. */
export function useFollowedTeams() {
  const { value, toggle, has, ready } = useStringSet(FOLLOWED_TEAMS_KEY);
  return { followedTeams: value, toggleFollow: toggle, isFollowed: has, ready };
}

export interface PinnedGame {
  id: string;
  /**
   * Recommendation signature ("yes|Dallas Cowboys") at the moment of pinning,
   * or null if there was none. NEVER back-filled — a pin made when no call
   * existed must stay that way.
   */
  rec: string | null;
  /** ISO timestamp of the pin. */
  at: string;
}

const NO_PINS: PinnedGame[] = [];

/**
 * Upgrades v1 pins (bare ids) to v2.
 *
 * `rec` becomes null rather than being reconstructed: the old format simply did
 * not record what the call was, and guessing from current data would fabricate
 * a history the user never saw.
 */
function migrateFavoriteGamesV1(): void {
  try {
    const old = window.localStorage.getItem(FAVORITE_GAMES_KEY_V1);
    if (old == null) return;
    if (window.localStorage.getItem(FAVORITE_GAMES_KEY) == null) {
      let ids: string[] = [];
      try {
        const parsed: unknown = JSON.parse(old);
        if (Array.isArray(parsed)) ids = parsed.filter((x): x is string => typeof x === "string");
      } catch {
        ids = [];
      }
      const upgraded: PinnedGame[] = ids.map((id) => ({ id, rec: null, at: "" }));
      if (upgraded.length > 0) {
        window.localStorage.setItem(FAVORITE_GAMES_KEY, JSON.stringify(upgraded));
      }
    }
    window.localStorage.removeItem(FAVORITE_GAMES_KEY_V1);
  } catch {
    // Unreadable storage simply starts empty.
  }
}

/** "Favorite" — this one matchup, regardless of who is playing. Keyed by event id. */
export function useFavoriteGames() {
  const { value, update, ready } = useJsonItem<PinnedGame[]>(FAVORITE_GAMES_KEY, NO_PINS);

  const toggleFavoriteGame = useCallback(
    (id: string, rec: string | null = null) =>
      update((prev) =>
        prev.some((p) => p.id === id)
          ? prev.filter((p) => p.id !== id)
          : [...prev, { id, rec, at: new Date().toISOString() }],
      ),
    [update],
  );

  const isFavoriteGame = useCallback(
    (id: string | null | undefined) => !!id && value.some((p) => p.id === id),
    [value],
  );

  const pinnedIds = useMemo(() => value.map((p) => p.id), [value]);

  return { favoriteGames: value, pinnedIds, toggleFavoriteGame, isFavoriteGame, ready };
}

/* --- recently viewed ----------------------------------------------------- */

export interface RecentEvent {
  id: string;
  home: string | null;
  away: string | null;
  sport: string | null;
  /** ISO timestamp of the visit. */
  at: string;
  /**
   * What the recommendation was WHEN LAST SEEN — "yes|Dallas Cowboys" or null
   * for no recommendation. Compared against live data to detect a flip.
   */
  rec: string | null;
  /** Whether an arbitrage was open when last seen. */
  arb: boolean;
}

const NO_RECENTS: RecentEvent[] = [];

/**
 * The last few events opened. Stores a display SNAPSHOT rather than just an id
 * so the list can render without refetching — an event that has since dropped
 * out of the feed still shows what it was, instead of a blank row.
 */
export function useRecentlyViewed() {
  const { value, update, ready } = useJsonItem<RecentEvent[]>(RECENT_KEY, NO_RECENTS);

  const record = useCallback(
    (event: Omit<RecentEvent, "at">) => {
      update((prev) =>
        [
          { ...event, at: new Date().toISOString() },
          ...prev.filter((e) => e.id !== event.id),
        ].slice(0, RECENT_LIMIT),
      );
    },
    [update],
  );

  const clear = useCallback(() => update(NO_RECENTS), [update]);

  return { recent: value, record, clear, ready };
}
