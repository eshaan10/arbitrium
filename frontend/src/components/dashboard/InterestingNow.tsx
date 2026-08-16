"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { fetchActivity, queryKeys } from "@/lib/api";
import { reachableValue } from "@/lib/confidence";
import { teamVisual } from "@/lib/teams";
import { cents, pct } from "@/lib/format";
import { InfoPopover } from "@/components/primitives/InfoPopover";
import type { Divergence } from "@/lib/types";

/**
 * Auto-curated, never hand-picked. Three slots, each a different question:
 *
 *  1. Biggest capturable edge — ranked by REACHABLE value, so a huge edge with
 *     five contracts behind it cannot outrank a solid one you can actually take.
 *  2. Today's arbitrage, if one exists at all.
 *  3. The widest price swing in the last 24h, from stored history.
 *
 * A slot with nothing to show says so. Padding an empty rail with the
 * least-bad option would present a non-event as a highlight.
 */
function Slot({
  label,
  info,
  href,
  headline,
  detail,
  empty,
  accent,
}: {
  label: string;
  info?: React.ReactNode;
  href?: string;
  headline?: string;
  detail?: string;
  empty?: string;
  accent?: string;
}) {
  const body = (
    <>
      <div className="flex items-center gap-1.5">
        <span className="text-micro uppercase tracking-[0.09em] text-faint">{label}</span>
        {info}
      </div>
      {headline ? (
        <>
          <div
            className="mt-2 truncate text-headline font-semibold"
            style={{ color: accent ?? "var(--text)" }}
          >
            {headline}
          </div>
          <div className="mt-1 truncate text-meta text-muted">{detail}</div>
        </>
      ) : (
        <div className="mt-2 text-meta leading-relaxed text-faint">{empty}</div>
      )}
    </>
  );

  const className =
    "block rounded-lg border border-border bg-surface p-4 transition-colors" +
    (href ? " hover:border-border-lit" : "");

  return href ? (
    <Link href={href} className={className}>
      {body}
    </Link>
  ) : (
    <div className={className}>{body}</div>
  );
}

export function InterestingNow({ events }: { events: Divergence[] }) {
  const { data: activity } = useQuery({
    queryKey: queryKeys.activity(24),
    queryFn: () => fetchActivity(24, 200),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  const withRec = events.filter((d) => d.recommendation);
  const bestEdge = withRec.length
    ? withRec.reduce((a, b) => (reachableValue(b) > reachableValue(a) ? b : a))
    : null;

  const arb =
    events.find((d) => d.is_arbitrage && d.arbitrage?.includes_kalshi) ??
    events.find((d) => d.is_arbitrage) ??
    null;

  const mover = activity?.movers?.[0] ?? null;

  return (
    <section>
      <h2 className="mb-3 flex items-center gap-3 text-meta font-semibold uppercase tracking-[0.09em] text-dim rule-label">
        Interesting right now
      </h2>
      <div className="grid gap-3 sm:grid-cols-3">
        <Slot
          label="Biggest edge"
          info={<InfoPopover term="netEdge" />}
          href={bestEdge ? `/events/${bestEdge.event_id}` : undefined}
          accent="var(--signal-500)"
          headline={
            bestEdge?.recommendation
              ? `Buy ${bestEdge.recommendation.side} ${
                  teamVisual(bestEdge.recommendation.team)?.short ?? bestEdge.recommendation.team
                } at ${cents(bestEdge.recommendation.price)}`
              : undefined
          }
          detail={
            bestEdge?.recommendation
              ? `${pct(bestEdge.recommendation.edge, 1)} edge · ${bestEdge.n_books ?? 0} books`
              : undefined
          }
          empty="No edge survives the spread right now. That is a real answer, not a gap in the data."
        />

        <Slot
          label="Arbitrage"
          info={<InfoPopover term="arbitrage" />}
          href={arb ? `/events/${arb.event_id}` : undefined}
          accent="var(--arb)"
          headline={arb ? `${arb.away_team} @ ${arb.home_team}` : undefined}
          detail={
            arb?.arbitrage
              ? `${(arb.arbitrage.total_cost * 100).toFixed(1)}¢ for $1 · ${
                  arb.arbitrage.includes_kalshi ? "includes Kalshi" : "no Kalshi leg"
                }`
              : undefined
          }
          empty="No arbitrage open. These are rare and usually short-lived."
        />

        <Slot
          label="Most movement · 24h"
          info={<InfoPopover term="divergence" />}
          href={mover ? `/events/${mover.event_id}` : undefined}
          headline={
            mover ? `${teamVisual(mover.team)?.short ?? mover.team} moved ${pct(mover.swing, 1)}` : undefined
          }
          detail={
            mover
              ? `${mover.away_team} @ ${mover.home_team} · ${mover.changes} recorded changes`
              : undefined
          }
          empty={
            activity
              ? "No price moved more than once in the last 24 hours."
              : "Loading recent movement…"
          }
        />
      </div>
    </section>
  );
}
