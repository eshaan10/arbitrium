"""Calibration: the sample gate, the isotonic fit, and closing-line value.

The gate is the most important thing here. This system starts at n=1 and a full
NFL season is only ~290 games, so almost every test below is about REFUSING to
report rather than about reporting.
"""

from __future__ import annotations

import random

from marketedge.calibration.model import (
    bootstrap_interval,
    fit,
    pool_adjacent_violators,
    reliability_bins,
)
from marketedge.calibration.sample import (
    CalibrationStatus,
    assess,
    brier_score,
    wilson_interval,
)
from marketedge.config import settings

MIN_REPORT = settings.calibration_min_report_samples
MIN_FIT = settings.calibration_min_fit_samples
TRUSTED = settings.calibration_trusted_samples


def _pairs(n, p=0.5, seed=1):
    rng = random.Random(seed)
    return [(p, rng.random() < p) for _ in range(n)]


# --- the gate ----------------------------------------------------------------


def test_a_sample_of_one_permits_nothing():
    """The state this system is actually in today."""
    v = assess(1)
    assert v.status is CalibrationStatus.INSUFFICIENT
    assert not v.may_report_rate and not v.may_fit_isotonic


def test_report_floor_is_a_boundary_not_a_range():
    assert not assess(MIN_REPORT - 1).may_report_rate
    assert assess(MIN_REPORT).may_report_rate


def test_fit_floor_is_a_boundary_not_a_range():
    assert not assess(MIN_FIT - 1).may_fit_isotonic
    assert assess(MIN_FIT).may_fit_isotonic


def test_a_full_season_is_still_only_provisional():
    """~290 games is a whole NFL season and must not read as established."""
    v = assess(290)
    assert v.may_fit_isotonic
    assert v.status is CalibrationStatus.PROVISIONAL
    assert not v.is_trustworthy


def test_established_requires_multi_season_evidence():
    assert assess(TRUSTED).status is CalibrationStatus.ESTABLISHED


# --- intervals and scores ----------------------------------------------------


def test_wilson_stays_inside_zero_one_at_the_extremes():
    """Where the normal approximation would run past the bounds."""
    lo, hi = wilson_interval(10, 10)
    assert 0.0 <= lo <= hi <= 1.0
    lo, hi = wilson_interval(0, 10)
    assert 0.0 <= lo <= hi <= 1.0


def test_wilson_narrows_as_evidence_grows():
    small = wilson_interval(7, 10)
    large = wilson_interval(700, 1000)
    assert (large[1] - large[0]) < (small[1] - small[0])


def test_no_interval_over_no_data():
    """Zero observations is not a wide interval; it is no interval."""
    assert wilson_interval(0, 0) is None


def test_brier_rewards_confident_correctness():
    assert brier_score([(1.0, True), (0.0, False)]) == 0.0
    assert brier_score([(0.5, True), (0.5, False)]) == 0.25
    assert brier_score([(1.0, False)]) == 1.0
    assert brier_score([]) is None


# --- isotonic ----------------------------------------------------------------


def test_pava_output_is_non_decreasing():
    pts = pool_adjacent_violators([(0.1, 0.0), (0.2, 1.0), (0.3, 0.0), (0.4, 1.0)])
    vals = [p.calibrated for p in pts]
    assert vals == sorted(vals)


def test_pava_pools_a_violation_rather_than_inverting():
    """0.2 -> hit then 0.3 -> miss violates monotonicity; the pair must merge."""
    pts = pool_adjacent_violators([(0.2, 1.0), (0.3, 0.0)])
    assert len(pts) == 1
    assert pts[0].calibrated == 0.5
    assert pts[0].n == 2


def test_pava_leaves_already_monotone_data_alone():
    pts = pool_adjacent_violators([(0.1, 0.0), (0.5, 0.5), (0.9, 1.0)])
    assert [p.calibrated for p in pts] == [0.0, 0.5, 1.0]


def test_fit_is_refused_below_the_floor():
    f = fit(_pairs(MIN_FIT - 1))
    assert not f.fitted
    assert f.verdict.status is not CalibrationStatus.ESTABLISHED


def test_an_unfitted_curve_returns_none_never_the_input():
    """Silently passing the raw probability through would be the dangerous bug:
    the caller could not tell corrected from uncorrected."""
    f = fit(_pairs(5))
    assert f.calibrate(0.6) is None


def test_fit_recovers_a_known_bias():
    """A source that says 0.5 but wins 0.8 of the time should calibrate upward."""
    pairs = [(0.5, i < 80) for i in range(100)] + [(0.9, i < 90) for i in range(100)]
    f = fit(pairs)
    assert f.fitted
    calibrated = f.calibrate(0.5)
    assert calibrated > 0.7, f"expected upward correction, got {calibrated}"


def test_calibrate_is_monotone_across_the_range():
    pairs = [(i / 200, (i / 200) > random.Random(i).random()) for i in range(MIN_FIT + 50)]
    f = fit(pairs)
    if f.fitted:
        vals = [f.calibrate(x / 20) for x in range(21)]
        assert all(a <= b + 1e-9 for a, b in zip(vals, vals[1:]))


# --- reliability bins --------------------------------------------------------


def test_empty_bins_are_reported_not_dropped():
    """A gap in coverage is information about where no call was ever made."""
    bins = reliability_bins([(0.05, True), (0.95, False)], 5)
    assert len(bins) == 5
    assert sum(1 for b in bins if b.n == 0) == 3


def test_bin_gap_shows_direction_of_miscalibration():
    bins = reliability_bins([(0.5, True), (0.5, True), (0.5, True), (0.5, False)], 5)
    mid = [b for b in bins if b.n][0]
    assert mid.observed_rate == 0.75
    assert mid.gap > 0  # under-confident: happened more often than stated


def test_probability_of_one_lands_in_the_final_bin():
    bins = reliability_bins([(1.0, True)], 5)
    assert bins[-1].n == 1


# --- bootstrap ---------------------------------------------------------------


def test_bootstrap_is_reproducible():
    pairs = _pairs(100, 0.6)
    stat = lambda ps: sum(1 for _, h in ps if h) / len(ps)  # noqa: E731
    assert bootstrap_interval(pairs, stat) == bootstrap_interval(pairs, stat)


def test_bootstrap_needs_more_than_one_point():
    assert bootstrap_interval([(0.5, True)], lambda ps: 0.5) is None
