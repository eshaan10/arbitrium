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
  // z-30, above the z-20 band that card-internal controls live in.
  // At z-20 this tied with the stake simulator and the follow/pin buttons, and
  // a tie is broken by DOM order — the cards come later, so a card's stake line
  // painted straight over the sticky filter chips as you scrolled. The chrome
  // needs its own band, above anything inside a card. Full layering:
  // card overlay 10 · card controls 20 · toolbar 30 · header 40 · popovers 50.
  return (
    <div className="sticky top-14 z-30 -mx-4 border-b border-border bg-[color-mix(in_srgb,var(--bg)_96%,transparent)] px-4 py-2.5 backdrop-blur-md sm:-mx-6 sm:px-6 sm:py-3">
      {/* Search leads on a phone: it is the control that makes a 288-row list
          usable on a small screen, and it is full-width there rather than
          sharing a row. On a wide screen the sport tabs lead instead, because
          the whole list is already in view. */}
      <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-4 sm:gap-y-3">
        <div className="order-2 sm:order-1">
          <SportTabs active={sport} available={sports} />
        </div>

        <div className="order-1 flex items-center gap-2 sm:order-2 sm:ml-auto">
          <SearchBar value={search} onChange={onSearch} resultCount={resultCount} />
          <RecentlyViewed />
          <ModeToggle mode={mode} />
        </div>
      </div>

      {/* The view chips scroll sideways on a phone rather than wrapping onto a
          third line — the toolbar is sticky, so every line it grows is a line
          permanently taken from the list below it. */}
      <div className="mt-2 flex items-center gap-x-3 sm:mt-2.5 sm:flex-wrap">
        <div className="scroll-x -mx-4 min-w-0 flex-1 px-4 sm:mx-0 sm:overflow-visible sm:px-0">
          <ViewFilter
            view={view}
            counts={counts}
            personalReady={personalReady}
            followedTeamCount={followedTeamCount}
            favoriteGameCount={favoriteGameCount}
          />
        </div>
        {/* Belongs to the LIST, not to system health: it says when this query
            was fetched. The header badge answers the separate question of
            whether ingestion itself is alive. */}
        <span
          className="hidden shrink-0 text-micro text-faint sm:ml-auto sm:inline"
          title="When this list was fetched. Prices are polled continuously."
        >
          {stamp}
        </span>
      </div>
    </div>
  );
}
