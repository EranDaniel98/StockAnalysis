"""Integration test for the regime gate inside run_backtest.

End-to-end through the engine is too heavy (5 analyzers + Rich progress
+ fundamental lookahead guard). Instead we monkeypatch ``_score_ticker``
to return a uniformly high score for every ticker on every Monday, so
the only thing controlling entry rate is the regime gate. Then we
compare three runs:

  * gate off (mode='off')           — engine opens positions every week
  * gate on with bull market data   — entries still happen
  * gate on with bear market data   — entries blocked

If the gate fires correctly, run 3 has ``entries_blocked > 0`` and a
strictly smaller closed-trade count than runs 1/2.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import src.backtest.engine as engine
from src.backtest.engine import BacktestConfig, run_backtest


class _StubConfig:
    """Minimal stand-in for ``Config`` — just satisfies the calls
    run_backtest makes (``get_regime_filter`` + the analyzer config
    lookups, which the stubbed _score_ticker bypasses)."""

    def __init__(self, regime_filter: dict) -> None:
        self._rf = regime_filter

    def get_regime_filter(self) -> dict:
        return self._rf

    def get(self, *args, default=None):
        return default


def _trending_prices(start: str, n_days: int, base: float, daily_drift: float) -> pd.DataFrame:
    """Smooth uptrend, no noise — every entry has positive ATR and a
    valid close. Real returns are irrelevant; the stub scoring fires
    regardless. ATR comes out non-zero from the synthetic high/low band.
    """
    idx = pd.date_range(start=start, periods=n_days, freq="B")
    closes = base * (1.0 + daily_drift) ** np.arange(n_days)
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes * 1.02,
            "Low": closes * 0.98,
            "Close": closes,
            "Volume": np.full(n_days, 1_000_000.0),
        },
        index=idx,
    )


def _build_universe(n_tickers: int, start: str, n_days: int) -> dict[str, pd.DataFrame]:
    return {
        f"T{i:02d}": _trending_prices(start, n_days, base=50.0 + i, daily_drift=0.0005)
        for i in range(n_tickers)
    }


def _build_bull_spy(start: str, n_days: int) -> pd.DataFrame:
    return _trending_prices(start, n_days, base=400.0, daily_drift=0.001)


def _build_bear_spy(start: str, n_days: int) -> pd.DataFrame:
    """SPY climbs for the SMA-establishment window then crashes — every
    Monday in the back half has spy_close < SMA200."""
    idx = pd.date_range(start=start, periods=n_days, freq="B")
    half = n_days // 2
    climb = np.linspace(300.0, 500.0, half)
    crash = np.full(n_days - half, 250.0)
    closes = np.concatenate([climb, crash])
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes * 1.01,
            "Low": closes * 0.99,
            "Close": closes,
            "Volume": np.full(n_days, 5_000_000.0),
        },
        index=idx,
    )


def _build_vix(start: str, n_days: int, level: float) -> pd.DataFrame:
    idx = pd.date_range(start=start, periods=n_days, freq="B")
    closes = np.full(n_days, level)
    return pd.DataFrame({"Close": closes}, index=idx)


@pytest.fixture
def stub_score(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force every ticker to return a high score with a sane ATR + close.
    Lets us isolate the gate from analyzer behavior."""

    def _fake_score(
        ticker, df_slice, fund, config, strategy,
        eh=None, as_of=None, sector_stats=None,
    ):
        if df_slice is None or len(df_slice) < 50:
            return None
        return {
            "composite_score": 90.0,
            "sub_scores": {"technical": 90.0},
            "all_signals": [],
            "_atr": 1.0,
            "_close": float(df_slice["Close"].iloc[-1]),
        }

    monkeypatch.setattr(engine, "_score_ticker", _fake_score)


def _make_run(
    *,
    regime_filter: dict,
    spy_df: pd.DataFrame,
    vix_df: pd.DataFrame,
    n_days: int = 500,
):
    start_date = pd.Timestamp("2023-01-02")
    end_date = start_date + pd.Timedelta(days=n_days - 1)
    universe = _build_universe(n_tickers=5, start="2022-01-03", n_days=n_days + 220)
    bt_cfg = BacktestConfig(
        start_date=start_date,
        end_date=end_date,
        min_score=50.0,
        max_open_positions=5,
        starting_cash=100_000.0,
        min_history_bars=200,
        workers=2,
        bootstrap_resamples=0,  # skip bootstrap for speed
        earnings_blackout_days=0,
        accept_lookahead=True,  # we're using stub scorer; bypass guard
    )
    return run_backtest(
        price_data=universe,
        fundamentals={t: {"sector": "Tech"} for t in universe},
        config=_StubConfig(regime_filter),
        strategy={"weights": {"technical": 1.0}, "thresholds": {}},
        bt_cfg=bt_cfg,
        spy_df=spy_df,
        vix_df=vix_df,
    )


