"""
Quantstats tearsheet generation.

Given a backtest's equity curve, produce a quantstats HTML tearsheet with
canonical risk-adjusted metrics, drawdowns, monthly heatmap, distribution
plots, and comparison to a benchmark (SPY by default).

This is a more comprehensive alternative to the custom HTML report — quantstats
is the de-facto retail tearsheet library.
"""

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


def render_quantstats_report(
    equity_curve: list[dict],
    output_path: str,
    benchmark_ticker: str = "SPY",
    title: str = "Backtest Tearsheet",
) -> str:
    """
    Build a quantstats HTML tearsheet from the equity_curve produced by
    run_backtest. Returns the path written.
    """
    import quantstats as qs

    if not equity_curve:
        raise ValueError("equity_curve is empty")

    df = pd.DataFrame(equity_curve)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    if "equity" not in df.columns:
        raise ValueError("equity_curve rows must contain 'equity' field")

    # quantstats expects a returns series (not equity)
    returns = df["equity"].pct_change().dropna()
    returns.name = "Strategy"

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Force the local QS adjustments to download benchmark from yfinance
    try:
        qs.reports.html(
            returns,
            benchmark=benchmark_ticker,
            output=str(out),
            title=title,
        )
    except Exception as e:
        # Fall back to no-benchmark if benchmark fetch fails
        logger.warning(f"Quantstats benchmark fetch failed ({e}); rendering without benchmark")
        qs.reports.html(returns, output=str(out), title=title)

    return str(out)
