"""Phase 0 parity test — kept past Phase 0 because the numerical
equivalence between the dict-returning legacy entry point and the typed
``CompositeScore`` entry point still has to hold.

The legacy-import-shim test that used to live here was dropped after the
Phase-2.2 polish removed those shim packages (``src.analysis``,
``src.broker``, ``src.paper``, ``src.diagnostic``, ``src.display``) — every
caller in-tree now imports from the bounded-context paths directly.

A full sub-score-vs-baseline scan parity test (mentioned in the original
plan under risk #2) is still deferred: it requires pinning ``as_of_date``
through the analyzer pipeline, which is a follow-up plumbing change.
"""

from __future__ import annotations

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


# Bounded-context modules every in-tree caller now points at. We don't
# pin the full dir() — package __init__ files may narrow the export
# surface — but each named symbol must remain importable so a future
# refactor doesn't quietly orphan a downstream caller.
_BOUNDED_CONTEXT_CASES = [
    ("src.scoring.analyzers.technical", "analyze"),
    ("src.scoring.analyzers.fundamental", "analyze"),
    ("src.scoring.analyzers.patterns", "analyze"),
    ("src.scoring.analyzers.statistical", "analyze"),
    ("src.scoring.analyzers.trend_detector", "analyze_stock_trend"),
    ("src.scoring.analyzers.alpha158", "analyze"),
    ("src.scoring.analyzers.pead", "analyze"),
    ("src.execution.alpaca", "AlpacaClient"),
    ("src.execution.paper_trade_service", "run_paper_trade"),
    ("src.execution.paper_evaluate_service", "run_paper_evaluate"),
    ("src.execution.sync_service", None),
    ("src.execution.bootstrap_service", None),
    ("src.research.diagnostic_service", "run_alphalens"),
    ("src.research.quantstats_service", "render_quantstats_report"),
    ("src.presentation.cli.cli_output", "display_scan_results"),
    ("src.portfolio", "Portfolio"),
    ("src.cli.main", "main"),
]


@pytest.mark.parametrize("module_path,expected_attr", _BOUNDED_CONTEXT_CASES)
def test_bounded_context_import_resolves(module_path, expected_attr):
    """Every bounded-context module name in-tree callers depend on must
    keep resolving. This is the post-shim replacement for the old
    legacy-shim test."""
    import importlib

    mod = importlib.import_module(module_path)
    if expected_attr is not None:
        assert hasattr(mod, expected_attr), (
            f"{module_path} no longer exposes {expected_attr!r}"
        )
