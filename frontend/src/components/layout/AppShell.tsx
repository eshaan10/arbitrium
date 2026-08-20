"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { StatusCluster } from "./StatusCluster";
import { ActivityTicker } from "./ActivityTicker";

const NAV = [
  { href: "/", label: "Dashboard", short: "Board" },
  { href: "/combos", label: "Combos", short: "Combos" },
  { href: "/performance", label: "Performance", short: "Perf" },
];

/**
 * One organising rule for the chrome:
 *
 *   the HEADER answers "is this data trustworthy?"  — identity, navigation,
 *   and a single consolidated status cluster (per-source freshness plus when
 *   this view was fetched, which are the same question asked twice).
 *
 *   the TOOLBAR answers "what am I looking at?"     — sport, search, filters,
 *   detail level. Those live with the list they control, not up here.
 *
 * Docs links sit in the footer rather than the header: they are for a first
 * visit, and they were competing with navigation on every subsequent one.
 *
 * MOBILE: no hamburger. Three destinations fit on a phone if the labels
 * shorten, and a menu that hides three links behind a tap costs more than it
 * saves — a hamburger is for when nav does not fit, not for when it looks
 * busy. The status cluster keeps its verdict and drops its per-source detail,
 * which is the part that genuinely does not fit.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="flex min-h-dvh flex-col">
      {/* z-40 — above the toolbar's z-30, which is itself above the z-20 band
          card controls occupy. See Toolbar for why that band matters. */}
      <header className="sticky top-0 z-40 border-b border-border bg-[color-mix(in_srgb,var(--bg)_96%,transparent)] backdrop-blur-md">
        <div className="mx-auto flex h-14 max-w-[1160px] items-center gap-3 px-4 sm:gap-6 sm:px-6">
          <Link
            href="/"
            className="tap label shrink-0 text-title font-bold text-signal"
            aria-label="Arbitrium — dashboard"
          >
            Arbitrium
          </Link>

          {/* No overflow property here, deliberately.
              `overflow-x: auto` forces `overflow-y` to compute to `auto` as
              well — the two axes cannot be `visible` and `auto` — and the
              active-tab underline is absolutely positioned 13px BELOW this
              box. So the nav gained 13px of vertical overflow it could never
              scroll, rendered a stray scrollbar inside a 33px-tall bar, and
              clipped the underline it was supposed to be showing. The nav does
              not need to scroll: the labels shorten below `sm` and the three
              destinations fit. */}
          <nav className="-mx-1 flex min-w-0 items-center gap-0.5" aria-label="Main">
            {NAV.map((item) => {
              const active =
                item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={`tap relative shrink-0 rounded-sm px-2 py-1.5 text-body transition-colors sm:px-2.5 ${
                    active ? "text-text" : "text-muted hover:text-dim"
                  }`}
                >
                  {/* The long label where it fits; an abbreviation rather than
                      an ellipsis where it does not. */}
                  <span className="hidden sm:inline">{item.label}</span>
                  <span className="sm:hidden">{item.short}</span>
                  {active ? (
                    <span
                      aria-hidden
                      className="absolute inset-x-2 -bottom-[13px] h-[2px] bg-signal sm:inset-x-2.5"
                    />
                  ) : null}
                </Link>
              );
            })}
          </nav>

          <div className="ml-auto shrink-0">
            <StatusCluster />
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-[1160px] flex-1 px-4 py-6 sm:px-6 sm:py-8">
        {children}
      </main>

      <ActivityTicker />

      <footer className="border-t border-border">
        <div className="mx-auto flex max-w-[1160px] flex-col gap-3 px-4 py-6 sm:flex-row sm:flex-wrap sm:items-baseline sm:gap-x-4 sm:px-6">
          <p className="prose max-w-[68ch] flex-1 text-micro leading-relaxed text-faint">
            Arbitrium compares Kalshi against sportsbook consensus. Nothing here is a guarantee,
            and every figure is gross of fees and execution risk. Events that cannot be scored are
            shown with the reason rather than hidden.
          </p>
          <nav aria-label="Secondary" className="flex items-center gap-4 text-meta">
            <Link href="/how-it-works" className="tap text-muted hover:text-dim">
              How it works
            </Link>
            <Link href="/about" className="tap text-muted hover:text-dim">
              About
            </Link>
          </nav>
        </div>
      </footer>
    </div>
  );
}
