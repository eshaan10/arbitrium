"""Isotonic calibration: mapping a stated probability to an observed one.

Answers "when this source says 60%, how often does it actually happen?" — the
question the whole project rests on, since the premise is that sportsbook
consensus is a better estimate than Kalshi's price.

Isotonic regression is fitted by the pool-adjacent-violators algorithm, which is
about thirty lines and exact. That is implemented here rather than adding
scikit-learn: pulling in a large numerical stack for one monotone fit would be a
poor trade, and PAVA has no tuning parameters to get wrong.

The reason ``sample.assess`` gates every call into this module: isotonic
regression is non-parametric and unpenalised, so with few points it interpolates
noise perfectly and reports flawless calibration. It is the single easiest way to
produce a confident-looking lie in this codebase, which is why fitting is refused
below a floor and the result stays labelled provisional for a whole first season.

Monotonicity is the only assumption imposed, and it is the right one: a
well-behaved forecaster that says 70% should not win LESS often than when it says
60%. Everything else is read from the data.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from arbitrium.calibration.sample import SampleVerdict, assess


@dataclass(frozen=True)
class CalibrationPoint:
    """One step of the fitted curve."""

    predicted: float
    calibrated: float
    n: int


@dataclass(frozen=True)
class IsotonicFit:
    """A fitted calibration curve, or an explicit refusal to fit one."""

    points: list[CalibrationPoint]
    verdict: SampleVerdict

    @property
    def fitted(self) -> bool:
        return bool(self.points)

    def calibrate(self, p: float) -> float | None:
        """Map a stated probability to its observed frequency.

        None when no curve was fitted — the caller must show the raw number and
        say it is uncalibrated, never silently pass the input through as though
        it had been corrected.
        """
        if not self.points:
            return None
        if p <= self.points[0].predicted:
            return self.points[0].calibrated
        if p >= self.points[-1].predicted:
            return self.points[-1].calibrated
        # Linear interpolation between adjacent steps.
        for lo, hi in zip(self.points, self.points[1:], strict=False):
            if lo.predicted <= p <= hi.predicted:
                span = hi.predicted - lo.predicted
                if span <= 0:
                    return lo.calibrated
                w = (p - lo.predicted) / span
                return lo.calibrated + w * (hi.calibrated - lo.calibrated)
        return self.points[-1].calibrated


def pool_adjacent_violators(pairs: list[tuple[float, float]]) -> list[CalibrationPoint]:
    """Exact isotonic regression by PAVA. ``pairs`` is (predicted, observed).

    Walks left to right, and whenever a block's mean would fall below its
    predecessor's — violating monotonicity — merges the two and re-averages,
    cascading backwards. The result is the unique non-decreasing least-squares
    fit.
    """
    if not pairs:
        return []
    ordered = sorted(pairs, key=lambda t: t[0])

    # Each block: [sum of observed, count, representative predicted value]
    blocks: list[list[float]] = []
    for predicted, observed in ordered:
        blocks.append([observed, 1.0, predicted])
        while len(blocks) > 1 and (blocks[-2][0] / blocks[-2][1]) > (blocks[-1][0] / blocks[-1][1]):
            last = blocks.pop()
            blocks[-1][0] += last[0]
            blocks[-1][1] += last[1]
            blocks[-1][2] = last[2]  # the block spans up to the rightmost predicted

    return [
        CalibrationPoint(predicted=b[2], calibrated=b[0] / b[1], n=int(b[1]))
        for b in blocks
    ]


def fit(pairs: list[tuple[float, bool]]) -> IsotonicFit:
    """Fit a calibration curve from (predicted probability, did it happen) pairs.

    ``pairs`` must already be ONE PER GAME. Passing both sides of a two-way market
    would double the count and make the gate — and every interval downstream —
    wrong by a factor of sqrt(2).
    """
    verdict = assess(len(pairs))
    if not verdict.may_fit_isotonic:
        return IsotonicFit(points=[], verdict=verdict)
    numeric = [(p, 1.0 if hit else 0.0) for p, hit in pairs]
    return IsotonicFit(points=pool_adjacent_violators(numeric), verdict=verdict)


@dataclass(frozen=True)
class ReliabilityBin:
    """Observed frequency within one predicted-probability band."""

    lower: float
    upper: float
    n: int
    mean_predicted: float | None
    observed_rate: float | None

    @property
    def gap(self) -> float | None:
        """Observed minus predicted. Positive = the source was under-confident."""
        if self.mean_predicted is None or self.observed_rate is None:
            return None
        return self.observed_rate - self.mean_predicted


def reliability_bins(pairs: list[tuple[float, bool]], bins: int) -> list[ReliabilityBin]:
    """Bucket predictions and compare stated to observed frequency.

    Far cruder than an isotonic fit and reportable at much smaller samples, which
    is the point: it is what /performance can honestly show during the months
    before a curve may be fitted. Empty bins are RETURNED, not dropped — a gap in
    coverage is information about where the system has never made a call.
    """
    edges = [i / bins for i in range(bins + 1)]
    out: list[ReliabilityBin] = []
    for lo, hi in zip(edges, edges[1:], strict=False):
        # Upper edge inclusive only on the final bin, so 1.0 lands somewhere.
        members = [
            (p, hit) for p, hit in pairs
            if (lo <= p < hi) or (hi == 1.0 and p == 1.0)
        ]
        if members:
            out.append(ReliabilityBin(
                lower=lo, upper=hi, n=len(members),
                mean_predicted=sum(p for p, _ in members) / len(members),
                observed_rate=sum(1 for _, hit in members if hit) / len(members),
            ))
        else:
            out.append(ReliabilityBin(lower=lo, upper=hi, n=0,
                                      mean_predicted=None, observed_rate=None))
    return out


def bootstrap_interval(
    pairs: list[tuple[float, bool]],
    statistic,
    *,
    rounds: int = 400,
    seed: int = 12345,
) -> tuple[float, float] | None:
    """Percentile bootstrap CI for any statistic over the graded pairs.

    Seeded so a reported interval is reproducible — an error bar that changes on
    every page refresh invites the reader to pick the one they like.
    """
    if len(pairs) < 2:
        return None
    rng = random.Random(seed)
    n = len(pairs)
    samples = []
    for _ in range(rounds):
        draw = [pairs[rng.randrange(n)] for _ in range(n)]
        value = statistic(draw)
        if value is not None:
            samples.append(value)
    if not samples:
        return None
    samples.sort()
    return (samples[int(0.025 * len(samples))], samples[min(len(samples) - 1, int(0.975 * len(samples)))])
