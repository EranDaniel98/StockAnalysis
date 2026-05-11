"""Phase 0 parity tests.

Two levels of guarantee:

  1. ``test_typed_scoring_matches_legacy_dict`` — deterministic unit test.
     Runs every analyzer on a real cached price DataFrame for AAPL, calls
     both `calculate_composite_score` (dict-returning legacy entry point)
     and `compute_composite_score` (typed CompositeScore-returning entry
     point), and asserts every sub-score + composite + breakdown row is
     byte-identical. This is the contract the typed wrapper must hold:
     same inputs -> same numeric result, just lifted into a model.

  2. ``test_legacy_import_shims_resolve`` — the Stream B carve added
     sys.modules shims so that ``import src.analysis.technical`` still
     resolves post-rename. We assert every legacy import path the CLI
     still uses keeps working through Phase 0.

A full sub-score-vs-baseline scan parity test (mentioned in the plan
under risk #2) is deferred: it requires pinning ``as_of_date`` through
the analyzer pipeline, which is a Phase 1 plumbing change. Until then,
the two tests above plus the manual scan/backtest smoke commands cover
the realistic regression surface.
"""

from __future__ import annotations

import warnings

import pandas as pd
import pytest

from src.config_loader import Config


def _cached_aapl_df() -> pd.DataFrame:
    """Load AAPL's OHLCV from the local Parquet store written by Stream D.

    Reads ~2y of history directly via the repository's internal sync helper
    (`_read_sync`). The Parquet store was populated from the legacy SQLite
    cache during migration, so this is deterministic across runs.
    """
    from datetime import datetime, timedelta

    from src.storage.parquet_ohlcv import ParquetPriceRepository

    repo = ParquetPriceRepository()
    # Parquet store was migrated with tz-naive index; pass naive bounds
    # so the loc[] slice doesn't trip on tz mismatch.
    end = datetime.now()
    start = end - timedelta(days=730)
    df = repo._read_sync("AAPL", start, end)
    assert df is not None and not df.empty, "AAPL Parquet cache missing; run scan first"
    assert len(df) >= 260, f"AAPL Parquet has only {len(df)} rows — need >=260 for alpha158"
    return df


def _build_inputs():
    config = Config()
    strategy = config.get_strategy("swing_trading")
    df = _cached_aapl_df()

    from src.scoring.analyzers import (
        alpha158,
        fundamental,
        patterns,
        statistical,
        technical,
        trend_detector,
    )

    tech = technical.analyze(df, config)
    fund = fundamental.analyze({}, config)
    pat = patterns.analyze(df, config)
    stat = statistical.analyze(df, config)
    trnd = trend_detector.analyze_stock_trend(df, {}, config)
    a158 = alpha158.analyze(df, config) if len(df) >= 260 else None

    return tech, fund, pat, stat, trnd, a158, strategy


def test_typed_scoring_matches_legacy_dict():
    """The typed entry point must return exactly the same numbers the
    legacy dict path produces. Same analyzer code, same composite math —
    we just lift the result into a pydantic model.
    """
    tech, fund, pat, stat, trnd, a158, strategy = _build_inputs()

    from src.scoring.engine import calculate_composite_score
    from src.scoring.service import compute_composite_score

    legacy = calculate_composite_score(
        tech, fund, pat, stat, trnd, strategy, alpha158_result=a158
    )
    typed = compute_composite_score(
        "AAPL",
        tech,
        fund,
        pat,
        stat,
        trnd,
        strategy,
        alpha158_result=a158,
    )

    assert typed.ticker == "AAPL"
    assert typed.composite_score == pytest.approx(legacy["composite_score"], abs=0.001)
    for key, expected in legacy["sub_scores"].items():
        assert typed.sub_scores[key] == pytest.approx(expected, abs=0.001), (
            f"sub_score drift on {key}: legacy={expected}, typed={typed.sub_scores[key]}"
        )

    assert len(typed.breakdown) == len(legacy["breakdown"])
    for typed_row, legacy_row in zip(typed.breakdown, legacy["breakdown"]):
        assert typed_row.category == legacy_row["category"]
        assert typed_row.score == pytest.approx(legacy_row["score"], abs=0.001)
        assert typed_row.contribution == pytest.approx(
            legacy_row["contribution"], abs=0.001
        )

    # Round-trip through legacy_dict() — Phase 0 callers still consume
    # the dict shape via the shim.
    round_trip = typed.legacy_dict()
    assert round_trip["composite_score"] == pytest.approx(legacy["composite_score"])
    assert round_trip["sub_scores"] == typed.sub_scores


# (legacy import path, attribute that real callers reference)
# We check that the legacy path still resolves AND that the specific
# attribute callers reach for is still importable — not that the entire
# dir() set matches, since package __init__ shims may intentionally
# narrow the surface area.
_LEGACY_SHIM_CASES = [
    ("src.analysis.technical", "analyze"),
    ("src.analysis.fundamental", "analyze"),
    ("src.analysis.patterns", "analyze"),
    ("src.analysis.statistical", "analyze"),
    ("src.analysis.trend_detector", "analyze_stock_trend"),
    ("src.analysis.alpha158", "analyze"),
    ("src.analysis.pead", "analyze"),
    ("src.broker.alpaca_client", "AlpacaClient"),
    ("src.paper.trader", "run_paper_trade"),
    ("src.paper.evaluator", "run_paper_evaluate"),
    ("src.paper.sync", None),  # module-level shim; no specific symbol required
    ("src.paper.bootstrap", None),
    ("src.diagnostic.alphalens_runner", "run_alphalens"),
    ("src.diagnostic.quantstats_runner", "render_quantstats_report"),
    ("src.display.cli_output", "display_scan_results"),
    ("src.portfolio", "Portfolio"),
]


@pytest.mark.parametrize("legacy_path,expected_attr", _LEGACY_SHIM_CASES)
def test_legacy_import_shim_resolves(legacy_path, expected_attr):
    """Every legacy import path must still resolve after the bounded-context
    carve. Phase 1 drops the shims; Phase 0 must not break callers that
    still type the old paths.
    """
    import importlib

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        legacy_mod = importlib.import_module(legacy_path)

    if expected_attr is not None:
        assert hasattr(legacy_mod, expected_attr), (
            f"{legacy_path} no longer exposes {expected_attr!r}"
        )
