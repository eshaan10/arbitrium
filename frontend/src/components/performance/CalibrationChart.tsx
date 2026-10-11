"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ComposedChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import type { CalibrationPoint, ReliabilityBin } from "@/lib/types";

const OBSERVED = "var(--series-kalshi)";

/**
 * Room for every label and mark. Left is 0 because the y-axis width already
 * reserves the tick column ("100%" needs all of it). Top and right cover half
 * of the edge tick labels plus the largest scatter point (range 400 → r ≈ 11px)
 * sitting at 100%.
 */
const MARGIN = { top: 12, right: 20, bottom: 0, left: 0 };
const AXIS_TICK = { fill: "var(--muted)", fontSize: 12 };
const PERCENT = (v: number) => `${Math.round(v * 100)}%`;

/**
 * The chart gets a fixed height and the caption sits below it in normal flow.
 * Sizing a box that holds both — with the chart at 100% of it — pushed the
 * caption out of the bottom of the card.
 */
function ChartFigure({
  height,
  caption,
  children,
}: {
  height: number;
  caption: string;
  children: React.ReactElement;
}) {
  return (
    <figure className="w-full">
      <div className="w-full" style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          {children}
        </ResponsiveContainer>
      </div>
      <figcaption className="mt-3 text-micro text-faint">{caption}</figcaption>
    </figure>
  );
}

/**
 * A reliability plot: predicted probability against what actually happened.
 *
 * The diagonal is the whole point — it is perfect calibration, and a reader
 * needs it to judge whether a point is high or low. It is drawn in a recessive
 * neutral so it reads as a reference, never as a third data series.
 *
 * Point size carries bin population, so a bin resting on four games cannot
 * visually outweigh one resting on four hundred.
 */
export function ReliabilityPlot({ bins }: { bins: ReliabilityBin[] }) {
  const points = bins
    .filter((b) => b.mean_predicted != null && b.observed_rate != null)
    .map((b) => ({
      predicted: b.mean_predicted!,
      observed: b.observed_rate!,
      n: b.n,
    }));

  if (points.length === 0) return null;

  return (
    <ChartFigure
      height={220}
      caption="Dashed line is perfect calibration. Point size is the number of games in that bin."
    >
      <ComposedChart margin={MARGIN}>
        <CartesianGrid stroke="var(--series-grid)" />
        <XAxis
          type="number"
          dataKey="predicted"
          domain={[0, 1]}
          ticks={[0, 0.25, 0.5, 0.75, 1]}
          tickFormatter={PERCENT}
          tick={AXIS_TICK}
          stroke="var(--border)"
          tickLine={false}
          tickMargin={6}
          name="Predicted"
        />
        <YAxis
          type="number"
          dataKey="observed"
          domain={[0, 1]}
          ticks={[0, 0.25, 0.5, 0.75, 1]}
          tickFormatter={PERCENT}
          tick={AXIS_TICK}
          stroke="var(--border)"
          tickLine={false}
          width={44}
          tickMargin={6}
          name="Observed"
        />
        <ZAxis type="number" dataKey="n" range={[40, 400]} name="Games" />
        <ReferenceLine
          segment={[
            { x: 0, y: 0 },
            { x: 1, y: 1 },
          ]}
          stroke="var(--series-reference)"
          strokeDasharray="4 4"
          ifOverflow="extendDomain"
        />
        <Tooltip
          cursor={{ stroke: "var(--border-lit)" }}
          contentStyle={{
            background: "var(--surface)",
            border: "1px solid var(--border-lit)",
            borderRadius: 8,
            fontSize: 12,
          }}
          labelStyle={{ color: "var(--muted)" }}
          formatter={(value: unknown, name: unknown) => {
            const v = Number(value);
            const label = String(name);
            return label === "Games"
              ? [v.toLocaleString(), label]
              : [`${(v * 100).toFixed(1)}%`, label];
          }}
        />
        <Scatter data={points} fill={OBSERVED} fillOpacity={0.8} name="Observed" />
      </ComposedChart>
    </ChartFigure>
  );
}

/** The fitted isotonic curve, when the sample is large enough to fit one. */
export function CalibrationCurve({ points }: { points: CalibrationPoint[] }) {
  if (points.length < 2) return null;

  return (
    <ChartFigure
      height={220}
      caption="Raw probability in, calibrated probability out. Dashed line is no adjustment."
    >
      <LineChart data={points} margin={MARGIN}>
        <CartesianGrid stroke="var(--series-grid)" />
        <XAxis
          dataKey="predicted"
          type="number"
          domain={[0, 1]}
          ticks={[0, 0.25, 0.5, 0.75, 1]}
          tickFormatter={PERCENT}
          tick={AXIS_TICK}
          stroke="var(--border)"
          tickLine={false}
          tickMargin={6}
        />
        <YAxis
          domain={[0, 1]}
          ticks={[0, 0.25, 0.5, 0.75, 1]}
          tickFormatter={PERCENT}
          tick={AXIS_TICK}
          stroke="var(--border)"
          tickLine={false}
          width={44}
          tickMargin={6}
        />
        <ReferenceLine
          segment={[
            { x: 0, y: 0 },
            { x: 1, y: 1 },
          ]}
          stroke="var(--series-reference)"
          strokeDasharray="4 4"
        />
        <Tooltip
          contentStyle={{
            background: "var(--surface)",
            border: "1px solid var(--border-lit)",
            borderRadius: 8,
            fontSize: 12,
          }}
          formatter={(v: unknown) => `${(Number(v) * 100).toFixed(1)}%`}
        />
        <Line
          type="monotone"
          dataKey="calibrated"
          stroke={OBSERVED}
          strokeWidth={2}
          dot={{ r: 3 }}
          isAnimationActive={false}
        />
      </LineChart>
    </ChartFigure>
  );
}
