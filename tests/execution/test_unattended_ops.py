"""Unattended-operation hardening tests (Railway cron path).

Pins:
  * trading.live circuit-breaker overlay: live=True overlays the live
    block over the base; live=False is untouched; missing live block
    falls back to base.
  * live_trade_factor_picks refuses every gate-override flag and
    requires the trading.live config block.
  * daily_cron calendar logic: open day, pre-open trading day,
    weekend/holiday.
  * run_daily_pipeline step timeout: a hung step is killed and marked
    failed (exit-code line preserved for the SSE parser).
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from src.execution.safety_gates import CircuitBreakerThresholds


# --- live circuit-breaker overlay ------------------------------------------


def _config(base: dict, live: dict | None):
    config = MagicMock()

    def cfg_get(*path, default=None):
        if path == ("trading", "circuit_breakers"):
            return base
        if path == ("trading", "live", "circuit_breakers"):
            return live if live is not None else default
        return default

    config.get.side_effect = cfg_get
    return config


_BASE = {
    "max_daily_loss_pct": -0.02,
    "max_drawdown_halt_pct": -0.10,
    "max_open_positions": 60,
    "max_order_value_usd": 5000,
}


def test_live_overlay_applies_live_caps():
    config = _config(_BASE, {"max_open_positions": 30,
                             "max_order_value_usd": 3000})
    t = CircuitBreakerThresholds.from_config(config, live=True)
    assert t.max_open_positions == 30
    assert t.max_order_value_usd == 3000.0
    # Non-overridden keys keep the base values.
    assert t.max_daily_loss_pct == -0.02
    assert t.max_drawdown_halt_pct == -0.10


def test_paper_path_ignores_live_block():
    config = _config(_BASE, {"max_order_value_usd": 3000})
    t = CircuitBreakerThresholds.from_config(config)  # live defaults False
    assert t.max_order_value_usd == 5000.0
    assert t.max_open_positions == 60


def test_live_overlay_missing_block_falls_back_to_base():
    config = _config(_BASE, None)
    t = CircuitBreakerThresholds.from_config(config, live=True)
    assert t.max_order_value_usd == 5000.0


# --- live script restrictions ----------------------------------------------


@pytest.mark.parametrize("flag", [
    "--override-drift",
    "--override-kill-switch",
    "--override-sanity-errors",
    "--skip-sanity",
])
def test_live_script_refuses_override_flags(monkeypatch, flag):
    from scripts.live_trade_factor_picks import main

    monkeypatch.setattr(sys, "argv", ["live_trade_factor_picks", flag])
    with pytest.raises(SystemExit, match="paper-only"):
        main()


def test_live_script_requires_trading_live_block(monkeypatch):
    from scripts import live_trade_factor_picks

    monkeypatch.setattr(sys, "argv", ["live_trade_factor_picks"])
    config = MagicMock()
    config.get.return_value = None  # no trading.live block
    with patch("src.config_loader.Config", return_value=config):
        with pytest.raises(SystemExit, match="trading.live"):
            live_trade_factor_picks.main()


# --- daily_cron calendar logic ---------------------------------------------


def test_is_trading_day_when_open():
    from scripts.daily_cron import _is_trading_day

    assert _is_trading_day({"is_open": True, "next_open": None})


def test_is_trading_day_pre_open():
    """Cron fires pre-open on a trading day: next_open is later TODAY."""
    from datetime import datetime, timedelta, timezone

    from scripts.daily_cron import _is_trading_day

    next_open = datetime.now(timezone.utc) + timedelta(hours=2)
    clock = {"is_open": False, "next_open": next_open.isoformat()}
    assert _is_trading_day(clock)


def test_is_not_trading_day_weekend():
    """Weekend/holiday: next_open is a different date -> skip silently."""
    from datetime import datetime, timedelta, timezone

    from scripts.daily_cron import _is_trading_day

    next_open = datetime.now(timezone.utc) + timedelta(days=2)
    clock = {"is_open": False, "next_open": next_open.isoformat()}
    assert not _is_trading_day(clock)


def test_execution_mode_default_and_live(monkeypatch):
    from scripts.daily_cron import _execution_mode

    monkeypatch.delenv("STOCKNEW_EXECUTION_MODE", raising=False)
    assert _execution_mode() == "paper"
    monkeypatch.setenv("STOCKNEW_EXECUTION_MODE", "live")
    assert _execution_mode() == "live"
    monkeypatch.setenv("STOCKNEW_EXECUTION_MODE", "bogus")
    assert _execution_mode() == "paper"


# --- pipeline step timeout ---------------------------------------------------


def test_pipeline_step_timeout_kills_and_fails(monkeypatch):
    """A hung step must come back False (failed), not hang the day."""
    import scripts.run_daily_pipeline as pipeline

    monkeypatch.setattr(pipeline, "_step_timeout_seconds", lambda: 0.5)
    # `python -c "import time; time.sleep(60)"` via the same uv-run shape
    # the pipeline uses would drag uv into the test; patch subprocess at
    # the module boundary instead and raise the real exception type.
    import subprocess

    def fake_run(cmd, check, shell, timeout):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)

    monkeypatch.setattr(pipeline.subprocess, "run", fake_run)
    assert pipeline._run(["scripts.morning_briefing"], "morning_briefing") is False


def test_pipeline_timeout_disabled_when_zero(monkeypatch):
    import scripts.run_daily_pipeline as pipeline

    config = MagicMock()
    config.get.return_value = 0
    with patch("src.config_loader.Config", return_value=config):
        assert pipeline._step_timeout_seconds() is None
