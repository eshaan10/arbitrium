"use client";

import { useRouter } from "next/navigation";
import { useCallback } from "react";
import type { Mode } from "@/lib/mode";

/** Sports we intend to cover. Only NFL has an ingestion path today. */
const KNOWN_SPORTS = [
  { key: "nfl", label: "NFL" },
  { key: "nba", label: "NBA" },
  { key: "mlb", label: "MLB" },
  { key: "nhl", label: "NHL" },
];

function useSetParam() {
  const router = useRouter();
  return useCallback(
    (updates: Record<string, string | null>) => {
      const params = new URLSearchParams(window.location.search);
      for (const [k, v] of Object.entries(updates)) {
        if (v == null) params.delete(k);
        else params.set(k, v);
      }
      const qs = params.toString();
      router.replace(qs ? `${window.location.pathname}?${qs}` : window.location.pathname, {
        scroll: false,
      });
    },
    [router],
  );
}

/**
 * Sport tabs, derived from what the feed actually returned.
 *
 * Sports with no data are rendered as disabled tabs saying so, rather than
 * omitted or shown as empty-but-clickable. A tab that looks live and returns
 * nothing reads as a broken product; a tab that says "not yet ingested" is the
 * truth and costs one word.
 */
export function SportTabs({
  active,
  available,
}: {
  active: string | null;
  available: string[];
}) {
  const setParam = useSetParam();
  const have = new Set(available.map((s) => s.toLowerCase()));

  const tabs = [
    { key: null as string | null, label: "All", enabled: true },
    ...KNOWN_SPORTS.map((s) => ({ ...s, enabled: have.has(s.key) })),
    // Anything the feed returned that we did not anticipate still gets a tab.
    ...available
      .map((s) => s.toLowerCase())
      .filter((s) => !KNOWN_SPORTS.some((k) => k.key === s))
      .map((s) => ({ key: s, label: s.toUpperCase(), enabled: true })),
  ];

  return (
    <div
      role="tablist"
      aria-label="Sport"
      className="scroll-x -mx-4 flex items-center gap-1 px-4 sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-0"
    >
      {tabs.map((t) => {
        const isActive = (t.key ?? null) === (active ?? null);
        return (
          <button
            key={t.key ?? "all"}
            role="tab"
            aria-selected={isActive}
            disabled={!t.enabled}
            title={t.enabled ? undefined : `${t.label} is not ingested yet`}
            onClick={() => setParam({ sport: t.key })}
            className={`tap shrink-0 whitespace-nowrap rounded-sm px-2.5 py-1.5 text-body transition-colors sm:px-3 ${
              isActive
                ? // Dark on amber. White on this accent fails contrast.
                  "bg-signal font-medium text-bg"
                : t.enabled
                  ? "text-dim hover:bg-raised hover:text-text"
                  : "cursor-not-allowed text-faint"
            }`}
          >
            {t.label}
            {!t.enabled ? (
              <span className="ml-1.5 hidden text-micro sm:inline">not ingested</span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

/** Simple is the default everywhere. Advanced is opt-in and shareable. */
export function ModeToggle({ mode }: { mode: Mode }) {
  const setParam = useSetParam();
  return (
    <div
      className="inline-flex shrink-0 rounded-sm border border-border p-0.5"
      role="group"
      aria-label="Detail level"
    >
      {(["simple", "advanced"] as const).map((m) => (
        <button
          key={m}
          aria-pressed={mode === m}
          onClick={() => setParam({ mode: m === "simple" ? null : m })}
          title={`${m === "simple" ? "Simple" : "Advanced"} detail level`}
          className={`tap rounded-[3px] px-2 py-1 text-meta capitalize transition-colors sm:px-3 ${
            mode === m ? "bg-raised text-text" : "text-muted hover:text-dim"
          }`}
        >
          {/* One letter on a phone. The pair still reads as a two-state toggle
              because both states are visible; an icon would not. */}
          <span className="sm:hidden">{m === "simple" ? "S" : "A"}</span>
          <span className="hidden sm:inline">{m}</span>
        </button>
      ))}
    </div>
  );
}

export type View = "all" | "recommended" | "arbitrage" | "unscoreable" | "my-teams" | "my-games";

/**
 * Two personal views, kept apart.
 *
 * "My Teams" and "My Games" answer different questions — every game a followed
 * team plays, versus the specific matchups you pinned — so they are separate,
 * independently browsable chips rather than one merged "Favorites". Collapsing
 * them would make it impossible to ask either question on its own.
 *
 * Each is disabled until it has something in it, with a title saying how to
 * fill it: a filter that can only ever return nothing is worse than one that
 * explains why it is unavailable.
 */
export function ViewFilter({
  view,
  counts,
  personalReady,
  followedTeamCount,
  favoriteGameCount,
}: {
  view: View;
  counts: Record<View, number>;
  personalReady: boolean;
  followedTeamCount: number;
  favoriteGameCount: number;
}) {
  const setParam = useSetParam();
  // Recommended leads because it is the default landing view — the chip order
  // and the default have to agree, or the highlighted chip appears to be in the
  // middle of the row for no reason.
  const items: { key: View; label: string }[] = [
    { key: "recommended", label: "Recommended" },
    { key: "all", label: "All" },
    { key: "arbitrage", label: "Arbitrage" },
    { key: "unscoreable", label: "Can't score" },
  ];

  const personal: {
    key: View;
    label: string;
    glyph: string;
    empty: boolean;
    hint: string;
    filled: string;
  }[] = [
    {
      key: "my-teams",
      label: "My Teams",
      glyph: "+",
      empty: !personalReady || followedTeamCount === 0,
      hint: "Follow a team with the + beside its name to fill this",
      filled: `${followedTeamCount} followed ${followedTeamCount === 1 ? "team" : "teams"}`,
    },
    {
      key: "my-games",
      label: "My Games",
      glyph: "★",
      empty: !personalReady || favoriteGameCount === 0,
      hint: "Pin a matchup with the star at a card's corner to fill this",
      filled: `${favoriteGameCount} pinned ${favoriteGameCount === 1 ? "game" : "games"}`,
    },
  ];

  return (
    <div className="flex items-center gap-1 sm:flex-wrap">
      {items.map((it) => (
        <button
          key={it.key}
          aria-pressed={view === it.key}
          onClick={() => setParam({ view: it.key === "recommended" ? null : it.key })}
          className={`tap shrink-0 whitespace-nowrap rounded-sm px-2 py-1 text-meta transition-colors sm:px-2.5 ${
            view === it.key ? "bg-raised text-text" : "text-muted hover:text-dim"
          }`}
        >
          {it.label}
          <span className="tabular ml-1.5 text-micro text-faint">{counts[it.key]}</span>
        </button>
      ))}

      <span aria-hidden className="mx-1 h-4 w-px shrink-0 bg-border" />

      {personal.map((p) => (
        <button
          key={p.key}
          aria-pressed={view === p.key}
          disabled={p.empty}
          title={p.empty ? p.hint : p.filled}
          onClick={() => setParam({ view: view === p.key ? null : p.key })}
          className={`tap flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-sm px-2 py-1 text-meta transition-colors sm:px-2.5 ${
            view === p.key
              ? "bg-raised text-signal"
              : p.empty
                ? "cursor-not-allowed text-faint"
                : "text-muted hover:text-dim"
          }`}
        >
          <span aria-hidden className={view === p.key ? "text-signal" : "text-faint"}>
            {p.glyph}
          </span>
          {p.label}
          {!p.empty ? (
            <span className="tabular text-micro text-faint">{counts[p.key]}</span>
          ) : null}
        </button>
      ))}
    </div>
  );
}
