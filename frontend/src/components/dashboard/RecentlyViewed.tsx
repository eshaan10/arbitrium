"use client";

import Link from "next/link";
import { useState } from "react";
import { useRecentlyViewed } from "@/lib/storage";
import { teamVisual } from "@/lib/teams";

/**
 * The last few events this browser opened. localStorage only — there is no
 * account here and nothing leaves the machine.
 */
export function RecentlyViewed() {
  const { recent, clear, ready } = useRecentlyViewed();
  const [open, setOpen] = useState(false);

  // Renders nothing until the client has read storage, so the server and the
  // first client pass agree.
  if (!ready || recent.length === 0) return null;

  return (
    <div className="relative">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="rounded-md border border-border px-2.5 py-1.5 text-meta text-muted hover:text-dim"
      >
        Recent
        <span className="tabular ml-1.5 text-micro text-faint">{recent.length}</span>
      </button>

      {open ? (
        <>
          {/* Click-away target. */}
          <div className="fixed inset-0 z-20" onClick={() => setOpen(false)} aria-hidden />
          <div className="absolute right-0 z-30 mt-1.5 w-[280px] rounded-lg border border-border-lit bg-surface p-1.5 shadow-[var(--shadow-panel)]">
            {recent.map((e) => {
              const away = teamVisual(e.away);
              const home = teamVisual(e.home);
              return (
                <Link
                  key={e.id}
                  href={`/events/${e.id}`}
                  onClick={() => setOpen(false)}
                  className="block rounded-md px-2.5 py-2 hover:bg-raised"
                >
                  <div className="truncate text-meta text-text">
                    {away?.short ?? e.away} <span className="text-muted">@</span>{" "}
                    {home?.short ?? e.home}
                  </div>
                  <div className="text-micro uppercase tracking-[0.06em] text-faint">
                    {e.sport ?? ""}
                  </div>
                </Link>
              );
            })}
            <button
              type="button"
              onClick={() => {
                clear();
                setOpen(false);
              }}
              className="mt-1 w-full rounded-md px-2.5 py-1.5 text-left text-meta text-faint hover:bg-raised hover:text-muted"
            >
              Clear history
            </button>
          </div>
        </>
      ) : null}
    </div>
  );
}
