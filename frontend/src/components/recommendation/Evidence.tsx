"use client";

import { confidence } from "@/lib/confidence";
import { whySimple } from "@/lib/copy";
import { cents } from "@/lib/format";
import { InfoPopover } from "@/components/primitives/InfoPopover";
import type { Divergence } from "@/lib/types";

/**
 * The evidence line: one row of real numbers, with the full sentence behind a
 * disclosure.
 *
 * The sentence used to sit on every card as four lines of 13px prose, taking
 * more area than the recommendation it was explaining — so the card's largest
 * element was its justification rather than its conclusion. Nothing is removed:
 * the same sentence, from the same source, is one click away, and the numbers
 * it quotes are now visible without opening it.
 */
function Bar({ filled }: { filled: number }) {
  return (
    <span aria-hidden className="flex items-end gap-[2px]">
      {[1, 2, 3, 4].map((i) => (
        <i
          key={i}
          style={{ height: `${3 + i * 2}px` }}
          className={`w-[3px] rounded-[1px] ${
            i <= filled ? "bg-signal" : "bg-[var(--border-lit)]"
          }`}
        />
      ))}
    </span>
  );
}

export function Evidence({ d, minBooks }: { d: Divergence; minBooks: number }) {
  const r = d.recommendation;
  const conf = confidence(d, minBooks);
  const segments = whySimple(d, minBooks);

  return (
    <div>
      {r ? (
        <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-meta text-muted">
          <span>
            Books say{" "}
            <span className="tabular text-dim">{cents(r.fair_value)}</span>
          </span>
          <span aria-hidden className="text-faint">
            ·
          </span>
          <span className="flex items-center gap-1">
            <span className="tabular text-dim">{d.n_books ?? 0}</span> books
            <InfoPopover term="books" />
          </span>
          <span aria-hidden className="text-faint">
            ·
          </span>
          <span className="flex items-center gap-1.5">
            <Bar filled={conf.bars} />
            <span className="text-dim">{conf.label}</span>
            <InfoPopover term="confidence" />
          </span>
        </div>
      ) : null}

      <details className="why group mt-1.5">
        <summary className="relative z-20 inline-flex items-center gap-1 text-meta text-faint hover:text-muted">
          <span aria-hidden className="why-chevron inline-block">
            ›
          </span>
          Why this?
        </summary>
        <p className="mt-1.5 max-w-[58ch] border-l border-border pl-3 text-body text-dim">
          {segments.map((s, i) =>
            typeof s === "string" ? (
              <span key={i}>{s}</span>
            ) : (
              <em key={i} className="font-medium not-italic text-text">
                {s.em}
              </em>
            ),
          )}
        </p>
      </details>
    </div>
  );
}
