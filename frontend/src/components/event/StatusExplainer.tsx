import { Badge } from "@/components/primitives";
import { STATUS_LABEL, unscoreableReason } from "@/lib/copy";
import type { Divergence } from "@/lib/types";

/** Status badge. Unscoreable is a fact about coverage, not a defect to hide. */
export function StatusBadge({ d }: { d: Divergence }) {
  if (d.status === "scored") return null;
  const tone = d.status === "incomparable_outcomes" ? "warn" : "muted";
  return (
    <Badge tone={tone} title={d.reason ?? undefined}>
      {STATUS_LABEL[d.status]}
    </Badge>
  );
}

/**
 * The long-form "why there are no numbers here" block for the detail view.
 * An event we cannot score still gets an explanation — silence would let the
 * reader assume the game does not exist.
 */
export function StatusExplainer({ d, minBooks }: { d: Divergence; minBooks: number }) {
  const reason = unscoreableReason(d, minBooks);
  if (!reason) return null;

  return (
    <div className="rounded-md border border-border bg-[var(--surface-sunken)] p-4">
      <h3 className="label text-meta font-semibold text-warn">
        Why there are no numbers here
      </h3>
      <p className="prose mt-2 max-w-prose text-body text-dim">{reason}</p>
      {d.reason ? (
        <p className="mt-2 text-meta text-faint">Engine reason: {d.reason}</p>
      ) : null}
    </div>
  );
}
