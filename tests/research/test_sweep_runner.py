"""Tests for src/research/sweep_runner.py — the shared sweep harness."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.research.sweep_runner import (
    _resolve_universe, summarize_result, write_sweep_rows,
)


def test_resolve_universe_custom_tickers_wins() -> None:
    """Custom tickers short-circuit the universe choice."""
    config = type("MockConfig", (), {})()
    tickers, label = _resolve_universe(config, "themes", ["aapl", "msft"])
    assert tickers == ["AAPL", "MSFT"]
    assert "custom" in label


def test_resolve_universe_themes_path() -> None:
    config = type("MockConfig", (), {})()
    config.get_theme_tickers = lambda: ["A", "B", "C"]
    tickers, label = _resolve_universe(config, "themes", None)
    assert tickers == ["A", "B", "C"]
    assert "themes" in label


def test_resolve_universe_watchlist_path() -> None:
    config = type("MockConfig", (), {})()
    config.get_watchlist = lambda: ["X", "Y"]
    tickers, label = _resolve_universe(config, "watchlist", None)
    assert tickers == ["X", "Y"]
    assert "watchlist" in label


def test_resolve_universe_unknown_raises() -> None:
    config = type("MockConfig", (), {})()
    with pytest.raises(ValueError, match="Unknown universe"):
        _resolve_universe(config, "imaginary", None)


def test_summarize_result_pulls_full_and_oos_metrics() -> None:
    """summarize_result reads the standard run_backtest result shape and
    returns a uniform comparison row — same keys regardless of which
    sweep called it."""
    result = {
        "full": {
            "summary": {"n_trades": 100, "total_return_pct": 12.3, "win_rate_pct": 55.0},
            "equity_stats": {"ann_sharpe": 1.2, "max_drawdown_pct": -8.7},
        },
        "out_of_sample": {
            "summary": {"n_trades": 30, "total_return_pct": 4.5, "win_rate_pct": 60.0},
            "equity_stats": {"ann_sharpe": 1.5, "max_drawdown_pct": -3.2},
        },
    }
    row = summarize_result(50.0, result)
    assert row["label"] == 50.0
    assert row["n_trades"] == 100
    assert row["n_oos_trades"] == 30
    assert row["oos_sharpe"] == 1.5
    assert row["win_rate_pct"] == 55.0


def test_write_sweep_rows_creates_parents_and_returns_path(tmp_path) -> None:
    """Output dir is created if missing; the resolved path is returned."""
    target = tmp_path / "nested" / "dirs" / "rows.json"
    rows = [{"label": 50, "n_trades": 1}]
    out = write_sweep_rows(rows, target)
    assert out == target
    assert target.exists()
    assert json.loads(target.read_text()) == rows
