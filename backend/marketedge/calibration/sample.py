"""How much evidence exists, and what it permits.

The gate every other calibration number passes through. It exists because this
system starts with a sample of ONE and will not clear a few hundred graded games
until deep into a season — and a calibration curve fitted to noise is worse than
no curve at all, because it looks authoritative.

Isotonic regression is the specific risk. It is non-parametric with no smoothness
constraint, so with few points it happily fits a step function straight through
random variation and reports perfect calibration. Hence a hard floor before it
may be fitted at all, and a "provisional" label that a single NFL season
(~290 games) never escapes.

ONE OBSERVATION PER GAME, NOT PER OUTCOME. In a two-way market the home and away
probabilities are perfectly anti-correlated: grading both would double the
apparent sample and shrink every interval by a factor of sqrt(2), making the
result look twice as certain as it is. Callers must deduplicate to one row per
event before asking anything here — the same "both sides are one bet" rule the
divergence engine already follows.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from marketedge.config import settings


class CalibrationStatus(str, Enum):
    INSUFFICIENT = "insufficient"  # too few to say anything at all
    PROVISIONAL = "provisional"  # reportable, but not to be trusted yet
    ESTABLISHED = "established"  # enough for the numbers to stand on their own


@dataclass(frozen=True)
class SampleVerdict:
    """What a given sample size permits. Every reported number carries one."""

    n: int
    status: CalibrationStatus
    may_report_rate: bool
    may_fit_isotonic: bool
    reason: str

    @property
    def is_trustworthy(self) -> bool:
        return self.status is CalibrationStatus.ESTABLISHED


def assess(n: int) -> SampleVerdict:
    """Judge a sample size. Pure, so the policy is testable without a database."""
    min_report = settings.calibration_min_report_samples
    min_fit = settings.calibration_min_fit_samples
    trusted = settings.calibration_trusted_samples

    if n < min_report:
        return SampleVerdict(
            n=n,
            status=CalibrationStatus.INSUFFICIENT,
            may_report_rate=False,
            may_fit_isotonic=False,
            reason=(
                f"{n} graded game(s) — below the floor of {min_report}. No rate is "
                "reported, because at this size the observed frequency is dominated "
                "by chance and would be read as a track record."
            ),
        )
    if n < min_fit:
        return SampleVerdict(
            n=n,
            status=CalibrationStatus.PROVISIONAL,
            may_report_rate=True,
            may_fit_isotonic=False,
            reason=(
                f"{n} graded games — enough for an observed rate with an interval, "
                f"but below the {min_fit} needed to fit a calibration curve. Isotonic "
                "regression on this many points would fit noise."
            ),
        )
    if n < trusted:
        return SampleVerdict(
            n=n,
            status=CalibrationStatus.PROVISIONAL,
            may_report_rate=True,
            may_fit_isotonic=True,
            reason=(
                f"{n} graded games — a curve can be fitted, but it stays PROVISIONAL "
                f"until {trusted}. A full NFL season is roughly 290 games, so a "
                "first-season curve never leaves this state; treat it as indicative."
            ),
        )
    return SampleVerdict(
        n=n,
        status=CalibrationStatus.ESTABLISHED,
        may_report_rate=True,
        may_fit_isotonic=True,
        reason=f"{n} graded games — enough for the calibration curve to stand on its own.",
    )


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """95% Wilson score interval for an observed rate.

    Wilson rather than the textbook normal approximation: at small n, or when the
    rate is near 0 or 1, the normal interval runs past [0, 1] and understates
    uncertainty exactly where this system will be spending its first season.

    Returns None when n is 0 — an interval over no data is not a wide interval,
    it is no interval.
    """
    if n <= 0:
        return None
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def brier_score(pairs: list[tuple[float, bool]]) -> float | None:
    """Mean squared error of probabilistic forecasts. Lower is better; 0.25 = coin flip.

    Reported alongside calibration because they measure different failures: a
    forecaster can be perfectly calibrated and still useless (always predicting
    the base rate), which the Brier score catches and a reliability curve does not.
    """
    if not pairs:
        return None
    return sum((p - (1.0 if outcome else 0.0)) ** 2 for p, outcome in pairs) / len(pairs)
