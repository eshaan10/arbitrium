import type { ReactNode } from "react";

/**
 * A row of headline numbers that line up with each other.
 *
 * Each stat spans the group's three rows through a subgrid, so labels share a
 * top edge, values share a baseline whatever their size, and footnotes share a
 * row — even when one stat has no footnote at all.
 */
export function StatGroup({ children }: { children: ReactNode }) {
  return (
    <dl className="grid auto-cols-max grid-flow-col grid-rows-[auto_auto_auto] justify-start gap-x-8">
      {children}
    </dl>
  );
}

export function Stat({
  label,
  value,
  note,
  valueClassName = "text-display font-semibold text-text",
}: {
  label: string;
  value: ReactNode;
  note?: ReactNode;
  valueClassName?: string;
}) {
  return (
    <div className="row-span-3 grid grid-rows-subgrid">
      <dt className="text-micro text-muted">{label}</dt>
      <dd className={`tabular mt-1 self-baseline ${valueClassName}`}>{value}</dd>
      <dd className="tabular mt-1 text-meta text-muted">{note}</dd>
    </div>
  );
}
