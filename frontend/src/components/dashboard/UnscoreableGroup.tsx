"use client";

import Link from "next/link";
import { useState } from "react";
import { STATUS_LABEL, shortUnscoreableReason } from "@/lib/copy";
import { timeToKickoff } from "@/lib/format";
import { teamVisual } from "@/lib/teams";
import { KickoffTime } from "@/components/event/KickoffTime";
import type { Divergence } from "@/lib/types";

/**
 * Unscoreable events, folded into one disclosure per date group.
 *
 * With 272 of 304 events unscoreable, the full list was mostly repetition: the
 * actionable minority was buried under identical "can't be scored yet" cards.
 * Collapsing them is NOT hiding them — the count is stated, the reasons are
 * summarised on the closed row, and one click brings every game back with its
 * own reason attached. That distinction is the whole point: this product's rule
 * is that an unscoreable event is a RESULT and must be reported with its
 * reason, not filtered out. A summary that says how many there are and why
 * satisfies that rule; silently dropping them would not.
 *
 * Expanding renders COMPACT ROWS rather than the full cards. Twelve full cards
 * would simply re-create the problem the fold exists to solve, and none of the
 * card's apparatus — price hero, stake simulator, evidence line — has anything
 * to show for an event that could not be scored. The row keeps the three facts
 * that do exist: which game, when, and why it could not be scored.
 */
function CompactRow({ d, minBooks }: { d: Divergence; minBooks: number }) {
  const away = teamVisual(d.away_team)?.short ?? d.away_team;
  const home = teamVisual(d.home_team)?.short ?? d.home_team;
  const reason = shortUnscoreableReason(d, minBooks);

  return (
    <li>
      <Link
        href={`/events/${d.event_id}`}
        className="flex flex-col gap-0.5 rounded-sm px-2 py-2 transition-colors hover:bg-raised sm:flex-row sm:items-baseline sm:gap-3"
        title={reason ?? undefined}
      >
        <span className="min-w-0 flex-1 truncate text-meta text-dim">
          {away} <span className="text-faint">@</span> {home}
        </span>
        <span className="flex shrink-0 items-baseline gap-2 text-micro text-faint">
          <span suppressHydrationWarning>{timeToKickoff(d.scheduled_start)}</span>
          <KickoffTime iso={d.scheduled_start} />
          {/* The reason travels with the row, so expanding gives the same
              information the card did — just without the empty apparatus. */}
          <span className="text-muted">{STATUS_LABEL[d.status]}</span>
        </span>
      </Link>
    </li>
  );
}

/** "9 thin consensus · 3 one source only" — what is actually in the fold. */
function summarise(events: Divergence[]): string {
  const counts = new Map<string, number>();
  for (const d of events) {
    const label = STATUS_LABEL[d.status].toLowerCase();
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([label, n]) => `${n} ${label}`)
    .join(" · ");
}

export function UnscoreableGroup({
  events,
  minBooks,
}: {
  events: Divergence[];
  minBooks: number;
}) {
  const [open, setOpen] = useState(false);
  if (events.length === 0) return null;

  return (
    <div className="mt-2.5">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="tap flex w-full items-center gap-2 rounded-sm border border-dashed border-border px-3 py-2 text-left transition-colors hover:border-border-lit"
      >
        <span aria-hidden className="why-chevron shrink-0 text-faint" style={{ transform: open ? "rotate(90deg)" : undefined }}>
          ›
        </span>
        <span className="min-w-0 flex-1 text-meta text-muted">
          <span className="tabular text-dim">{events.length}</span>{" "}
          {events.length === 1 ? "game" : "games"} can’t be scored
          <span className="ml-2 text-micro text-faint">{summarise(events)}</span>
        </span>
        <span className="shrink-0 text-micro text-faint">{open ? "Hide" : "Show"}</span>
      </button>

      {open ? (
        <ul className="mt-1 divide-y divide-border rounded-sm border border-border bg-[var(--surface-sunken)] p-1">
          {events.map((d) => (
            <CompactRow key={d.event_id} d={d} minBooks={minBooks} />
          ))}
        </ul>
      ) : null}
    </div>
  );
}
