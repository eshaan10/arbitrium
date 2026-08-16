"use client";

import { ModeToggle, SportTabs, ViewFilter, type View } from "./Controls";
import { SearchBar } from "./SearchBar";
import { RecentlyViewed } from "./RecentlyViewed";
import type { Mode } from "@/lib/mode";

/**
 * Everything that answers "what am I looking at?", in one band.
 *
 * Previously four separate rows — sport tabs, four stat tiles, search, filter
 * chips — stacked between the curated rail and the list, so the reader crossed
 * four full-width blocks to reach the first card. The stat tiles are gone
 * entirely: they printed the same four counts as the filter chips directly
 * below them, while being the heaviest element on the page and the only one
 * that could not be clicked.
 *
 * Sticky, because filtering a 288-row list from the top and then scrolling is
 * the actual usage pattern.
 */
export function Toolbar({
  sport,
  sports,
  view,
  counts,
  personalReady,
  followedTeamCount,
  favoriteGameCount,
  mode,
  search,
  onSearch,
  resultCount,
  stamp,
}: {
  sport: string | null;
  sports: string[];
  view: View;
  counts: Record<View, number>;
  personalReady: boolean;
  followedTeamCount: number;
  favoriteGameCount: number;
  mode: Mode;
  search: string;
  onSearch: (v: string) => void;
  resultCount: number;
  stamp: string;
}) {
  return (
    <div className="sticky top-14 z-20 -mx-6 border-b border-border bg-[color-mix(in_srgb,var(--bg)_86%,transparent)] px-6 py-3 backdrop-blur-md">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
        <SportTabs active={sport} available={sports} />

        <div className="ml-auto flex items-center gap-2">
          <SearchBar value={search} onChange={onSearch} resultCount={resultCount} />
          <RecentlyViewed />
          <ModeToggle mode={mode} />
        </div>
      </div>

      <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-2">
        <ViewFilter
          view={view}
          counts={counts}
          personalReady={personalReady}
          followedTeamCount={followedTeamCount}
          favoriteGameCount={favoriteGameCount}
        />
        {/* Belongs to the LIST, not to system health: it says when this query
            was fetched. The header badge answers the separate question of
            whether ingestion itself is alive. */}
        <span
          className="ml-auto text-micro text-faint"
          title="When this list was fetched. Prices are polled continuously."
        >
          {stamp}
        </span>
      </div>
    </div>
  );
}