@pytest.fixture(scope="module")
def n_days() -> int:
    return 500  # ~2 years of bars — long enough for SMA200 + a meaningful run


class TestRegimeGateInBacktest:
    def test_gate_off_opens_trades(self, stub_score, n_days: int) -> None:
        spy = _build_bull_spy("2022-01-03", n_days + 220)
        vix = _build_vix("2022-01-03", n_days + 220, level=15.0)
        result = _make_run(
            regime_filter={"enabled": False, "mode": "off",
                           "sma_period": 200, "vix_low": 20.0, "vix_high": 25.0},
            spy_df=spy, vix_df=vix,
        )
        assert result["regime_gate"]["enabled"] is False
        assert result["regime_gate"]["entries_blocked"] == 0
        assert len(result["trades"]) > 0

    def test_gate_bull_market_passes(self, stub_score, n_days: int) -> None:
        """skip_bear in a bull market = no blocks, same trade flow as off."""
        spy = _build_bull_spy("2022-01-03", n_days + 220)
        vix = _build_vix("2022-01-03", n_days + 220, level=15.0)
        result = _make_run(
            regime_filter={"enabled": True, "mode": "skip_bear",
                           "sma_period": 200, "vix_low": 20.0, "vix_high": 25.0},
            spy_df=spy, vix_df=vix,
        )
        assert result["regime_gate"]["enabled"] is True
        assert result["regime_gate"]["mode"] == "skip_bear"
        assert result["regime_gate"]["entries_blocked"] == 0
        # Every Monday classifies as bull in this synthetic universe.
        labels = {r["label"] for r in result["regime_gate"]["history"]}
        assert "bull" in labels

    def test_gate_bear_market_blocks(self, stub_score, n_days: int) -> None:
        """SPY crash + high VIX → bear → skip_bear blocks new entries."""
        spy = _build_bear_spy("2022-01-03", n_days + 220)
        vix = _build_vix("2022-01-03", n_days + 220, level=35.0)
        result = _make_run(
            regime_filter={"enabled": True, "mode": "skip_bear",
                           "sma_period": 200, "vix_low": 20.0, "vix_high": 25.0},
            spy_df=spy, vix_df=vix,
        )
        gate = result["regime_gate"]
        assert gate["enabled"] is True
        assert gate["entries_blocked"] > 0
        assert gate["mondays_blocked"] > 0
        labels = {r["label"] for r in gate["history"]}
        assert "bear" in labels

    def test_legacy_config_without_get_regime_filter(
        self, stub_score, n_days: int, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If a caller hands run_backtest a Config object that predates
        get_regime_filter(), the engine treats it as gate-off and does
        not crash. Protects users on old/branch checkouts."""

        class LegacyConfig:
            def get(self, *args, default=None):
                return default

        start_date = pd.Timestamp("2023-01-02")
        end_date = start_date + pd.Timedelta(days=n_days - 1)
        universe = _build_universe(n_tickers=3, start="2022-01-03", n_days=n_days + 220)
        bt_cfg = BacktestConfig(
            start_date=start_date, end_date=end_date, min_score=50.0,
            max_open_positions=3, starting_cash=50_000.0,
            min_history_bars=200, workers=2, bootstrap_resamples=0,
            earnings_blackout_days=0, accept_lookahead=True,
        )
        result = run_backtest(
            price_data=universe,
            fundamentals={t: {"sector": "Tech"} for t in universe},
            config=LegacyConfig(),
            strategy={"weights": {"technical": 1.0}, "thresholds": {}},
            bt_cfg=bt_cfg,
            spy_df=_build_bull_spy("2022-01-03", n_days + 220),
            vix_df=_build_vix("2022-01-03", n_days + 220, level=15.0),
        )
        assert result["regime_gate"]["enabled"] is False
        assert result["regime_gate"]["entries_blocked"] == 0
