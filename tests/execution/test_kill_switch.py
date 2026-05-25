"""Unit tests for the live α kill switch state machine.

The Alpaca + yfinance paths are mocked so these tests run offline. The focus
is the state-rollover logic and the warm-up / triggered / unavailable
status mapping — the parts that decide whether a live trade gets sent.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from src.execution import kill_switch as ks


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    """Redirect the state + report files into a tmp dir per test."""
    state_file = tmp_path / "live_strategy_state.json"
    report_file = tmp_path / "kill_switch.json"
    monkeypatch.setattr(ks, "STATE_FILE", state_file)
    monkeypatch.setattr(ks, "REPORT_FILE", report_file)
    return {"state": state_file, "report": report_file, "tmp": tmp_path}


class TestRollover:
    def test_first_call_initializes_state_to_today(self, isolated_state):
        state = ks.rollover_if_changed("strategy_v1")
        assert state.label == "strategy_v1"
        assert state.started_at == datetime.now(timezone.utc).date().isoformat()
        assert isolated_state["state"].exists()

    def test_same_label_is_idempotent(self, isolated_state):
        first = ks.rollover_if_changed("strategy_v1")
        # Mutate the file to a different started_at; same-label rollover
        # should NOT touch it.
        payload = json.loads(isolated_state["state"].read_text(encoding="utf-8"))
        payload["started_at"] = "2020-01-01"
        isolated_state["state"].write_text(json.dumps(payload), encoding="utf-8")

        second = ks.rollover_if_changed("strategy_v1")
        assert second.started_at == "2020-01-01", (
            "Same-label call rewrote the state file — should have been a no-op"
        )

    def test_label_change_resets_to_today(self, isolated_state):
        ks.rollover_if_changed("strategy_v1")
        # Backdate so we can prove the rewrite happened.
        payload = json.loads(isolated_state["state"].read_text(encoding="utf-8"))
        payload["started_at"] = "2020-01-01"
        isolated_state["state"].write_text(json.dumps(payload), encoding="utf-8")

        new = ks.rollover_if_changed("strategy_v2")
        assert new.label == "strategy_v2"
        assert new.started_at == datetime.now(timezone.utc).date().isoformat()

    def test_unreadable_state_treated_as_missing(self, isolated_state):
        isolated_state["state"].write_text("not json", encoding="utf-8")
        # Should not crash — should overwrite with a fresh state.
        state = ks.rollover_if_changed("strategy_v1")
        assert state.label == "strategy_v1"


class TestEvaluate:
    def test_warming_up_when_window_too_short(self, isolated_state):
        payload = ks.evaluate("strategy_v1", lookback_trading_days=60,
                              threshold_pct=-8.0)
        assert payload["status"] == "warming_up"
        assert payload["alpha_pct"] is None
        assert payload["trading_days_in_window"] == 0

    def test_unavailable_when_alpaca_returns_none(self, isolated_state, monkeypatch):
        # Backdate state so we're past warm-up.
        ks.rollover_if_changed("strategy_v1")
        old_state = ks.StrategyState(label="strategy_v1", started_at="2020-01-01")
        ks._save_state(old_state)

        monkeypatch.setattr(ks, "_aligned_window_alpha", lambda *a, **kw: None)
        payload = ks.evaluate("strategy_v1")
        assert payload["status"] == "unavailable"
        assert payload["alpha_pct"] is None

    def test_ok_when_alpha_above_threshold(self, isolated_state, monkeypatch):
        ks._save_state(ks.StrategyState(label="strategy_v1",
                                        started_at="2020-01-01"))
        monkeypatch.setattr(ks, "_aligned_window_alpha", lambda *a, **kw: {
            "paper_return_pct": 5.0,
            "spy_return_pct": 3.0,
            "alpha_pct": 2.0,
            "trading_days_in_window": 62,
        })
        payload = ks.evaluate("strategy_v1", threshold_pct=-8.0)
        assert payload["status"] == "ok"
        assert payload["alpha_pct"] == 2.0

    def test_triggered_when_alpha_below_threshold(self, isolated_state, monkeypatch):
        ks._save_state(ks.StrategyState(label="strategy_v1",
                                        started_at="2020-01-01"))
        monkeypatch.setattr(ks, "_aligned_window_alpha", lambda *a, **kw: {
            "paper_return_pct": -2.0,
            "spy_return_pct": 8.0,
            "alpha_pct": -10.0,
            "trading_days_in_window": 62,
        })
        payload = ks.evaluate("strategy_v1", threshold_pct=-8.0)
        assert payload["status"] == "triggered"
        assert payload["alpha_pct"] == -10.0

    def test_exact_threshold_does_not_trigger(self, isolated_state, monkeypatch):
        # < is strict: an α of exactly -8.0 should be OK, not triggered.
        # Documents the boundary behavior so a future refactor doesn't flip
        # this silently.
        ks._save_state(ks.StrategyState(label="strategy_v1",
                                        started_at="2020-01-01"))
        monkeypatch.setattr(ks, "_aligned_window_alpha", lambda *a, **kw: {
            "paper_return_pct": 0.0,
            "spy_return_pct": 8.0,
            "alpha_pct": -8.0,
            "trading_days_in_window": 62,
        })
        payload = ks.evaluate("strategy_v1", threshold_pct=-8.0)
        assert payload["status"] == "ok"

    def test_label_change_during_evaluate_warms_up_from_today(
        self, isolated_state, monkeypatch,
    ):
        # Strategy was running for years; we evaluate under a NEW label.
        # The rollover should reset and produce a warming_up verdict even
        # though the prior strategy had plenty of history.
        ks._save_state(ks.StrategyState(label="old", started_at="2020-01-01"))
        monkeypatch.setattr(ks, "_aligned_window_alpha", lambda *a, **kw: pytest.fail(
            "should not query alpha during warm-up"
        ))
        payload = ks.evaluate("new")
        assert payload["status"] == "warming_up"
        assert payload["strategy_label"] == "new"
        assert payload["strategy_started_at"] == (
            datetime.now(timezone.utc).date().isoformat()
        )
