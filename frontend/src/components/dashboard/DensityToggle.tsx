"use client";

import { useDensity, type Density } from "@/lib/storage";

/**
 * Cards or Rows for the dashboard list.
 *
 * Mounted twice in the toolbar — at the end of the filter line from 768px up,
 * and on the search line on a phone — and both read the same stored value (see
 * useDensity), so they cannot drift apart. `compact` is the phone form: icons
 * only, with the label kept for screen readers, so search keeps its width.
 */
const OPTIONS: { value: Density; label: string; icon: React.ReactNode }[] = [
  {
    value: "cards",
    label: "Cards",
    icon: (
      <svg aria-hidden width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
        <rect x="1.5" y="1.5" width="11" height="4.5" rx="1" />
        <rect x="1.5" y="8" width="11" height="4.5" rx="1" />
      </svg>
    ),
  },
  {
    value: "rows",
    label: "Rows",
    icon: (
      <svg aria-hidden width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M1.5 3h11M1.5 7h11M1.5 11h11" />
      </svg>
    ),
  },
];

export function DensityToggle({ compact = false }: { compact?: boolean }) {
  const { density, setDensity } = useDensity();

  return (
    <div
      role="group"
      aria-label="List density"
      className="inline-flex shrink-0 gap-0.5 rounded-[10px] border border-[var(--row-border)] bg-[var(--row-surface)] p-[3px]"
    >
      {OPTIONS.map((o) => {
        const active = density === o.value;
        return (
          <button
            key={o.value}
            type="button"
            aria-pressed={active}
            aria-label={compact ? o.label : undefined}
            title={`${o.label} view`}
            onClick={() => setDensity(o.value)}
            className={`tap flex items-center gap-1.5 rounded-[7px] text-meta transition-colors ${
              compact ? "px-2 py-1.5" : "px-3 py-1.5"
            } ${
              active
                ? "bg-signal font-semibold text-bg"
                : "text-[var(--row-muted)] hover:text-text"
            }`}
          >
            {o.icon}
            {compact ? null : o.label}
          </button>
        );
      })}
    </div>
  );
}
