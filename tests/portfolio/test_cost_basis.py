"""Unit tests for src.portfolio.cost_basis."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.portfolio import cost_basis


@pytest.fixture(autouse=True)
def _clear_caches_and_env(monkeypatch):
    cost_basis.load_real_cost_basis.cache_clear()
    monkeypatch.delenv(cost_basis._ENV_FLAG, raising=False)
    yield
    cost_basis.load_real_cost_basis.cache_clear()


def _write_holdings(tmp_path: Path, rows: list[dict]) -> Path:
    """Write a holdings YAML and return its path."""
    p = tmp_path / "real_holdings.yaml"
    body = "holdings:\n"
    for row in rows:
        body += f"  - ticker: {row['ticker']}\n"
        body += f"    shares: {row['shares']}\n"
        body += f"    avg_price: {row['avg_price']}\n"
    p.write_text(body, encoding="utf-8")
    return p


def test_load_returns_empty_when_file_missing(tmp_path):
    missing = tmp_path / "does_not_exist.yaml"
    assert cost_basis.load_real_cost_basis(str(missing)) == {}


def test_load_parses_avg_prices(tmp_path):
    p = _write_holdings(tmp_path, [
        {"ticker": "AAPL", "shares": 10, "avg_price": 175.5},
        {"ticker": "MSFT", "shares": 5, "avg_price": 380.0},
    ])
    result = cost_basis.load_real_cost_basis(str(p))
    assert result == {"AAPL": 175.5, "MSFT": 380.0}


def test_load_uppercases_tickers(tmp_path):
    p = _write_holdings(tmp_path, [
        {"ticker": "aapl", "shares": 10, "avg_price": 175.5},
    ])
    assert cost_basis.load_real_cost_basis(str(p)) == {"AAPL": 175.5}


def test_apply_overrides_present_tickers_only():
    positions = [
        {"ticker": "AAPL", "shares": 10, "avg_price": 200.0,
         "current_price": 220.0, "unrealized_pnl": 200.0,
         "unrealized_pnl_pct": 10.0},
        {"ticker": "TSLA", "shares": 5, "avg_price": 250.0,
         "current_price": 200.0, "unrealized_pnl": -250.0,
         "unrealized_pnl_pct": -20.0},
    ]
    real_basis = {"AAPL": 150.0}  # TSLA absent — should pass through

    out = cost_basis.apply_real_cost_basis(positions, real_basis=real_basis)

    aapl, tsla = out
    # AAPL: overridden with real_avg=150. P&L recomputed from current=220.
    assert aapl["avg_price"] == 150.0
    assert aapl["cost_basis_source"] == "real_holdings"
    assert aapl["unrealized_pnl"] == pytest.approx((220 - 150) * 10)
    assert aapl["unrealized_pnl_pct"] == pytest.approx((220 / 150 - 1) * 100)
    # TSLA: unchanged. No cost_basis_source marker.
    assert tsla["avg_price"] == 250.0
    assert "cost_basis_source" not in tsla
    assert tsla["unrealized_pnl"] == -250.0


def test_apply_handles_missing_current_price():
    positions = [
        {"ticker": "AAPL", "shares": 10, "avg_price": 200.0,
         "current_price": None, "unrealized_pnl": 0.0,
         "unrealized_pnl_pct": 0.0},
    ]
    out = cost_basis.apply_real_cost_basis(
        positions, real_basis={"AAPL": 150.0},
    )
    # Avg is still overridden but P&L is zeroed (no current price).
    assert out[0]["avg_price"] == 150.0
    assert out[0]["unrealized_pnl"] == 0.0
    assert out[0]["unrealized_pnl_pct"] == 0.0


def test_apply_handles_fractional_shares():
    positions = [
        {"ticker": "SNDK", "shares": 10.4316, "avg_price": 1300.0,
         "current_price": 1400.0, "unrealized_pnl": 1043.16,
         "unrealized_pnl_pct": 7.69},
    ]
    out = cost_basis.apply_real_cost_basis(
        positions, real_basis={"SNDK": 1362.85},
    )
    # current 1400 vs real 1362.85: pnl ≈ (1400-1362.85) * 10.4316 ≈ 387.55
    assert out[0]["avg_price"] == 1362.85
    assert out[0]["unrealized_pnl"] == pytest.approx(
        (1400 - 1362.85) * 10.4316, abs=0.01,
    )


def test_apply_returns_passthrough_when_real_basis_empty():
    positions = [
        {"ticker": "AAPL", "shares": 10, "avg_price": 200.0,
         "current_price": 220.0, "unrealized_pnl": 200.0,
         "unrealized_pnl_pct": 10.0},
    ]
    out = cost_basis.apply_real_cost_basis(positions, real_basis={})
    assert out == positions


def test_apply_if_enabled_off_by_default(monkeypatch):
    monkeypatch.delenv(cost_basis._ENV_FLAG, raising=False)
    positions = [
        {"ticker": "AAPL", "shares": 10, "avg_price": 200.0,
         "current_price": 220.0, "unrealized_pnl": 200.0,
         "unrealized_pnl_pct": 10.0},
    ]
    out = cost_basis.apply_if_enabled(positions)
    assert out[0]["avg_price"] == 200.0  # unchanged
    assert "cost_basis_source" not in out[0]


def test_apply_if_enabled_on(monkeypatch, tmp_path):
    monkeypatch.setenv(cost_basis._ENV_FLAG, "1")
    p = _write_holdings(tmp_path, [
        {"ticker": "AAPL", "shares": 10, "avg_price": 150.0},
    ])
    monkeypatch.setattr(
        cost_basis, "_DEFAULT_PATH", p,
    )
    # Clear the lru_cache so the new _DEFAULT_PATH takes effect.
    cost_basis.load_real_cost_basis.cache_clear()
    positions = [
        {"ticker": "AAPL", "shares": 10, "avg_price": 200.0,
         "current_price": 220.0, "unrealized_pnl": 200.0,
         "unrealized_pnl_pct": 10.0},
    ]
    out = cost_basis.apply_if_enabled(positions)
    assert out[0]["avg_price"] == 150.0
    assert out[0]["cost_basis_source"] == "real_holdings"


def test_is_enabled_recognizes_truthy_values(monkeypatch):
    for val in ("1", "true", "TRUE", "yes"):
        monkeypatch.setenv(cost_basis._ENV_FLAG, val)
        assert cost_basis.is_enabled(), f"expected truthy for {val!r}"
    for val in ("0", "false", "no", "", "anything-else"):
        monkeypatch.setenv(cost_basis._ENV_FLAG, val)
        assert not cost_basis.is_enabled(), f"expected falsy for {val!r}"
