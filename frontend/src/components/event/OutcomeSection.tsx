import { PriceHistory } from "./PriceHistory";
import { cents, num, pct } from "@/lib/format";
import type { EventHistory, Outcome } from "@/lib/types";

function Row({ label, value, title }: { label: string; value: string; title?: string }) {
  return (
    <div title={title} className="flex items-baseline justify-between gap-3 py-1">
      <span className="text-meta text-muted">{label}</span>
      <span className="tabular text-meta text-text">{value}</span>
    </div>
  );
}

/**
 * One outcome, both sources side by side.
 *
 * Kalshi shows the EXECUTABLE prices — what you would actually pay to buy each
 * side — next to its vig-stripped implied probability, because those two
 * numbers answer different questions and the gap between them is exactly what
 * net edge has to survive.
 */
export function OutcomeSection({
  outcome,
  history,
}: {
  outcome: Outcome;
  history: EventHistory | null;
}) {
  const o = outcome;

  return (
    <section className="rounded-lg border border-border bg-surface p-4">
      <h3 className="mb-3 text-body font-medium text-text">{o.team ?? "Outcome"}</h3>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="rounded-md border border-border bg-[var(--surface-sunken)] p-3">
          <div className="mb-1.5 flex items-center gap-1.5">
            <span
              aria-hidden
              className="h-[2px] w-4 rounded-full"
              style={{ background: "var(--series-kalshi)" }}
            />
            <span className="text-micro uppercase tracking-[0.06em] text-muted">Kalshi</span>
          </div>
          <Row label="Implied" value={pct(o.kalshi_probability)} />
          {o.kalshi_ask != null ? (
            <Row label="Buy Yes at" value={cents(o.kalshi_ask)} title="Best resting ask" />
          ) : null}
          {o.kalshi_bid != null ? (
            <Row
              label="Buy No at"
              value={cents(1 - o.kalshi_bid)}
              title="Buying No costs 1 minus the Yes bid"
            />
          ) : null}
          <Row label="Resting depth" value={num(o.resting_depth)} />
          <Row
            label="Spread"
            value={pct(o.spread)}
            title="What a directional edge has to clear before it is worth anything."
          />
        </div>

        <div className="rounded-md border border-border bg-[var(--surface-sunken)] p-3">
          <div className="mb-1.5 flex items-center gap-1.5">
            <span
              aria-hidden
              className="h-[2px] w-4 rounded-full"
              style={{ background: "var(--series-consensus)" }}
            />
            <span className="text-micro uppercase tracking-[0.06em] text-muted">
              Sportsbook consensus
            </span>
          </div>
          <Row label="Implied" value={pct(o.consensus_probability)} />
          <Row label="Books" value={num(o.books ? Object.keys(o.books).length : null)} />
          <Row
            label="Divergence"
            value={pct(o.divergence)}
            title="Gap between the two beliefs. Not capturable on its own."
          />
          <Row
            label="Net edge"
            value={pct(o.net_edge_after_spread)}
            title="What survives crossing Kalshi's spread."
          />
        </div>
      </div>

      <div className="mt-4">
        {history ? (
          <PriceHistory history={history} team={o.team} />
        ) : (
          <p className="text-meta text-muted">Price history unavailable.</p>
        )}
      </div>
    </section>
  );
}
