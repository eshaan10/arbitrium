import type { ReactNode } from "react";

/* Small shared pieces. Kept in one file because each is a handful of lines and
   splitting them would cost more navigation than it saves. */

export function Card({
  children,
  className = "",
  style,
}: {
  children: ReactNode;
  className?: string;
  style?: React.CSSProperties;
}) {
  return (
    <div
      style={style}
      className={`rounded-lg border border-border bg-surface shadow-[var(--shadow-card)] ${className}`}
    >
      {children}
    </div>
  );
}

type Tone = "neutral" | "signal" | "warn" | "arb" | "muted";

const TONES: Record<Tone, string> = {
  neutral: "border-border-lit text-dim",
  signal: "border-signal-800 text-signal-600 bg-[var(--signal-950)]",
  warn: "border-[color-mix(in_srgb,var(--warn)_40%,transparent)] text-warn",
  arb: "border-arb text-arb bg-[var(--arb-glow)]",
  muted: "border-border text-muted",
};

export function Badge({
  children,
  tone = "neutral",
  title,
}: {
  children: ReactNode;
  tone?: Tone;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-[3px] text-micro font-medium leading-none tracking-[0.01em] ${TONES[tone]}`}
    >
      {children}
    </span>
  );
}

/**
 * Confidence as four discrete bars plus a word. The word is not optional: the
 * bars alone would encode the whole signal in shape, and this app never lets a
 * caveat live only in a visual channel.
 */
export function ConfidenceBars({ bars, label }: { bars: number; label: string }) {
  if (!bars) return null;
  return (
    <span className="inline-flex items-center gap-2" title={`${label} confidence`}>
      <span aria-hidden className="flex items-end gap-[2px]">
        {[1, 2, 3, 4].map((i) => (
          <i
            key={i}
            style={{ height: `${4 + i * 2}px` }}
            className={`w-[3px] rounded-[1px] ${i <= bars ? "bg-signal" : "bg-[var(--border-lit)]"}`}
          />
        ))}
      </span>
      <span className="text-micro text-muted">{label} confidence</span>
    </span>
  );
}

export function Metric({
  label,
  value,
  negative = false,
  title,
}: {
  label: string;
  value: string;
  negative?: boolean;
  title?: string;
}) {
  const missing = value === "—";
  return (
    <div title={title} className="min-w-0">
      <div className="text-micro uppercase tracking-[0.07em] text-muted">{label}</div>
      <div
        className={`tabular mt-[3px] text-body ${
          missing ? "text-faint" : negative ? "text-neg" : "text-text"
        }`}
      >
        {value}
      </div>
    </div>
  );
}

export function SectionHeading({ children, note }: { children: ReactNode; note?: string }) {
  return (
    <div className="mb-3">
      <h3 className="text-meta font-semibold uppercase tracking-[0.08em] text-dim">{children}</h3>
      {note ? <p className="mt-1 text-meta leading-relaxed text-muted">{note}</p> : null}
    </div>
  );
}

export function EmptyState({
  title,
  children,
  tone = "neutral",
}: {
  title: string;
  children?: ReactNode;
  tone?: "neutral" | "warn";
}) {
  return (
    <div className="rounded-lg border border-dashed border-border bg-[var(--surface-sunken)] px-6 py-10 text-center">
      <p className={`text-title font-medium ${tone === "warn" ? "text-warn" : "text-dim"}`}>
        {title}
      </p>
      {children ? (
        <div className="mx-auto mt-2 max-w-prose text-body leading-relaxed text-muted">
          {children}
        </div>
      ) : null}
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div
      className={`animate-pulse rounded-sm bg-[var(--surface-raised)] ${className}`}
    />
  );
}
