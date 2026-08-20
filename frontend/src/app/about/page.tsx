import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "About — Arbitrium",
  description: "Why Arbitrium was built, and what it is made of.",
};

const REPO = "https://github.com/eshaan10/Arbitrium";

const STACK = [
  ["Ingestion", "Python, httpx, Prefect — Kalshi and The Odds API on independent schedules"],
  ["Storage", "PostgreSQL, append-only snapshots with a dedup trigger"],
  ["API", "FastAPI"],
  ["Frontend", "Next.js App Router, TypeScript, Tailwind, TanStack Query, Recharts"],
];

export default function AboutPage() {
  return (
    <div className="max-w-[68ch] space-y-8">
      <div>
        <h1 className="text-lede font-semibold">About</h1>
        <p className="mt-2 text-body text-dim">
          Arbitrium is an independent auditor for two sports-pricing systems that never check each
          other&apos;s work.
        </p>
      </div>

      <section className="space-y-3 text-body text-dim">
        <h2 className="text-title font-semibold text-text">Why it exists</h2>
        <p>
          Kalshi is a market; a sportsbook is a bookmaker. They price the same games from completely
          different mechanisms, and neither has any incentive to tell you when it disagrees with the
          other — or whether trusting it has historically paid off.
        </p>
        <p>
          The interesting part was never picking winners. It was building something that grades its
          own accuracy honestly: reporting how often it was right, refusing to quote a rate before
          the sample supports one, and keeping a backtest visibly separate from a live record.
        </p>
        <p>
          Most of the engineering effort went into the parts that make that possible — append-only
          history so closing-line value can be measured at all, a dedup trigger so a flat price
          isn&apos;t recorded as activity, and ingest monitoring that survives a crash loop.
        </p>
      </section>

      <section>
        <h2 className="text-title font-semibold text-text">Built with</h2>
        <dl className="mt-2 space-y-2">
          {STACK.map(([label, detail]) => (
            <div key={label} className="flex flex-col gap-0.5 sm:flex-row sm:gap-3">
              <dt className="w-[92px] shrink-0 label text-micro text-muted">
                {label}
              </dt>
              <dd className="text-body text-dim">{detail}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="space-y-2">
        <h2 className="text-title font-semibold text-text">Source</h2>
        <p className="text-body text-dim">
          The code, the schema, and the reasoning behind each decision are on GitHub. The README
          covers the build order and what each phase deliberately left open.
        </p>
        <a
          href={REPO}
          target="_blank"
          rel="noopener noreferrer"
          className="tap inline-block text-body text-signal-600 hover:text-signal"
        >
          ↗ github.com/eshaan10/Arbitrium
        </a>
      </section>

      <p className="border-t border-border pt-5 text-meta leading-relaxed text-faint">
        Not affiliated with Kalshi or any sportsbook. Nothing here is financial advice, and every
        figure is gross of fees and execution risk.{" "}
        <Link href="/how-it-works" className="tap text-muted underline-offset-2 hover:underline">
          How it works
        </Link>
      </p>
    </div>
  );
}
