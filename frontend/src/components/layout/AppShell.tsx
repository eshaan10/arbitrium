"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { StatusCluster } from "./StatusCluster";
import { ActivityTicker } from "./ActivityTicker";

const NAV = [
  { href: "/", label: "Dashboard" },
  { href: "/combos", label: "Combos" },
  { href: "/performance", label: "Performance" },
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
 */
export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="flex min-h-dvh flex-col">
      <header className="sticky top-0 z-30 border-b border-border bg-[color-mix(in_srgb,var(--bg)_86%,transparent)] backdrop-blur-md">
        <div className="mx-auto flex h-14 max-w-[1160px] items-center gap-8 px-6">
          <Link
            href="/"
            className="shrink-0 text-title font-semibold tracking-[-0.02em] text-text"
          >
            Arbi<span className="text-signal">trium</span>
          </Link>

          <nav className="flex items-center gap-0.5" aria-label="Main">
            {NAV.map((item) => {
              const active =
                item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={`relative rounded-md px-2.5 py-1.5 text-body transition-colors ${
                    active ? "text-text" : "text-muted hover:text-dim"
                  }`}
                >
                  {item.label}
                  {active ? (
                    <span
                      aria-hidden
                      className="absolute inset-x-2.5 -bottom-[13px] h-[2px] rounded-full bg-signal"
                    />
                  ) : null}
                </Link>
              );
            })}
          </nav>

          <div className="ml-auto">
            <StatusCluster />
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-[1160px] flex-1 px-6 py-8">{children}</main>

      <ActivityTicker />

      <footer className="border-t border-border">
        <div className="mx-auto flex max-w-[1160px] flex-wrap items-baseline gap-x-4 gap-y-2 px-6 py-6">
          <p className="max-w-[68ch] flex-1 text-micro leading-relaxed text-faint">
            Arbitrium compares Kalshi against sportsbook consensus. Nothing here is a guarantee,
            and every figure is gross of fees and execution risk. Events that cannot be scored are
            shown with the reason rather than hidden.
          </p>
          <nav aria-label="Secondary" className="flex items-center gap-4 text-meta">
            <Link href="/how-it-works" className="text-muted hover:text-dim">
              How it works
            </Link>
            <Link href="/about" className="text-muted hover:text-dim">
              About
            </Link>
          </nav>
        </div>
      </footer>
    </div>
  );
}
