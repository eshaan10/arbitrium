import { Metric } from "@/components/primitives";
import { money, num, pct, titleCase } from "@/lib/format";
import type { Divergence } from "@/lib/types";

/**
 * Advanced mode only. This is an ADDITIONAL mount, not a CSS reveal — jargon
 * stays structurally out of Simple mode rather than depending on a class that
 * could leak.
 *
 * Divergence and net edge sit next to each other on purpose: a large
 * divergence with a negative net edge is real and worth nothing, and showing
 * either one alone invites mistaking it for the other.
 */
export function AdvancedMetrics({ d }: { d: Divergence }) {
  const bt = d.best_trade;
  // Three columns at every width: the card sits in a two-up grid, so six
  // columns only fit the viewport, not the container the card actually has.
  return (
    <div className="grid grid-cols-3 gap-x-4 gap-y-3 rounded-md border border-border bg-[var(--surface-sunken)] p-3">
      <Metric
        label="Divergence"
        value={pct(d.max_abs_divergence)}
        title="How far apart the two sources' vig-stripped beliefs are. Not what you can capture."
      />
      <Metric
        label="Net edge"
        value={pct(d.best_net_edge)}
        negative={(d.best_net_edge ?? 0) < 0}
        title="What survives crossing Kalshi's spread. This is the capturable number."
      />
      <Metric
        label="EV @ depth"
        value={money(d.best_expected_value)}
        negative={(d.best_expected_value ?? 0) < 0}
        title="Expected value at the size actually resting on the book."
      />
      <Metric label="Books" value={num(d.n_books)} title="Bookmakers behind the consensus median." />
      <Metric
        label="Depth"
        value={num(bt?.resting_depth)}
        title="Contracts resting at the recommended price."
      />
      <Metric label="Status" value={titleCase(d.status)} />
    </div>
  );
}
