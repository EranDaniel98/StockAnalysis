"""Pure-function pins for the analyzer_ic_report math helpers.

The full IC pipeline needs alphalens + a score panel; we don't try to
fixture that here. Instead we cover the three helpers that decide
verdicts — they're the part that can silently drift and turn a NOISE
analyzer into a MODEST one (or vice-versa) without anyone noticing.
"""

from __future__ import annotations

import math

import pytest

from scripts.analyzer_ic_report import _bonferroni, _ic_t_p, _verdict


class TestBonferroni:
    def test_caps_at_one(self):
        assert _bonferroni(0.5, 10) == 1.0

    def test_multiplies_below_one(self):
        assert _bonferroni(0.01, 6) == pytest.approx(0.06)

    def test_none_is_one(self):
        assert _bonferroni(None, 6) == 1.0

    def test_nan_is_one(self):
        assert _bonferroni(float("nan"), 6) == 1.0


class TestIcTp:
    def test_zero_ic_gives_zero_t_and_p_one(self):
        t, p = _ic_t_p(0.0, 0.05, 20)
        assert t == 0.0
        assert p == pytest.approx(1.0, abs=1e-6)

    def test_strong_signal_gives_large_t_small_p(self):
        # ic_mean=0.05, ic_std=0.05, n=26 → t = 0.05/(0.05/sqrt(26)) ≈ 5.1
        t, p = _ic_t_p(0.05, 0.05, 26)
        assert t > 4.0
        assert p < 1e-3

    def test_zero_std_gives_zero_t_and_p_one(self):
        # Refusal: when std is 0 the t-stat is undefined; we return safe
        # (t=0, p=1) so a bug doesn't accidentally upgrade a flat factor
        # to "significant".
        t, p = _ic_t_p(0.1, 0.0, 20)
        assert t == 0.0
        assert p == 1.0

    def test_n_below_three_returns_safe(self):
        t, p = _ic_t_p(0.1, 0.05, 2)
        assert t == 0.0
        assert p == 1.0


class TestVerdict:
    def test_strong_requires_both_ic_and_significance(self):
        assert _verdict(0.06, 0.01) == "STRONG"

    def test_modest_requires_ic_above_threshold_and_significance(self):
        assert _verdict(0.04, 0.01) == "MODEST"

    def test_high_ic_but_not_significant_drops_to_weak(self):
        # IC>0.05 alone is not enough — we require Bonferroni-p < 0.05
        # for STRONG/MODEST. The IC>0.01 floor still puts us at WEAK.
        assert _verdict(0.06, 0.99) == "WEAK"

    def test_low_ic_is_noise_regardless_of_p(self):
        assert _verdict(0.005, 0.001) == "NOISE"

    def test_nan_ic_is_na(self):
        assert _verdict(float("nan"), 0.01) == "NA"
