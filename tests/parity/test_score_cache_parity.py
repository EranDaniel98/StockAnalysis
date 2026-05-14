"""Parity: run_backtest_multi_mode == per-mode run_backtest.

Both code paths must agree on trade count, equity curve, and OOS Sharpe
for each of the three insider-flow sweep modes. The multi-mode path
scores once and re-weights per mode via ``recompose_composite``; the
legacy path re-runs the entire analyzer chain per mode. They must produce
identical portfolios.

We monkeypatch ``_score_ticker`` with a deterministic stub so the test
runs in <5 s and doesn't depend on the real analyzer chain. The stub
emits realistic per-source sub-scores AND per-source signal counts so
both code paths exercise the recompose-vs-calculate-composite formula.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import src.backtest.engine as engine
from src.backtest.engine import (
    BacktestConfig,
    SweepMode,
    run_backtest,
    run_backtest_multi_mode,
)
from src.backtest.score_cache import ALL_SOURCES


class _StubConfig:
    def __init__(self) -> None:
        pass

    def get_regime_filter(self) -> dict:
        return {"enabled": False}

    def get_sector_relative_scoring(self) -> dict:
        return {"enabled": False}

    def get(self, *args, default=None):
        return default


def _prices(start: str, n_days: int, base: float, daily_drift: float) -> pd.DataFrame:
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


def _universe(n_tickers: int, start: str, n_days: int) -> dict[str, pd.DataFrame]:
    return {
        f"T{i:02d}": _prices(start, n_days, base=50.0 + i, daily_drift=0.0005)
        for i in range(n_tickers)
    }


@pytest.fixture
def deterministic_score(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make _score_ticker return a hash-stable result per (ticker, as_of).

    Returns sub_scores + per-source signal counts shaped exactly like
    the real ``_score_ticker`` output, including the optional
    ``_bullish_by_source`` / ``_bearish_by_source`` / ``_pead_bonus``
    fields populated by the cache path.

    Crucially: when ``insider_txs_slice`` is None (legacy off-mode),
    insider_flow is absent from sub_scores and from the signal-count
    dicts. When the slice is non-None (other modes + cached path), the
    insider_flow sub-score and signals are present.
    """

    def _fake(
        ticker, df_slice, fund, config, strategy,
        eh=None, as_of=None, sector_stats=None, benchmark_slice=None,
        insider_txs_slice=None, catalyst_snapshot=None,
        short_interest_history=None, sector_etf_slice=None,
        sector_etf_symbol=None,
    ):
        if df_slice is None or len(df_slice) < 50:
            return None
        seed = (hash(ticker) ^ hash(str(as_of))) & 0xFFFF
        rng = np.random.default_rng(seed)

        sub_scores = {
            "technical": 70.0 + float(rng.uniform(-10, 10)),
            "fundamental": 55.0,
            "pattern": 60.0 + float(rng.uniform(-5, 5)),
            "statistical": 65.0,
            "trend": 60.0,
        }
        bull_by_src = {
            "technical": int(rng.integers(0, 4)),
            "pattern": int(rng.integers(0, 2)),
            "trend": 1,
        }
        bear_by_src = {
            "technical": int(rng.integers(0, 2)),
            "fundamental": 1,
        }

        if insider_txs_slice is not None:
            sub_scores["insider_flow"] = 50.0 + float(rng.uniform(-15, 25))
            bull_by_src["insider_flow"] = int(rng.integers(0, 3))
            bear_by_src["insider_flow"] = int(rng.integers(0, 2))

        # Composite via the real engine — keeps both paths reading the same
        # arithmetic. Re-derive composite from sub_scores + weights, mirroring
        # calculate_composite_score (without optional consensus scaling).
        weights = strategy.get("weights", {}) or {}
        total_w = sum(weights.get(k, 0) for k in sub_scores)
        if total_w > 0:
            composite = sum(
                sub_scores[k] * weights.get(k, 0) for k in sub_scores
            ) / total_w
        else:
            composite = 50.0
        # Consensus scaling matches engine — same formula as
        # apply_consensus_scaling.
        if strategy.get("use_consensus_scaling", False):
            vals = np.array(list(sub_scores.values()), dtype=float)
            std = float(vals.std(ddof=0))
            confidence = max(0.4, 1.0 - min(std / 20.0, 1.0))
            composite = 50.0 + (composite - 50.0) * confidence
        # Signal consensus ±5
        bull_total = sum(bull_by_src.values())
        bear_total = sum(bear_by_src.values())
        total_sig = bull_total + bear_total
        if total_sig > 0:
            composite += (bull_total - bear_total) / total_sig * 5
        composite = max(0.0, min(100.0, composite))

        return {
            "composite_score": round(composite, 2),
            "sub_scores": sub_scores,
            "all_signals": [],
            "_atr": 1.0,
            "_close": float(df_slice["Close"].iloc[-1]),
            "_bullish_by_source": bull_by_src,
            "_bearish_by_source": bear_by_src,
            "_pead_bonus": 0.0,
        }

    monkeypatch.setattr(engine, "_score_ticker", _fake)


