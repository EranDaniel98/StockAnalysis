"""Round-trip + immutability tests for src.storage.snapshot.

The keystone property we're testing: write_snapshot then load_snapshot
returns engine-shaped inputs that are functionally identical to what
the live fetcher path would have produced. Any drift here turns the
non-determinism fix into a different kind of non-determinism.

Also pinned:
  * Same input data → same snapshot id (content addressing works)
  * Mutating a snapshot file on disk → load_snapshot raises ValueError
  * Manifest round-trips through JSON
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.storage.snapshot import (
    SnapshotManifest,
    load_snapshot,
    write_snapshot,
)


def _make_price_frame(
    start: str = "2022-01-03", days: int = 100, seed: int = 0,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start=start, periods=days)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.015, days)))
    return pd.DataFrame({
        "Open": close * 0.995,
        "High": close * 1.01,
        "Low": close * 0.99,
        "Close": close,
        "Volume": rng.integers(1_000_000, 10_000_000, days),
    }, index=idx)


@pytest.fixture
def snapshot_dir(tmp_path):
    return tmp_path / "snapshots"


@pytest.fixture
def sample_inputs():
    price_data = {
        "AAPL": _make_price_frame(seed=1),
        "MSFT": _make_price_frame(seed=2),
        "NVDA": _make_price_frame(seed=3),
    }
    fundamentals = {
        "AAPL": {"market_cap": 3.0e12, "pe_ratio": 28.5, "revenue_growth": 0.08},
        "MSFT": {"market_cap": 2.8e12, "pe_ratio": 32.0, "revenue_growth": 0.12},
        "NVDA": {"market_cap": 2.0e12, "pe_ratio": 50.0, "revenue_growth": 0.30},
    }
    # Engine convention: earnings DataFrames have at least one column
    # (yfinance returns 'EPS Estimate', 'Reported EPS', 'Surprise(%)').
    # A zero-column frame is df.empty == True and would be filtered out.
    earnings_history = {
        "AAPL": pd.DataFrame(
            {"EPS Estimate": [1.0, 1.1, 1.2, 1.3]},
            index=pd.to_datetime(
                ["2022-01-27", "2022-04-28", "2022-07-28", "2022-10-27"]),
        ),
        "MSFT": pd.DataFrame(
            {"EPS Estimate": [2.0, 2.1, 2.2, 2.3]},
            index=pd.to_datetime(
                ["2022-01-25", "2022-04-26", "2022-07-26", "2022-10-25"]),
        ),
    }
    spy_df = _make_price_frame(seed=100)
    vix_df = _make_price_frame(seed=101)
    return dict(
        price_data=price_data, fundamentals=fundamentals,
        earnings_history=earnings_history, spy_df=spy_df, vix_df=vix_df,
    )


def test_round_trip_preserves_prices(snapshot_dir, sample_inputs):
    mf = write_snapshot(
        **sample_inputs,
        universe_label="test", window_start=pd.Timestamp("2022-01-03"),
        window_end=pd.Timestamp("2022-05-30"),
        pipeline_version="test-v1",
        root=snapshot_dir,
    )
    loaded = load_snapshot(mf.snapshot_id, root=snapshot_dir)

    # Every ticker present
    assert set(loaded.price_data.keys()) == set(sample_inputs["price_data"].keys())
    for ticker, orig in sample_inputs["price_data"].items():
        got = loaded.price_data[ticker]
        # Index dates round-trip
        assert list(got.index) == list(orig.index), f"{ticker} index drift"
        # Close prices round-trip exactly
        np.testing.assert_allclose(
            got["Close"].values, orig["Close"].values, rtol=1e-9,
            err_msg=f"{ticker} Close drift",
        )


def test_round_trip_preserves_spy_and_vix(snapshot_dir, sample_inputs):
    mf = write_snapshot(
        **sample_inputs,
        universe_label="test", window_start=pd.Timestamp("2022-01-03"),
        window_end=pd.Timestamp("2022-05-30"),
        pipeline_version="test-v1",
        root=snapshot_dir,
    )
    loaded = load_snapshot(mf.snapshot_id, root=snapshot_dir)
    assert loaded.spy_df is not None
    assert loaded.vix_df is not None
    np.testing.assert_allclose(
        loaded.spy_df["Close"].values,
        sample_inputs["spy_df"]["Close"].values,
        rtol=1e-9,
    )


def test_round_trip_preserves_fundamentals(snapshot_dir, sample_inputs):
    mf = write_snapshot(
        **sample_inputs,
        universe_label="test", window_start=pd.Timestamp("2022-01-03"),
        window_end=pd.Timestamp("2022-05-30"),
        pipeline_version="test-v1",
        root=snapshot_dir,
    )
    loaded = load_snapshot(mf.snapshot_id, root=snapshot_dir)
    assert loaded.fundamentals == sample_inputs["fundamentals"]


def test_round_trip_preserves_earnings_dates(snapshot_dir, sample_inputs):
    mf = write_snapshot(
        **sample_inputs,
        universe_label="test", window_start=pd.Timestamp("2022-01-03"),
        window_end=pd.Timestamp("2022-05-30"),
        pipeline_version="test-v1",
        root=snapshot_dir,
    )
    loaded = load_snapshot(mf.snapshot_id, root=snapshot_dir)
    for ticker, df in sample_inputs["earnings_history"].items():
        got = loaded.earnings_history[ticker]
        assert sorted(got.index.tolist()) == sorted(df.index.tolist())


def test_same_inputs_produce_same_snapshot_id(snapshot_dir, sample_inputs):
    """Content-addressing: two writes of identical data → same id."""
    mf1 = write_snapshot(
        **sample_inputs,
        universe_label="test", window_start=pd.Timestamp("2022-01-03"),
        window_end=pd.Timestamp("2022-05-30"),
        pipeline_version="test-v1",
        root=snapshot_dir,
    )
    # Re-write with the same inputs (different staging dir; the
    # function should detect content-hash collision and reuse the
    # existing snapshot id rather than create a duplicate).
    mf2 = write_snapshot(
        **sample_inputs,
        universe_label="test", window_start=pd.Timestamp("2022-01-03"),
        window_end=pd.Timestamp("2022-05-30"),
        pipeline_version="test-v1",
        root=snapshot_dir,
    )
    assert mf1.snapshot_id == mf2.snapshot_id


def test_different_window_produces_different_snapshot_id(snapshot_dir, sample_inputs):
    mf1 = write_snapshot(
        **sample_inputs,
        universe_label="test", window_start=pd.Timestamp("2022-01-03"),
        window_end=pd.Timestamp("2022-05-30"),
        pipeline_version="test-v1",
        root=snapshot_dir,
    )
    mf2 = write_snapshot(
        **sample_inputs,
        universe_label="test", window_start=pd.Timestamp("2022-01-03"),
        window_end=pd.Timestamp("2022-12-30"),  # different end
        pipeline_version="test-v1",
        root=snapshot_dir,
    )
    assert mf1.snapshot_id != mf2.snapshot_id


def test_tampering_with_a_file_makes_load_raise(snapshot_dir, sample_inputs):
    mf = write_snapshot(
        **sample_inputs,
        universe_label="test", window_start=pd.Timestamp("2022-01-03"),
        window_end=pd.Timestamp("2022-05-30"),
        pipeline_version="test-v1",
        root=snapshot_dir,
    )
    fund = snapshot_dir / mf.snapshot_id / "fundamentals.json"
    # Mutate the fundamentals file after snapshot creation
    fund.write_text(fund.read_text(encoding="utf-8") + "\n  ",
                    encoding="utf-8")
    with pytest.raises(ValueError, match="content hash mismatch"):
        load_snapshot(mf.snapshot_id, root=snapshot_dir)


def test_manifest_json_round_trips(snapshot_dir, sample_inputs):
    mf = write_snapshot(
        **sample_inputs,
        universe_label="test", window_start=pd.Timestamp("2022-01-03"),
        window_end=pd.Timestamp("2022-05-30"),
        pipeline_version="test-v1",
        root=snapshot_dir,
    )
    mf_path = snapshot_dir / mf.snapshot_id / "manifest.json"
    data = json.loads(mf_path.read_text(encoding="utf-8"))
    reloaded = SnapshotManifest.from_dict(data)
    assert reloaded.snapshot_id == mf.snapshot_id
    assert reloaded.window_start == mf.window_start
    assert reloaded.tickers == mf.tickers


def test_load_missing_snapshot_raises(snapshot_dir):
    with pytest.raises(FileNotFoundError):
        load_snapshot("nonexistent_id", root=snapshot_dir)
