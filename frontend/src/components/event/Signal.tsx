import { formatSignal, signalFill, signalOf } from "@/lib/signal";
import type { Divergence } from "@/lib/types";

/** Hover text everywhere the meter appears; the "?" popover says the same. */
export const SIGNAL_TITLE =
  "Signal: a relative ranking signal, not a probability and not a promised profit. " +
  "The backend's expected value at depth: the edge left after crossing Kalshi's spread, " +
  "times the contracts resting at that price. The meter is scaled to the strongest game " +
  "in this list. Not yet calibrated across sports.";

/**
 * A small meter plus the backend number, for a scored game.
 *
 * `scale` is the strongest signal in the list it is drawn in, so the meter
 * says "how this compares here" while the number stays the backend's own.
 * Unscoreable games get nothing: they are never ranked.
 */
export function SignalMeter({
  d,
  scale,
  label = false,
  className = "",
}: {
  d: Divergence;
  scale: number;
  /** Prefix the word "Signal", for roomier layouts (cards). */
  label?: boolean;
  className?: string;
}) {
  if (d.status !== "scored") return null;
  const value = signalOf(d);
  const fill = signalFill(value, scale);
  const text = formatSignal(value);
  return (
    <span
      role="meter"
      aria-label={`Signal ${text}, relative`}
      aria-valuemin={0}
      aria-valuemax={1}
      aria-valuenow={Number(fill.toFixed(2))}
      title={SIGNAL_TITLE}
      className={`inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap ${className}`}
    >
      {label ? <span className="text-[13px] text-muted">Signal</span> : null}
      <span aria-hidden className="relative h-[5px] w-8 overflow-hidden rounded-full bg-raised">
        <span
          className="absolute inset-y-0 left-0 rounded-full bg-signal"
          style={{ width: `${Math.round(fill * 100)}%` }}
        />
      </span>
      <span aria-hidden className="tabular text-micro font-medium text-dim">
        {text}
      </span>
    </span>
  );
}
