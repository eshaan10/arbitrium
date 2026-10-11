"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  fetchActivity,
  fetchDivergences,
  LIST_LIMIT,
  queryKeys,
} from "@/lib/api";
import { groupEvents, type Group } from "@/lib/grouping";
import { capPerSport, rankBySignal, signalScale, TODAY_PER_SPORT } from "@/lib/signal";
import { sportTabs } from "@/lib/sports";
import { matchesTeamQuery } from "@/lib/teams";
import { netMovesByEvent } from "@/lib/moves";
import {
  useDensity,
  useFavoriteGames,
  useFollowedTeams,
  useRecentlyViewed,
} from "@/lib/storage";
import { usePriceFlash } from "@/lib/usePriceDeltas";
import { useIsClient } from "@/lib/useIsClient";
import { recSignature } from "@/lib/changes";
import { shouldFold, splitFoldable } from "@/lib/fold";
import { EventCard } from "@/components/event/EventCard";
import { EventRow } from "@/components/event/EventRow";
import { EmptyState } from "@/components/primitives";
import { type View } from "./Controls";
import { Toolbar } from "./Toolbar";
import { InterestingNow } from "./InterestingNow";
import { SinceLastVisit } from "./SinceLastVisit";
import { LandingExplainer } from "./LandingExplainer";
import { PastGames } from "./PastGames";
import { UnscoreableGroup } from "./UnscoreableGroup";
import type { Mode } from "@/lib/mode";
import type { Divergence, DivergencesResponse } from "@/lib/types";

/**
 * Page rhythm, deliberately uneven:
 *
 *   lede      quiet prose, no border — context, not a component
 *   rail      the curated answer, given the most presence on the page
 *   toolbar   one sticky band of controls
 *   list      grouped cards, more air between groups than within them
 *
 * Eight stacked full-width blocks became four. The largest single removal was
 * the stat-tile row, which reprinted the filter chips' own counts in the
 * heaviest type on the page while being the one element you could not click.
 */
