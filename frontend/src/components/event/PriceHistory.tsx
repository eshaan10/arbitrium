"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { EventHistory, HistoryPoint } from "@/lib/types";

const KALSHI = "var(--series-kalshi)";
const CONSENSUS = "var(--series-consensus)";

interface Row {
  t: number;
  kalshi?: number;
  consensus?: number;
}

/**
 * Merge the two sources onto one time axis.
 *
 * They are polled independently and the dedup trigger only records genuine
 * price CHANGES, so the two series almost never share timestamps. Gaps are
 * left as holes and bridged with connectNulls — a step-interpolated line would
 * invent observations that were never recorded.
 */
function merge(history: EventHistory, team: string | null): Row[] {
  const byTime = new Map<number, Row>();

  const add = (points: HistoryPoint[], key: "kalshi" | "consensus") => {
    for (const p of points) {
      const t = new Date(p.t).getTime();
      const row = byTime.get(t) ?? { t };
      row[key] = p.p;
      byTime.set(t, row);
    }
  };

  for (const s of history.series) {
    if (s.team !== team) continue;
    add(s.points, s.source === "kalshi" ? "kalshi" : "consensus");
  }

  return [...byTime.values()].sort((a, b) => a.t - b.t);
}

function TooltipBody({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: { dataKey?: string | number; value?: number }[];
  label?: string | number;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border border-border-lit bg-surface px-2.5 py-2 shadow-[var(--shadow-panel)]">
      <div className="text-micro text-muted">
        {new Date(Number(label)).toLocaleString(undefined, {
          month: "short",
          day: "numeric",
          hour: "numeric",
          minute: "2-digit",
        })}
      </div>
      {payload.map((p) => (
        <div key={String(p.dataKey)} className="mt-1 flex items-center gap-2">
          <span
            aria-hidden
            className="h-2 w-2 rounded-full"
            style={{ background: p.dataKey === "kalshi" ? KALSHI : CONSENSUS }}
          />
          <span className="text-meta text-dim">
            {p.dataKey === "kalshi" ? "Kalshi" : "Consensus"}
          </span>
          <span className="tabular ml-auto text-meta text-text">
            {p.value == null ? "—" : `${(p.value * 100).toFixed(1)}%`}
          </span>
        </div>
      ))}
    </div>
  );
}

export function PriceHistory({
  history,
  team,
}: {
  history: EventHistory;
  team: string | null;
}) {
  const rows = merge(history, team);
  const recorded = rows.length;

  // Per-source counts, because the two sources are recorded at wildly
  // different rates: Kalshi ticks all day while the odds feed often has a
  // single stored observation. A one-point series draws no line segment, so it
  // MUST be drawn as a dot — otherwise the legend advertises a series that is
  // invisible on the chart, which reads as missing data rather than a market
  // that has only been priced once.
  const kalshiPoints = rows.filter((r) => r.kalshi != null).length;
  const consensusPoints = rows.filter((r) => r.consensus != null).length;

  if (recorded < 2) {
    return (
      <p className="text-meta leading-relaxed text-muted">
        {recorded === 1
          ? "One observation recorded — the price has not moved since. Only genuine price changes are stored, so a short series means a quiet market, not missing data."
          : "No price history recorded yet for this outcome."}
      </p>
    );
  }

  return (
    <div>
      {/* Legend is present because there are two series; each line is also
          named in the tooltip, so identity never rests on colour alone. */}
      <div className="mb-2 flex flex-wrap items-center gap-4">
        {[
          { label: "Kalshi", color: KALSHI, n: kalshiPoints },
          { label: "Sportsbook consensus", color: CONSENSUS, n: consensusPoints },
        ]
          .filter((s) => s.n > 0)
          .map((s) => (
            <span key={s.label} className="flex items-center gap-1.5">
              <span
                aria-hidden
                className="h-[2px] w-4 rounded-full"
                style={{ background: s.color }}
              />
              <span className="text-micro text-muted">
                {s.label}
                <span className="text-faint">
                  {" "}
                  · {s.n} {s.n === 1 ? "observation" : "points"}
                </span>
              </span>
            </span>
          ))}
      </div>

      <div className="h-[180px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 4, right: 8, bottom: 0, left: -8 }}>
            <CartesianGrid stroke="var(--series-grid)" vertical={false} />
            <XAxis
              dataKey="t"
              type="number"
              domain={["dataMin", "dataMax"]}
              scale="time"
              tickFormatter={(t) =>
                new Date(t).toLocaleDateString(undefined, { month: "short", day: "numeric" })
              }
              tick={{ fill: "var(--muted)", fontSize: 10 }}
              stroke="var(--border)"
              tickLine={false}
            />
            <YAxis
              tickFormatter={(v) => `${Math.round(v * 100)}%`}
              tick={{ fill: "var(--muted)", fontSize: 10 }}
              stroke="var(--border)"
              tickLine={false}
              width={44}
              domain={["auto", "auto"]}
            />
            <Tooltip content={<TooltipBody />} cursor={{ stroke: "var(--border-lit)" }} />
            <Line
              type="monotone"
              dataKey="kalshi"
              stroke={KALSHI}
              strokeWidth={2}
              dot={kalshiPoints === 1 ? { r: 3.5, fill: KALSHI } : false}
              activeDot={{ r: 4 }}
              connectNulls
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="consensus"
              stroke={CONSENSUS}
              strokeWidth={2}
              dot={consensusPoints === 1 ? { r: 3.5, fill: CONSENSUS } : false}
              activeDot={{ r: 4 }}
              connectNulls
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <p className="mt-1.5 text-micro text-faint">
        Only genuine price changes are stored, so a flat line means the price held.
        {consensusPoints === 1
          ? " The consensus has been recorded once so far — it is a single point, not a trend."
          : ""}
      </p>
    </div>
  );
}
