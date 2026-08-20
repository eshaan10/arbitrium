"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchHealth, queryKeys } from "@/lib/api";
import type { HealthResponse } from "@/lib/types";

const LABELS: Record<string, string> = { kalshi: "Kalshi", consensus: "Odds API" };

function age(seconds: number | null): string {
  if (seconds == null) return "never";
  if (seconds < 90) return `${seconds}s ago`;
  if (seconds < 5400) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 172_800) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86_400)}d ago`;
}

/**
 * Per-source ingest freshness and when this view was fetched, as ONE unit.
 *
 * Deliberately does NOT show a clock. An "as of" time belongs to the LIST — it
 * says when that query was fetched — and putting a wall-clock reading in a
 * freshness badge would imply the data is current as of now, which is a
 * different and stronger claim than anything measured here. The list toolbar
 * keeps its own stamp, tied to the actual fetch.
 *
 * Honest in both directions: a stale source is shown as stale, and a source on
 * a slow-but-correct schedule is not called stale merely because the gap is
 * long. The tooltip carries the interval actually in force, so a quiet schedule
 * is distinguishable from a wedged poller.
 */
function summarise(data: HealthResponse | undefined) {
  if (!data) return { tone: "loading" as const, label: "…" };
  const sources = Object.values(data.ingestion);
  const stale = sources.filter((s) => s.stale).length;
  if (stale === 0) return { tone: "ok" as const, label: "Live" };
  if (stale < sources.length) return { tone: "warn" as const, label: "Partial" };
  return { tone: "warn" as const, label: "Stale" };
}

export function StatusCluster() {
  const { data, error } = useQuery({
    queryKey: queryKeys.health(),
    queryFn: fetchHealth,
    refetchInterval: 120_000,
    staleTime: 60_000,
  });

  if (error) {
    return (
      <span
        className="label flex items-center gap-1.5 text-micro text-warn sm:text-meta"
        title="/health did not respond"
      >
        <span aria-hidden className="h-[6px] w-[6px] rounded-full bg-[var(--warn)]" />
        <span className="hidden sm:inline">API unreachable</span>
        <span className="sm:hidden">No API</span>
      </span>
    );
  }

  const summary = summarise(data);
  const colour =
    summary.tone === "ok"
      ? "var(--status-ok)"
      : summary.tone === "warn"
        ? "var(--warn)"
        : "var(--faint)";

  const detail = data
    ? Object.entries(data.ingestion)
        .map(
          ([key, f]) =>
            `${LABELS[key] ?? key}: ${f.stale ? "stale" : "fresh"}, last write ${age(
              f.age_seconds,
            )}, polls every ${Math.round(f.poll_interval_seconds / 60)}m`,
        )
        .join("\n")
    : "Checking ingest freshness…";

  return (
    <span
      className="group flex items-center gap-2 rounded-sm border border-border px-2 py-1 sm:px-2.5"
      title={detail}
    >
      <span className="flex items-center gap-1.5">
        <span
          aria-hidden
          className="h-[6px] w-[6px] rounded-full"
          style={{ background: colour }}
        />
        <span
          className="label text-micro sm:text-meta"
          style={{ color: summary.tone === "warn" ? "var(--warn)" : "var(--text-dim)" }}
        >
          {summary.label}
        </span>
      </span>

      {/* Per-source detail stays visible where there is room; the badge above
          carries the verdict everywhere else. */}
      {data ? (
        <span className="label hidden items-center gap-2 border-l border-border pl-2 text-micro text-faint lg:flex">
          {Object.entries(data.ingestion).map(([key, f]) => (
            <span key={key}>
              {LABELS[key] ?? key}{" "}
              <span style={{ color: f.stale ? "var(--warn)" : "var(--status-ok)" }}>
                {f.stale ? "stale" : "ok"}
              </span>
            </span>
          ))}
        </span>
      ) : null}
    </span>
  );
}
