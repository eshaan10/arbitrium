"use client";

import Link from "next/link";
import { changesSinceLastVisit } from "@/lib/changes";
import { useRecentlyViewed } from "@/lib/storage";
import type { Divergence } from "@/lib/types";

/**
 * What moved on events you previously opened.
 *
 * Renders nothing when there is no history and nothing when nothing changed —
 * a "no changes" banner on a first visit would be noise, and this only ever
 * speaks when it has something specific to say.
 */
export function SinceLastVisit({ events }: { events: Divergence[] }) {
  const { recent, ready } = useRecentlyViewed();

  if (!ready || recent.length === 0) return null;

  const changes = changesSinceLastVisit(recent, events);
  if (changes.length === 0) return null;

  return (
    <section
      aria-label="Changes since your last visit"
      className="rounded-lg border border-signal-800 bg-[var(--signal-950)] p-3.5"
    >
      <h2 className="text-micro font-semibold uppercase tracking-[0.07em] text-signal-600">
        Since you last looked
      </h2>
      <ul className="mt-2 space-y-1.5">
        {changes.map((c) => (
          <li key={`${c.eventId}-${c.kind}`}>
            <Link
              href={`/events/${c.eventId}`}
              className="group flex flex-wrap items-baseline gap-x-2 text-meta"
            >
              <span className="font-medium text-text group-hover:text-signal">{c.label}</span>
              <span className="text-muted">{c.detail}</span>
            </Link>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-micro text-faint">
        Based on events you opened in this browser. Nothing is stored anywhere else.
      </p>
    </section>
  );
}
