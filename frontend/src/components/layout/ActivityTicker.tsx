"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { fetchActivity, queryKeys } from "@/lib/api";
import { teamVisual } from "@/lib/teams";
import { cents } from "@/lib/format";
import { formatCentsDelta } from "@/lib/moves";
import { useLiveArbitrage } from "@/lib/useLiveArbitrage";
import type { ActivityChange } from "@/lib/types";

function ago(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 90) return `${Math.round(s)}s`;
  if (s < 5400) return `${Math.round(s / 60)}m`;
  return `${Math.round(s / 3600)}h`;
}

function ChangeItem({ c }: { c: ActivityChange }) {
  const visual = teamVisual(c.team);
  const up = c.delta > 0;
  return (
    <Link
      href={`/events/${c.event_id}`}
      className="inline-flex shrink-0 items-center gap-1.5 rounded-md px-2 py-1 hover:bg-raised"
    >
      <span className="text-meta text-dim">{visual?.short ?? c.team}</span>
      <span className="tabular text-meta text-muted">
        {cents(c.from)} → <span className="text-text">{cents(c.to)}</span>
      </span>
      <span
        className="tabular text-micro"
        style={{ color: up ? "var(--gain)" : "var(--loss)" }}
      >
        {up ? "▲" : "▼"}
        {formatCentsDelta(c.delta)}¢
      </span>
      <span className="text-micro text-faint">{ago(c.at)}</span>
    </Link>
  );
}

/**
 * Recent real price movement, as a footer strip.
 *
 * In the footer rather than the header on purpose: it is ambient, and a moving
 * element directly above the recommendation list would compete with the thing
 * people came to read.
 *
 * Everything with a timestamp comes from stored snapshot history, so it is
 * populated on first paint and every row is a move that genuinely happened —
 * the dedup trigger only admits a snapshot when the price changed.
 *
 * Arbitrage is the exception and is labelled as such: it is computed on read
 * and never stored, so there is no history of when one opened. Those entries
 * are detected live in this session only, and say so.
 */
export function ActivityTicker() {
  const { data, error } = useQuery({
    queryKey: queryKeys.activity(24),
    // Same arguments as the dashboard's call: the query key is keyed on hours,
    // so differing limits would silently share one cache entry and whichever
    // request landed first would decide how much data everyone got.
    queryFn: () => fetchActivity(24, 200),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  const liveArbs = useLiveArbitrage();

  if (error) return null;

  // The strip only has room for a handful; the shared fetch serves the rail and
  // the per-card move chips too.
  const changes = (data?.changes ?? []).slice(0, 24);

  return (
    <div className="border-t border-border bg-[var(--surface-sunken)]">
      <div className="mx-auto flex max-w-[1160px] items-center gap-3 px-6 py-2.5">
        <span className="shrink-0 text-micro uppercase tracking-[0.07em] text-faint">
          Live · 24h
        </span>

        <div className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
          {liveArbs.map((a) => (
            <Link
              key={`${a.eventId}-${a.at}`}
              href={`/events/${a.eventId}`}
              title="Detected in this session — arbitrage is computed live and is not stored historically."
              className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-arb px-2 py-1 hover:bg-raised"
            >
              <span className="text-meta text-arb">Arbitrage appeared</span>
              <span className="text-micro text-dim">{a.label}</span>
              <span className="text-micro text-faint">this session</span>
            </Link>
          ))}

          {changes.length === 0 && liveArbs.length === 0 ? (
            <span className="text-meta text-faint">
              {data
                ? "No recorded price changes in the last 24 hours. Only genuine moves are stored, so a quiet feed shows nothing rather than filler."
                : "Loading recent moves…"}
            </span>
          ) : (
            changes.map((c) => <ChangeItem key={`${c.event_id}-${c.team}-${c.at}`} c={c} />)
          )}
        </div>
      </div>
    </div>
  );
}
