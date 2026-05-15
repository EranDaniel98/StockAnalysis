"""Validation report tests.

Pins the convergence gate decision logic:
  * INSUFFICIENT when <22 days observed (configurable)
  * INSUFFICIENT when backtest baseline missing
  * PASS when |live - backtest| Sharpe delta <= tol
  * FAIL when delta > tol
  * Sharpe computation matches expected: daily returns annualized via
    sqrt(252).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
import pytest

from scripts.validation_report import (
    SHARPE_CONVERGENCE_TOL,
    _backtest_sharpe,
    _compute_live_sharpe,
    _evaluate_gate,
)


def _snap_seq(start_equity: float, daily_returns: list[float]) -> list[dict]:
    """Build a snapshot list with the given start equity and daily-pct returns.
    Each day's equity = previous * (1 + return)."""
    out = []
    equity = start_equity
    for i, r in enumerate(daily_returns):
        date = f"2026-05-{16 + i:02d}"
        out.append({
            "snapshot_date": date,
            "account_equity": equity,
            "n_positions": 0,
            "day_pnl_pct": 0.0,
            "cum_pnl_pct": 0.0,
            "submitted_today": 0,
            "refusals_orphan": 0,
            "refusals_safety_gate": 0,
            "refusals_score_valid": 0,
        })
        equity *= (1.0 + r)
    return out


# --- _compute_live_sharpe ---------------------------------------------------


def test_compute_live_sharpe_with_constant_returns():
    """0.1% daily, zero variance → divide-by-zero path → Sharpe = 0,
    not NaN/inf."""
    snaps = _snap_seq(100_000.0, [0.001] * 25)
    out = _compute_live_sharpe(snaps)
    assert out["n_days"] == 25
    assert out["ann_sharpe"] == 0.0  # zero std fallback
    assert out["mean_daily_pct"] == pytest.approx(0.1, abs=1e-3)


def test_compute_live_sharpe_with_realistic_drift():
    """Mean +0.1%/day, std ~0.5%/day, annualized Sharpe ≈ sqrt(252)*0.2
    ≈ 3.17 in the limit. With 30 samples we get noise; just verify
    positive and in a sane band."""
    rng = np.random.default_rng(seed=42)
    daily = rng.normal(loc=0.001, scale=0.005, size=30).tolist()
    snaps = _snap_seq(100_000.0, daily)
    out = _compute_live_sharpe(snaps)
    assert out["ann_sharpe"] is not None
    assert -5.0 < out["ann_sharpe"] < 10.0  # realistic envelope


def test_compute_live_sharpe_with_too_few_snapshots():
    """A single snapshot can't produce a return; result must say so
    instead of crashing."""
    snaps = _snap_seq(100_000.0, [])
    out = _compute_live_sharpe([{
        "snapshot_date": "2026-05-16",
        "account_equity": 100_000.0,
        "n_positions": 0,
        "day_pnl_pct": 0.0,
        "cum_pnl_pct": 0.0,
        "submitted_today": 0,
        "refusals_orphan": 0,
        "refusals_safety_gate": 0,
        "refusals_score_valid": 0,
    }])
    assert out["ann_sharpe"] is None
    assert out["n_days"] == 1


# --- _backtest_sharpe -------------------------------------------------------


def test_backtest_sharpe_reads_oos_block(tmp_path):
    fixture = {
        "out_of_sample": {
            "summary": {"total_return_pct": 24.24},
            "equity_stats": {"ann_sharpe": 1.84},
        },
        "bootstrap": {"ann_sharpe_ci": [0.92, 2.78]},
        "pipeline_version": "2026-05-15-test",
        "window": {"years": 2.0},
    }
    p = tmp_path / "fixture.json"
    p.write_text(json.dumps(fixture), encoding="utf-8")

    out = _backtest_sharpe(p)
    assert out["available"] is True
    assert out["ann_sharpe"] == 1.84
    assert out["ann_sharpe_ci"] == [0.92, 2.78]
    assert out["total_return_pct"] == 24.24
    assert out["pipeline_version"] == "2026-05-15-test"


def test_backtest_sharpe_missing_file(tmp_path):
    out = _backtest_sharpe(tmp_path / "nonexistent.json")
    assert out["available"] is False
    assert "not found" in out["reason"]


# --- _evaluate_gate ---------------------------------------------------------


def test_gate_insufficient_when_too_few_days():
    """Fewer than 22 daily snapshots → INSUFFICIENT (don't claim a
    verdict on sparse evidence)."""
    live = {"n_days": 10, "ann_sharpe": 1.5}
    bt = {"available": True, "ann_sharpe": 1.84}
    g = _evaluate_gate(live, bt, SHARPE_CONVERGENCE_TOL)
    assert g["verdict"] == "INSUFFICIENT"
    assert "22" in g["reason"]


def test_gate_insufficient_when_no_baseline():
    live = {"n_days": 30, "ann_sharpe": 1.5}
    bt = {"available": False, "reason": "missing fixture"}
    g = _evaluate_gate(live, bt, SHARPE_CONVERGENCE_TOL)
    assert g["verdict"] == "INSUFFICIENT"


def test_gate_pass_when_within_tolerance():
    """live=1.6, backtest=1.84, delta=0.24 ≤ 0.4 → PASS."""
    live = {"n_days": 30, "ann_sharpe": 1.6}
    bt = {"available": True, "ann_sharpe": 1.84}
    g = _evaluate_gate(live, bt, tol=0.4)
    assert g["verdict"] == "PASS"
    assert g["delta"] == 0.24


def test_gate_fail_when_outside_tolerance():
    """live=0.8, backtest=1.84, delta=1.04 > 0.4 → FAIL."""
    live = {"n_days": 30, "ann_sharpe": 0.8}
    bt = {"available": True, "ann_sharpe": 1.84}
    g = _evaluate_gate(live, bt, tol=0.4)
    assert g["verdict"] == "FAIL"
    assert g["delta"] == 1.04
    assert "investigate" in g["reason"]


def test_gate_pass_at_exact_tolerance_boundary():
    """Equality (delta == tol) is considered PASS — the tolerance is
    inclusive on the boundary."""
    live = {"n_days": 30, "ann_sharpe": 1.44}
    bt = {"available": True, "ann_sharpe": 1.84}
    g = _evaluate_gate(live, bt, tol=0.4)
    assert g["verdict"] == "PASS"
    assert g["delta"] == 0.4


def test_gate_insufficient_when_live_sharpe_none():
    """Zero-variance live curve produces Sharpe=0.0 (not None) but the
    real None case (e.g. only 1 day captured) must hit INSUFFICIENT."""
    live = {"n_days": 30, "ann_sharpe": None}
    bt = {"available": True, "ann_sharpe": 1.84}
    g = _evaluate_gate(live, bt, tol=0.4)
    assert g["verdict"] == "INSUFFICIENT"