export function Dashboard({
  initialData,
  initialAllData,
  sport,
  mode,
  view,
  serverNow,
}: {
  initialData: DivergencesResponse | null;
  /** The unfiltered feed, for sport-tab availability; null on the All tab. */
  initialAllData: DivergencesResponse | null;
  sport: string | null;
  mode: Mode;
  view: View;
  /** The server's clock, used for the first paint so grouping cannot mismatch. */
  serverNow: number;
}) {
  const isClient = useIsClient();
  const [search, setSearch] = useState("");
  const { density } = useDensity();
  // One open row at a time, across every group.
  const [openRow, setOpenRow] = useState<string | null>(null);
  // "Show N more" in Today, which expands in place until the page is left.
  const [todayExpanded, setTodayExpanded] = useState(false);

  const {
    followedTeams,
    toggleFollow,
    isFollowed,
    ready: followReady,
  } = useFollowedTeams();
  const {
    favoriteGames,
    pinnedIds,
    toggleFavoriteGame,
    isFavoriteGame,
    ready: gamesReady,
  } = useFavoriteGames();
  const { record } = useRecentlyViewed();

  const query = { sport: sport ?? undefined, limit: LIST_LIMIT };
  const { data, error, isFetching, dataUpdatedAt } = useQuery({
    queryKey: queryKeys.divergences(query),
    queryFn: () => fetchDivergences(query),
    initialData: initialData ?? undefined,
  });

  // The UNFILTERED feed, for the sport tabs' availability and counts. On the
  // All tab this is the same key as the query above, so React Query serves both
  // from one request; on a sport tab it is the one extra request that keeps the
  // other sports from reading "not ingested".
  const allQuery = { limit: LIST_LIMIT };
  const { data: allData } = useQuery({
    queryKey: queryKeys.divergences(allQuery),
    queryFn: () => fetchDivergences(allQuery),
    initialData: (sport == null ? initialData : initialAllData) ?? undefined,
  });

  // Shared with the ticker and the rail — one request serves all three, so the
  // per-card move chips cost nothing extra.
  const { data: activity } = useQuery({
    queryKey: queryKeys.activity(24),
    queryFn: () => fetchActivity(24, 200),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  const all = useMemo(() => data?.divergences ?? [], [data]);
  const moves = useMemo(() => netMovesByEvent(activity), [activity]);
  usePriceFlash(all, dataUpdatedAt);

  if (error && !data) {
    return (
      <EmptyState title="Can't reach the backend" tone="warn">
        The API at <code className="text-dim">/divergences</code> did not
        respond. If you are running the stack locally, check that the FastAPI
        service is up on port 8000. Nothing is cached here on purpose — showing
        you a stale market would be worse than showing you nothing.
      </EmptyState>
    );
  }

  const minBooks = data?.min_consensus_books ?? 3;
  const stamp = !isClient
    ? ""
    : isFetching
      ? "updating…"
      : dataUpdatedAt
        ? `updated ${new Date(dataUpdatedAt).toLocaleTimeString(undefined, { timeStyle: "short" })}`
        : "";

  // Two independent memberships. A game can be in both, either, or neither,
  // and neither list implies the other.
  const followedSet = new Set(followedTeams);
  const gameSet = new Set(pinnedIds);
  const hasFollowedTeam = (d: Divergence) =>
    followedSet.has(d.home_team ?? "") || followedSet.has(d.away_team ?? "");
  const isPinnedGame = (d: Divergence) => gameSet.has(d.event_id);

  const counts: Record<View, number> = {
    all: all.length,
    recommended: all.filter((d) => d.recommendation).length,
    arbitrage: all.filter((d) => d.is_arbitrage).length,
    unscoreable: all.filter((d) => d.status !== "scored").length,
    "my-teams": all.filter(hasFollowedTeam).length,
    "my-games": all.filter(isPinnedGame).length,
  };

  const tabs = sportTabs({
    activeSport: sport,
    filtered: data?.divergences,
    unfiltered: allData?.divergences,
  });

  const matchesView = (d: Divergence) => {
    if (view === "recommended") return d.recommendation != null;
    if (view === "arbitrage") return d.is_arbitrage;
    if (view === "unscoreable") return d.status !== "scored";
    if (view === "my-teams") return hasFollowedTeam(d);
    if (view === "my-games") return isPinnedGame(d);
    return true;
  };

  // Sections are ranked by signal individually (see sectionRows), so the
  // flat list needs no order of its own.
  const visible = all.filter(
    (d) => matchesView(d) && matchesTeamQuery(search, d.home_team, d.away_team),
  );
  // One scale for every meter on the page, so two rows' meters compare
  // honestly even when they sit in different sections.
  const scale = signalScale(visible);

  // Grouping decides DOM structure, so it uses the SERVER's clock until the
  // client is live; both renders then agree. After that it rides the poll
  // timestamp, which is the browser's own clock and advances on every refetch.
  const groups = groupEvents(
    visible,
    isClient ? dataUpdatedAt || serverNow : serverNow,
  );

  const foldUnscoreable = shouldFold(view, search);

  /**
   * One section's rows: strongest signal first, unscoreable games folded as
   * before, and Today capped at the TODAY_PER_SPORT strongest per sport.
   *
   * The cap follows the fold's rules (shouldFold): a search, My Teams, My
   * Games and the Can't-score view must show every match, so they are never
   * capped. Hidden rows are only ever behind "Show N more", and the section
   * heading keeps counting all of them.
   */
  const sectionRows = (group: Group) => {
    const [shown, folded] = splitFoldable(rankBySignal(group.events), foldUnscoreable);
    if (group.key !== "today" || !foldUnscoreable) return { rows: shown, more: 0, folded };
    const { kept, hidden } = capPerSport(shown, TODAY_PER_SPORT);
    if (hidden.length === 0) return { rows: shown, more: 0, folded };
    return { rows: todayExpanded ? shown : kept, more: hidden.length, folded };
  };

  const recordOpen = (ev: Divergence) =>
    record({
      id: ev.event_id,
      home: ev.home_team,
      away: ev.away_team,
      sport: ev.sport,
      rec: recSignature(ev),
      arb: ev.is_arbitrage,
    });

  return (
    <div className="space-y-10">
      <LandingExplainer />

      <SinceLastVisit events={all} />

      <InterestingNow events={all} />

      <div>
        <Toolbar
          sport={sport}
          sportTabs={tabs}
          view={view}
          counts={counts}
          personalReady={followReady && gamesReady}
          followedTeamCount={followedTeams.length}
          favoriteGameCount={pinnedIds.length}
          mode={mode}
          search={search}
          onSearch={setSearch}
          resultCount={visible.length}
          stamp={stamp}
        />

        <div className="pt-6">
          {groups.length === 0 ? (
            <EmptyState
              title={
                view === "recommended" && !search ? "Nothing worth acting on" : "Nothing here right now"
              }
            >
              {search ? (
                `No events match "${search}".`
              ) : view === "recommended" ? (
                <>
                  {/* Recommended is the landing view, so its empty state has to
                      carry its own weight: this is a genuine reading, not a
                      failure, and the way out is one click with the number
                      already on it. */}
                  No edge currently survives crossing the Kalshi spread. That is a real answer
                  rather than a gap — roughly half of measured divergences are smaller than the
                  spread needed to capture them.{" "}
                  <Link
                    href="/?view=all"
                    className="tap text-signal-600 underline-offset-2 hover:underline"
                  >
                    Browse all {counts.all} events →
                  </Link>
                </>
              ) : view === "my-teams" ? (
                "None of the teams you follow have an upcoming game in this feed."
              ) : view === "my-games" ? (
                "None of your pinned matchups are upcoming. Any that have finished appear below."
              ) : counts.all === 0 ? (
                "No events have been ingested for this filter yet. Far from kickoff, the odds feed carries very few books — this is expected, not a failure."
              ) : (
                "No events match this filter. The other tabs still have data."
              )}
            </EmptyState>
          ) : (
            <div className="space-y-9">
              {groups.map((group) => {
                const { rows: shown, more, folded } = sectionRows(group);
                return (
                <section key={group.key}>
                  <h2 className="rule-label mb-3 flex items-center gap-3 text-[15px] font-medium text-dim">
                    {group.label}
                    {/* The count stays the GROUP total even when some are
                        folded away. The fold states its own number; a header
                        that silently shrank would misreport the feed. */}
                    <span className="tabular text-micro font-normal text-faint">
                      {group.events.length}
                    </span>
                  </h2>
                  {density === "rows" ? (
                    <div className="flex flex-col gap-2">
                      {shown.map((d) => (
                        <EventRow
                          key={d.event_id}
                          d={d}
                          minBooks={minBooks}
                          mode={mode}
                          isFavoriteGame={isFavoriteGame(d.event_id)}
                          onToggleFavoriteGame={(id) => toggleFavoriteGame(id, recSignature(d))}
                          move={moves.get(d.event_id)}
                          onOpen={recordOpen}
                          open={openRow === d.event_id}
                          onToggle={(id) => setOpenRow((cur) => (cur === id ? null : id))}
                          signalScale={scale}
                        />
                      ))}
                    </div>
                  ) : (
                    // Same container and gutter as the three "Interesting right now"
                    // tiles, so on desktop each card is exactly a tile's width.
                    // `items-start`: a quiet card is as tall as its content, not
                    // stretched to match a recommendation card beside it.
                    <div className="grid items-start gap-3 min-[720px]:grid-cols-2 lg:grid-cols-3">
                      {shown.map((d) => (
                        <EventCard
                          key={d.event_id}
                          d={d}
                          minBooks={minBooks}
                          mode={mode}
                          isFollowed={isFollowed}
                          onToggleFollow={toggleFollow}
                          isFavoriteGame={isFavoriteGame(d.event_id)}
                          onToggleFavoriteGame={(id) => toggleFavoriteGame(id, recSignature(d))}
                          move={moves.get(d.event_id)}
                          onOpen={recordOpen}
                          signalScale={scale}
                        />
                      ))}
                    </div>
                  )}
                  {more > 0 ? (
                    <button
                      type="button"
                      aria-expanded={todayExpanded}
                      onClick={() => setTodayExpanded((v) => !v)}
                      className="tap mt-3 rounded-sm px-1 text-[13px] font-medium text-signal-600 underline-offset-4 hover:underline"
                    >
                      {todayExpanded
                        ? "Show fewer"
                        : `Show ${more} more ${more === 1 ? "game" : "games"}`}
                    </button>
                  ) : null}
                  <UnscoreableGroup events={folded} minBooks={minBooks} />
                </section>
                );
              })}
            </div>
          )}

          {/* Pinned games that have kicked off leave /divergences entirely, so
              they are fetched by id and graded here. Only shown in My Games —
              elsewhere they would be an unrelated tangent. */}
          {view === "my-games" && gamesReady ? (
            <div className={groups.length === 0 ? "" : "mt-9"}>
              <PastGames pins={favoriteGames} />
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
