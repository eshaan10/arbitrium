import type { Divergence } from "./types";

/** Sports we intend to cover; any other sport the feed returns still gets a tab. */
export const KNOWN_SPORTS = [
  { key: "nfl", label: "NFL" },
  { key: "nba", label: "NBA" },
  { key: "mlb", label: "MLB" },
  { key: "nhl", label: "NHL" },
] as const;

/**
 * "available": the feed has games for it. "empty": the feed has none, so the
 * tab says "not ingested". "unknown": the unfiltered feed has not loaded yet,
 * and saying "not ingested" would be a claim we cannot back.
 */
export type SportTabState = "available" | "empty" | "unknown";

export interface SportTab {
  key: string | null;
  label: string;
  state: SportTabState;
  /** Games in the feed for this tab; null while unknown. */
  count: number | null;
}

/**
 * The sport tabs: which are live, and how many games each holds.
 *
 * Counted from the UNFILTERED feed, never from the list on screen. The list on
 * screen is the response to /divergences?sport=<active tab>, so counting it
 * made every other sport look empty: on NFL, NBA read "not ingested"; on NBA,
 * NFL did. Availability is a fact about the backend, and it cannot depend on
 * which tab happens to be selected.
 *
 * `filtered` is used for one thing only: on the All tab it IS the unfiltered
 * feed (same query), so it can stand in before the separate query resolves.
 */
export function sportTabs({
  activeSport,
  filtered,
  unfiltered,
}: {
  activeSport: string | null;
  filtered: Divergence[] | undefined;
  unfiltered: Divergence[] | undefined;
}): SportTab[] {
  const source = unfiltered ?? (activeSport == null ? filtered : undefined);

  const counts = new Map<string, number>();
  for (const d of source ?? []) {
    const s = d.sport?.toLowerCase();
    if (s) counts.set(s, (counts.get(s) ?? 0) + 1);
  }

  const tab = (key: string, label: string): SportTab => {
    if (source === undefined) return { key, label, state: "unknown", count: null };
    const count = counts.get(key) ?? 0;
    return { key, label, state: count > 0 ? "available" : "empty", count };
  };

  const known = new Set<string>(KNOWN_SPORTS.map((s) => s.key));
  return [
    {
      key: null,
      label: "All",
      state: source === undefined ? "unknown" : "available",
      count: source?.length ?? null,
    },
    ...KNOWN_SPORTS.map((s) => tab(s.key, s.label)),
    ...[...counts.keys()]
      .filter((s) => !known.has(s))
      .sort()
      .map((s) => tab(s, s.toUpperCase())),
  ];
}
