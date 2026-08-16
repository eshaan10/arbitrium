import type { RiskTier } from "@/lib/types";

/**
 * The combo card's layout, with no data in it.
 *
 * Deliberately NOT a mock combo with plausible team names and prices: a
 * realistic-looking fake on a page about betting is the exact thing this
 * product refuses to ship. The slots are drawn empty and labelled, so the shape
 * can be reviewed without anything on screen being mistakable for a live
 * recommendation.
 */
const LEGS: Record<RiskTier, number> = { safe: 2, balanced: 3, max_payout: 5 };

function Slot({ className = "" }: { className?: string }) {
  return <div className={`rounded-sm bg-[var(--surface-raised)] ${className}`} />;
}

export function ComboShapePreview({ tier }: { tier: RiskTier }) {
  const legs = LEGS[tier];

  return (
    <div className="rounded-lg border border-dashed border-border-lit bg-surface p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-micro uppercase tracking-[0.07em] text-faint">
          Layout preview — no data
        </span>
        <span className="text-micro text-faint">
          {legs} legs at this tier
        </span>
      </div>

      <div className="space-y-2">
        {Array.from({ length: legs }).map((_, i) => (
          <div
            key={i}
            className="flex items-center gap-3 rounded-md border border-border bg-[var(--surface-sunken)] p-3"
          >
            <div className="min-w-0 flex-1 space-y-1.5">
              <Slot className="h-2.5 w-[45%]" />
              <Slot className="h-2 w-[28%]" />
            </div>
            <div className="text-right">
              <div className="text-micro uppercase tracking-[0.06em] text-faint">price</div>
              <Slot className="mt-1 h-3 w-12" />
            </div>
            <div className="text-right">
              <div className="text-micro uppercase tracking-[0.06em] text-faint">calibrated</div>
              <Slot className="mt-1 h-3 w-12" />
            </div>
          </div>
        ))}
      </div>

      <div className="mt-3 grid grid-cols-3 gap-3 border-t border-border pt-3">
        {["Joint probability", "Total cost", "Payout"].map((label) => (
          <div key={label}>
            <div className="text-micro uppercase tracking-[0.06em] text-faint">{label}</div>
            <Slot className="mt-1 h-4 w-16" />
          </div>
        ))}
      </div>

      <div className="mt-3 rounded-md border border-border bg-[var(--surface-sunken)] p-2.5">
        <div className="text-micro uppercase tracking-[0.06em] text-faint">
          Independence assumption
        </div>
        <Slot className="mt-1.5 h-2 w-[80%]" />
        <Slot className="mt-1.5 h-2 w-[60%]" />
      </div>
    </div>
  );
}
