import { whySimple } from "@/lib/copy";
import type { Divergence } from "@/lib/types";

/** The plain-English explanation. Every number in it comes from the event. */
export function WhyThis({ d, minBooks }: { d: Divergence; minBooks: number }) {
  const segments = whySimple(d, minBooks);
  return (
    <p className="text-body text-dim">
      {segments.map((s, i) =>
        typeof s === "string" ? (
          <span key={i}>{s}</span>
        ) : (
          <em key={i} className="not-italic font-medium text-text">
            {s.em}
          </em>
        ),
      )}
    </p>
  );
}
