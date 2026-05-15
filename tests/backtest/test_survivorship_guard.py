"""Survivorship-bias guard tests (review item #4).

Pins:
  * Universe file with a `# captured: YYYY-MM-DD` header returns the date.
  * Missing header raises ValueError (refuse to silently treat absence
    as "no bias risk").
  * Malformed date string raises ValueError.
  * Backtest end_date > captured date raises SurvivorshipGuardError when
    refuse_survivor_only_window=True (the default).
  * Override flag suppresses the guard for explicit exploratory runs.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture
def tmp_universe_dir(tmp_path):
    """A throwaway config dir with our own universe-file shape."""
    cfg = tmp_path / "config"
    cfg.mkdir()
    return cfg


def _make_loader_for(cfg_dir: Path):
    """Build a ConfigLoader-shaped object that only exposes the
    get_universe_captured_date method we want to exercise.

    The full ConfigLoader needs settings.yaml + sectors.yaml + portfolio.yaml
    in place, which is more setup than this unit test needs. We replicate
    the captured-date logic directly here so the test is hermetic."""
    from src.config_loader import Config

    # Build a partial config_dir + bypass __init__'s file reads.
    loader = Config.__new__(Config)
    loader.config_dir = cfg_dir
    return loader


def test_captured_date_parsed_from_header(tmp_universe_dir):
    (tmp_universe_dir / "russell_1000_tickers.txt").write_text(
        "# captured: 2026-05-13\n# source: iShares IWB\nAAPL\nMSFT\n",
        encoding="utf-8",
    )
    loader = _make_loader_for(tmp_universe_dir)
    assert loader.get_universe_captured_date("russell_1000") == date(2026, 5, 13)


def test_missing_header_raises(tmp_universe_dir):
    """No '# captured:' line at all — refuse rather than silently
    return None (which would let the guard sleep through)."""
    (tmp_universe_dir / "russell_1000_tickers.txt").write_text(
        "AAPL\nMSFT\n", encoding="utf-8",
    )
    loader = _make_loader_for(tmp_universe_dir)
    with pytest.raises(ValueError, match="missing.*captured"):
        loader.get_universe_captured_date("russell_1000")


def test_malformed_date_raises(tmp_universe_dir):
    (tmp_universe_dir / "russell_1000_tickers.txt").write_text(
        "# captured: not-a-date\nAAPL\n", encoding="utf-8",
    )
    loader = _make_loader_for(tmp_universe_dir)
    with pytest.raises(ValueError, match="malformed captured-date"):
        loader.get_universe_captured_date("russell_1000")


def test_unknown_universe_returns_none(tmp_universe_dir):
    """Unknown label or missing file returns None — caller decides
    whether to refuse the run on a missing universe file."""
    loader = _make_loader_for(tmp_universe_dir)
    assert loader.get_universe_captured_date("russell_1000") is None
    assert loader.get_universe_captured_date("nonexistent_universe") is None


# --- Backtest engine integration --------------------------------------------


def test_engine_refuses_window_past_capture_date(tmp_universe_dir):
    """run_backtest must raise SurvivorshipGuardError when end_date is
    after the universe-capture date, default behavior."""
    from src.backtest.engine import (
        BacktestConfig,
        SurvivorshipGuardError,
        run_backtest,
    )

    (tmp_universe_dir / "russell_1000_tickers.txt").write_text(
        "# captured: 2026-01-01\nAAPL\n", encoding="utf-8",
    )
    config = _make_loader_for(tmp_universe_dir)

    bt_cfg = BacktestConfig(
        start_date=pd.Timestamp("2024-01-01"),
        end_date=pd.Timestamp("2026-05-15"),  # AFTER capture
        universe_label="russell_1000",
        refuse_survivor_only_window=True,
    )
    # Minimal price data so we get past the empty-frame check.
    price_data = {
        "AAPL": pd.DataFrame(
            {"Open": [100.0], "Close": [100.0]},
            index=[pd.Timestamp("2024-01-01")],
        ),
    }
    with pytest.raises(SurvivorshipGuardError, match="end_date.*AFTER"):
        run_backtest(
            price_data=price_data,
            fundamentals={"AAPL": {}},
            config=config,
            strategy={"weights": {}, "thresholds": {}},
            bt_cfg=bt_cfg,
        )


def test_engine_allows_window_inside_capture_date(tmp_universe_dir):
    """When end_date <= captured date, the guard stays out of the way
    and the engine proceeds (will likely hit a different downstream
    error in this hermetic setup — we only check the guard didn't
    pre-empt it)."""
    from src.backtest.engine import (
        BacktestConfig,
        SurvivorshipGuardError,
        run_backtest,
    )

    (tmp_universe_dir / "russell_1000_tickers.txt").write_text(
        "# captured: 2026-05-15\nAAPL\n", encoding="utf-8",
    )
    config = _make_loader_for(tmp_universe_dir)

    bt_cfg = BacktestConfig(
        start_date=pd.Timestamp("2024-01-01"),
        end_date=pd.Timestamp("2025-12-31"),  # BEFORE capture
        universe_label="russell_1000",
        refuse_survivor_only_window=True,
    )
    price_data = {
        "AAPL": pd.DataFrame(
            {"Open": [100.0], "Close": [100.0]},
            index=[pd.Timestamp("2024-01-01")],
        ),
    }
    # Should NOT raise SurvivorshipGuardError. May raise something else
    # downstream (e.g. config missing get_sector_relative_scoring); we
    # only assert the guard didn't trip.
    try:
        run_backtest(
            price_data=price_data,
            fundamentals={"AAPL": {}},
            config=config,
            strategy={"weights": {}, "thresholds": {}},
            bt_cfg=bt_cfg,
        )
    except SurvivorshipGuardError:
        pytest.fail("guard should not trip when end_date <= captured")
    except Exception:
        # Any non-guard exception is fine for this test.
        pass


def test_engine_override_suppresses_guard(tmp_universe_dir):
    """refuse_survivor_only_window=False lets a survivor-only window
    through — for explicit exploratory runs the operator knows are
    biased."""
    from src.backtest.engine import (
        BacktestConfig,
        SurvivorshipGuardError,
        run_backtest,
    )

    (tmp_universe_dir / "russell_1000_tickers.txt").write_text(
        "# captured: 2026-01-01\nAAPL\n", encoding="utf-8",
    )
    config = _make_loader_for(tmp_universe_dir)

    bt_cfg = BacktestConfig(
        start_date=pd.Timestamp("2024-01-01"),
        end_date=pd.Timestamp("2026-05-15"),
        universe_label="russell_1000",
        refuse_survivor_only_window=False,  # explicit override
    )
    price_data = {
        "AAPL": pd.DataFrame(
            {"Open": [100.0], "Close": [100.0]},
            index=[pd.Timestamp("2024-01-01")],
        ),
    }
    try:
        run_backtest(
            price_data=price_data,
            fundamentals={"AAPL": {}},
            config=config,
            strategy={"weights": {}, "thresholds": {}},
            bt_cfg=bt_cfg,
        )
    except SurvivorshipGuardError:
        pytest.fail("override should suppress the guard")
    except Exception:
        pass
