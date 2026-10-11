import { Badge, Card } from "@/components/primitives";
import { pct } from "@/lib/format";
import { ReliabilityPlot, CalibrationCurve } from "./CalibrationChart";
import { Stat, StatGroup } from "./Stat";
import type { GatedEvidence } from "@/lib/types";

/**
 * One body of evidence, with its sample gate in front of every number.
 *
 * The UI does not decide when a number is trustworthy — the API withholds the
 * rate below its floor and this renders whatever verdict came back. When
 * `accuracy` is null there is genuinely nothing to show, and the sample count
 * plus the reason IS the honest answer, not a placeholder for one.
 */
export function EvidenceCard({
  evidence,
  title,
  description,
}: {
  evidence: GatedEvidence;
  title: string;
  description: string;
}) {
  const e = evidence;
  const hasRate = e.accuracy != null;

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-body font-medium text-text">{title}</h3>
          <p className="prose mt-1 max-w-prose text-meta leading-relaxed text-muted">{description}</p>
        </div>
        <Badge tone={hasRate ? "signal" : "warn"}>
          {e.n} {e.n === 1 ? "game" : "games"}
        </Badge>
      </div>

      {hasRate ? (
        <>
          <div className="mt-4">
            <StatGroup>
              <Stat
                label="Accuracy"
                value={pct(e.accuracy, 1)}
                note={
                  e.accuracy_95ci
                    ? `95% CI ${pct(e.accuracy_95ci[0], 1)} – ${pct(e.accuracy_95ci[1], 1)}`
                    : null
                }
              />
              <Stat
                label="Brier score"
                value={e.brier_score?.toFixed(4) ?? "—"}
                valueClassName="text-headline font-medium text-text"
                note="lower is better"
              />
            </StatGroup>
          </div>

          {e.reliability_bins.length > 0 ? (
            <div className="mt-4">
              <ReliabilityPlot bins={e.reliability_bins} />
            </div>
          ) : null}

          {e.calibration_curve && e.calibration_curve.length > 1 ? (
            <div className="mt-5 border-t border-border pt-4">
              <h4 className="mb-2 text-micro text-muted">
                Fitted calibration curve
              </h4>
              <CalibrationCurve points={e.calibration_curve} />
            </div>
          ) : null}
        </>
      ) : (
        <div className="mt-3 rounded-md border border-dashed border-border bg-[var(--surface-sunken)] p-3">
          <p className="prose text-meta leading-relaxed text-dim">
            {e.reason ?? "Not enough resolved games to report a rate yet."}
          </p>
          <p className="mt-1.5 text-meta text-faint">
            The rate is withheld entirely rather than shown with a caveat — a number that exists
            gets quoted regardless of the words next to it.
          </p>
        </div>
      )}
    </Card>
  );
}