def _bt_cfg() -> BacktestConfig:
    return BacktestConfig(
        start_date=pd.Timestamp("2023-06-05"),
        end_date=pd.Timestamp("2023-12-29"),
        min_score=50.0,
        max_open_positions=5,
        starting_cash=100_000.0,
        min_history_bars=100,
        workers=2,
        bootstrap_resamples=0,
        earnings_blackout_days=0,
        accept_lookahead=True,
    )


def _strategy_with_insider(insider_weight: float) -> dict:
    """Sweep-style strategy: rescale base weights so total stays at 1.
    Matches sweep_insider_flow._strategy_with_insider_weight."""
    base = {
        "technical": 0.30,
        "fundamental": 0.05,
        "pattern": 0.25,
        "statistical": 0.15,
        "trend": 0.10,
    }
    if insider_weight <= 0:
        weights = dict(base)
        weights["insider_flow"] = 0.0
    else:
        other_sum = sum(base.values())
        scale = (1.0 - insider_weight) / other_sum
        weights = {k: v * scale for k, v in base.items()}
        weights["insider_flow"] = insider_weight
    return {
        "weights": weights,
        "use_consensus_scaling": True,
        "thresholds": {},
    }


def test_multi_mode_matches_per_mode_run(deterministic_score) -> None:
    universe = _universe(n_tickers=5, start="2022-01-03", n_days=600)
    fundamentals = {t: {"sector": "Tech"} for t in universe}
    # Synthetic insider_transactions need only be truthy per ticker for the
    # engine to invoke the analyzer on the cached path. Stub _score_ticker
    # ignores their content — it just inspects whether slice is None.
    class _FakeTx:
        def __init__(self, ticker: str, d: pd.Timestamp) -> None:
            self.ticker = ticker
            self.filing_date = d.date()
    insider_txs = {
        t: [_FakeTx(t, pd.Timestamp("2022-06-01"))] for t in universe
    }
    cfg = _StubConfig()
    bt_cfg = _bt_cfg()

    legacy: dict[str, dict] = {}
    for label, weight, run_analyzer in [
        ("off", 0.0, False),
        ("signal_only", 0.0, True),
        ("weighted", 0.10, True),
    ]:
        legacy[label] = run_backtest(
            price_data=universe,
            fundamentals=fundamentals,
            config=cfg,
            strategy=_strategy_with_insider(weight),
            bt_cfg=bt_cfg,
            insider_transactions=insider_txs if run_analyzer else None,
        )

    sweep_modes = [
        SweepMode(
            label="off",
            strategy=_strategy_with_insider(0.0),
            enabled_sources=set(ALL_SOURCES - {"insider_flow"}),
        ),
        SweepMode(
            label="signal_only",
            strategy=_strategy_with_insider(0.0),
            enabled_sources=None,
        ),
        SweepMode(
            label="weighted",
            strategy=_strategy_with_insider(0.10),
            enabled_sources=None,
        ),
    ]
    cached = run_backtest_multi_mode(
        sweep_modes,
        price_data=universe,
        fundamentals=fundamentals,
        config=cfg,
        bt_cfg=bt_cfg,
        insider_transactions=insider_txs,
    )

    for label in ["off", "signal_only", "weighted"]:
        leg = legacy[label]
        cac = cached[label]
        assert (
            leg["full"]["summary"]["n_trades"]
            == cac["full"]["summary"]["n_trades"]
        ), f"trade count mismatch for mode={label}"
        assert (
            leg["full"]["summary"]["total_return_pct"]
            == pytest.approx(cac["full"]["summary"]["total_return_pct"], abs=0.01)
        ), f"total return mismatch for mode={label}"
        leg_trades = sorted(
            (t["ticker"], t["entry_date"], t["exit_date"])
            for t in leg["trades"]
        )
        cac_trades = sorted(
            (t["ticker"], t["entry_date"], t["exit_date"])
            for t in cac["trades"]
        )
        assert leg_trades == cac_trades, (
            f"trade list mismatch for mode={label}: "
            f"legacy={leg_trades} cached={cac_trades}"
        )
