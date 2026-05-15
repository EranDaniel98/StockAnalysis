"""Tests for analyzer_correlation._flag_redundant.

A silent bug in this helper would either hide a real redundancy
(operator misses it, weights stay inflated) or invent fake ones
(operator wastes time investigating noise). Pin the contract.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.analyzer_correlation import _flag_redundant


def _matrix(d: dict[tuple[str, str], float], cols: list[str]) -> pd.DataFrame:
    n = len(cols)
    arr = np.full((n, n), np.nan)
    for i, a in enumerate(cols):
        for j, b in enumerate(cols):
            if a == b:
                arr[i, j] = 1.0
            elif (a, b) in d:
                arr[i, j] = d[(a, b)]
            elif (b, a) in d:
                arr[i, j] = d[(b, a)]
    return pd.DataFrame(arr, index=cols, columns=cols)


def test_returns_empty_when_no_pair_above_threshold():
    cols = ["a", "b", "c"]
    m = _matrix({("a", "b"): 0.3, ("a", "c"): 0.5, ("b", "c"): 0.69}, cols)
    assert _flag_redundant(m, threshold=0.7) == []


def test_returns_pair_at_or_above_threshold():
    cols = ["a", "b", "c"]
    m = _matrix({("a", "b"): 0.85, ("a", "c"): 0.5, ("b", "c"): 0.2}, cols)
    out = _flag_redundant(m, threshold=0.7)
    assert out == [("a", "b", 0.85)]


def test_catches_strong_negative_correlation():
    # |corr| >= threshold — a -0.9 is "redundant" because it's the
    # same information with reversed sign, still inflates joint weight.
    cols = ["a", "b"]
    m = _matrix({("a", "b"): -0.9}, cols)
    out = _flag_redundant(m, threshold=0.7)
    assert out == [("a", "b", -0.9)]


def test_sorts_by_absolute_value_descending():
    cols = ["a", "b", "c", "d"]
    m = _matrix(
        {("a", "b"): 0.75, ("a", "c"): -0.95, ("b", "d"): 0.85,
         ("a", "d"): 0.2, ("b", "c"): 0.0, ("c", "d"): 0.0},
        cols,
    )
    out = _flag_redundant(m, threshold=0.7)
    # Expected order: 0.95, 0.85, 0.75
    abs_vals = [abs(v) for _, _, v in out]
    assert abs_vals == sorted(abs_vals, reverse=True)
    assert len(out) == 3


def test_skips_nan_entries():
    cols = ["a", "b"]
    m = _matrix({}, cols)  # off-diagonals stay NaN
    out = _flag_redundant(m, threshold=0.0)
    assert out == []


def test_does_not_double_count_pairs():
    # We only return the upper-triangular pair — (a, b) but not (b, a).
    cols = ["a", "b", "c"]
    m = _matrix({("a", "b"): 0.85, ("b", "c"): 0.80}, cols)
    out = _flag_redundant(m, threshold=0.7)
    assert len(out) == 2
    keys = {(a, b) for a, b, _ in out}
    assert ("a", "b") in keys
    assert ("b", "c") in keys
    assert ("b", "a") not in keys
    assert ("c", "b") not in keys
