"""Pure-function tests for ml/dataset.py.

The orchestrator path (``build_training_matrix``) goes through Postgres
+ Parquet so it lives in integration tests. Here we test the inner
helpers that don't need infra.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.ml.dataset import _compute_forward_return


def _price_frame(closes: list[float], tz: str | None = None) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=len(closes), freq="B", tz=tz)
    return pd.DataFrame({"Close": closes}, index=idx)


class TestComputeForwardReturn:
    def test_recovers_percent_return_over_horizon(self) -> None:
        prices = _price_frame([100.0, 101.0, 102.0, 103.0, 104.0, 105.0])
        as_of = prices.index[0]
        # Close[0]=100, Close[3]=103 → 3.0% return
        ret = _compute_forward_return(prices, as_of, horizon=3)
        assert ret is not None
        assert abs(ret - 3.0) < 1e-6

    def test_none_when_horizon_extends_past_data(self) -> None:
        prices = _price_frame([100.0, 101.0, 102.0])
        as_of = prices.index[0]
        # Only 3 rows, horizon=5 → can't reach the exit.
        assert _compute_forward_return(prices, as_of, horizon=5) is None

    def test_none_for_empty_frame(self) -> None:
        empty = pd.DataFrame({"Close": []})
        empty.index = pd.DatetimeIndex([])
        as_of = pd.Timestamp("2025-01-01")
        assert _compute_forward_return(empty, as_of, horizon=3) is None
        assert _compute_forward_return(None, as_of, horizon=3) is None

    def test_none_for_zero_or_negative_entry_price(self) -> None:
        prices = _price_frame([0.0, 1.0, 2.0, 3.0])
        as_of = prices.index[0]
        assert _compute_forward_return(prices, as_of, horizon=2) is None

    def test_normalizes_tz_aware_input(self) -> None:
        """yfinance returns tz-aware UTC indices; the snapshot pipeline
        is tz-naive. ``_compute_forward_return`` should normalize."""
        prices_aware = _price_frame([100.0, 102.0, 104.0, 106.0], tz="UTC")
        as_of_naive = pd.Timestamp("2025-01-01")  # tz-naive
        # Compare against a tz-aware as_of too — both paths should work.
        ret_a = _compute_forward_return(prices_aware, as_of_naive, horizon=2)
        ret_b = _compute_forward_return(
            prices_aware, pd.Timestamp("2025-01-01", tz="UTC"), horizon=2
        )
        assert ret_a is not None and ret_b is not None
        # 100 → 104 = +4%
        assert abs(ret_a - 4.0) < 1e-6
        assert abs(ret_b - 4.0) < 1e-6

    def test_uses_first_available_row_when_as_of_predates_history(self) -> None:
        """When as_of is before the first price bar, the function should
        still resolve to the earliest row (slice with >=) and compute
        from there. That matches the snapshot job's semantics — it
        never asks for a return earlier than the data starts."""
        prices = _price_frame([100.0, 101.0, 102.0, 103.0])
        as_of = pd.Timestamp("2024-06-01")  # well before the price series
        ret = _compute_forward_return(prices, as_of, horizon=2)
        assert ret is not None
        # First close 100 → close[2]=102 → 2.0%
        assert abs(ret - 2.0) < 1e-6
