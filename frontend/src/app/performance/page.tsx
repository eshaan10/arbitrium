import { fetchPerformance } from "@/lib/api";
import { EvidenceCard } from "@/components/performance/EvidenceCard";
import { Card, EmptyState, SectionHeading } from "@/components/primitives";
import { pct } from "@/lib/format";
import type { PerformanceResponse } from "@/lib/types";

export const dynamic = "force-dynamic";

const SOURCE_COPY: Record<string, string> = {
  kalshi:
    "How often Kalshi's closing price was right. Derived from append-only snapshots plus recorded winners, so it needs nothing to have been recorded in advance.",
  consensus:
    "How often the sportsbook consensus closing price was right. This is the project's premise under test: if consensus is not the better estimate, the recommendations have no basis.",
};

const TRACK_COPY: Record<string, string> = {
  live: "A genuine prospective record — recommendations made before the game, graded after.",
  reconstructed:
    "A backtest built from stored history. Reported separately so it cannot borrow the credibility of a live record.",
};

function ClvBlock({ data }: { data: PerformanceResponse["closing_line_value"] }) {
  const entries = Object.entries(data);
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {entries.map(([origin, clv]) => (
        <Card key={origin} className="p-4">
          <h3 className="text-body font-medium capitalize text-text">{origin}</h3>
          {clv.n === 0 ? (
            <p className="mt-2 text-meta text-muted">
              No priced recommendations yet for this origin.
            </p>
          ) : (
            <div className="mt-3 flex flex-wrap gap-6">
              <div>
                <div className="text-micro uppercase tracking-[0.07em] text-muted">Mean CLV</div>
                <div
                  className={`tabular mt-1 text-display font-semibold ${
                    (clv.mean_clv ?? 0) < 0 ? "text-neg" : "text-gain"
                  }`}
                >
                  {clv.mean_clv == null ? "—" : pct(clv.mean_clv, 2)}
                </div>
              </div>
              <div>
                <div className="text-micro uppercase tracking-[0.07em] text-muted">
                  Beat the close
                </div>
                <div className="tabular mt-1 text-display text-text">
                  {clv.beat_close ?? "—"}
                  <span className="text-body text-muted"> / {clv.n}</span>
                </div>
                <div className="tabular mt-0.5 text-meta text-muted">
                  {clv.beat_rate == null ? "" : pct(clv.beat_rate, 1)}
                </div>
              </div>
            </div>
          )}
        </Card>
      ))}
    </div>
  );
}

export default async function PerformancePage() {
  let data: PerformanceResponse | null = null;
  try {
    data = await fetchPerformance();
  } catch {
    data = null;
  }

  if (!data) {
    return (
      <EmptyState title="Can't reach the backend" tone="warn">
        <code className="text-dim">/performance</code> did not respond. Check that the API is
        running.
      </EmptyState>
    );
  }

  return (
    <div className="space-y-7">
      <div>
        <h1 className="text-lede font-semibold">Performance</h1>
        <p className="mt-1.5 max-w-prose text-body leading-relaxed text-dim">
          The system grading its own accuracy, with the sample size in front of every number. Three
          separate bodies of evidence, never blended — a backtest is not a live record, and
          closing-line value is evidence about the signal rather than proof of profit.
        </p>
        <p className="mt-2 text-meta text-faint">
          Reporting floor: {data.thresholds.min_report_samples} games · curve fitting:{" "}
          {data.thresholds.min_fit_samples} · treated as trusted: {data.thresholds.trusted_samples}.
          Counted in games, not outcome rows — the two sides of a two-way market are one bet.
        </p>
      </div>

      <div>
        <SectionHeading note="Which source is the better probability estimate. This tests the premise the whole product rests on.">
          Source reliability
        </SectionHeading>
        <div className="grid gap-3 md:grid-cols-2">
          {Object.entries(data.source_reliability).map(([src, evidence]) => (
            <EvidenceCard
              key={src}
              evidence={evidence}
              title={src === "kalshi" ? "Kalshi closing price" : "Consensus closing price"}
              description={SOURCE_COPY[src] ?? evidence.label}
            />
          ))}
        </div>
      </div>

      <div>
        <SectionHeading note="What the system actually recommended, split by origin.">
          Track record
        </SectionHeading>
        <div className="grid gap-3 md:grid-cols-2">
          {Object.entries(data.track_record).map(([origin, evidence]) => (
            <EvidenceCard
              key={origin}
              evidence={evidence}
              title={`Recommendations (${origin})`}
              description={TRACK_COPY[origin] ?? evidence.label}
            />
          ))}
        </div>
      </div>

      <div>
        <SectionHeading note="Needs no outcomes at all, only price history — so it is the one signal available before enough games resolve.">
          Closing-line value
        </SectionHeading>
        <ClvBlock data={data.closing_line_value} />
      </div>

      <p className="max-w-prose text-meta leading-relaxed text-faint">{data.note}</p>
    </div>
  );
}
