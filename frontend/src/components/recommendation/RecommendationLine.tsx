"use client";

import { cents } from "@/lib/format";
import { AnimatedNumber } from "@/components/primitives/AnimatedNumber";
import { InfoPopover } from "@/components/primitives/InfoPopover";
import { ConfidenceBars } from "@/components/primitives";
import { confidence } from "@/lib/confidence";
import type { Divergence } from "@/lib/types";

/**
 * The headline: one platform, one action, in the words Kalshi itself uses.
 *
 * Both sides are BUYS — "Buy No" is a purchase of the No contract, not a sale
 * of Yes — so the verb never changes. This is the primary content of a card;
 * technical metrics never take this slot.
 */
export function RecommendationLine({
  d,
  minBooks,
  size = "md",
}: {
  d: Divergence;
  minBooks: number;
  size?: "md" | "lg";
}) {
  const r = d.recommendation;
  const conf = confidence(d, minBooks);

  if (!r) {
    return (
      <div className="flex items-center justify-between gap-3">
        <span className="text-body text-muted">No recommendation</span>
      </div>
    );
  }

  const priceClass = size === "lg" ? "text-display" : "text-title";

  return (
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
      <span className="flex items-baseline gap-2">
        <span className="rounded-sm bg-[var(--signal-950)] px-1.5 py-0.5 text-meta font-semibold uppercase tracking-[0.04em] text-signal-600">
          Buy {r.side}
        </span>
        <span className="text-title font-medium text-text">{r.team}</span>
        <span className="text-meta text-muted">at</span>
        <AnimatedNumber
          value={r.price}
          format={cents}
          className={`tabular font-semibold text-signal ${priceClass}`}
        />
      </span>
      <span className="flex items-center gap-1.5">
        <ConfidenceBars bars={conf.bars} label={conf.label} />
        <InfoPopover term="confidence" />
      </span>
    </div>
  );
}
