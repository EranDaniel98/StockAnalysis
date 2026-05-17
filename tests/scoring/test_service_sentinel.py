"""Crash-sentinel regression for analyze_and_score.

Before ba0f9c0, an exception in the per-ticker analyzer chain caught the
exception, logged it, and DROPPED the ticker entirely from the results
dict. The API then returned 404 for that ticker with no explanation —
indistinguishable from "ticker doesn't exist." Real-money risk: a
ticker the user expected to see in a scan silently vanished.

The fix emits a sentinel result with every required analyzer marked
``{"score": None, "error": ...}`` so the engine flips score_valid=False,
the recommender forces HOLD/Low, and the FE renders a Data-Quality
warning.

This test pins the sentinel emission so a future refactor that
"simplifies" the try/except can't quietly restore the silent-drop
behaviour.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

from src.scoring.service import analyze_and_score


def _ohlcv(n: int = 300) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": np.linspace(100, 150, n),
            "High": np.linspace(101, 151, n),
            "Low": np.linspace(99, 149, n),
            "Close": np.linspace(100, 150, n),
            "Volume": np.full(n, 1_000_000),
        },
        index=pd.date_range("2024-01-01", periods=n, freq="B"),
    )


def _config_stub():
    cfg = MagicMock()
    cfg.get_scoring_thresholds = MagicMock(return_value={
        "strong_buy": 80, "buy": 65, "hold_upper": 50,
        "hold_lower": 35, "sell": 20,
    })
    # config.get(k, default=...) returns the default for unknown keys
    # so the recommender's risk_management branch doesn't trip on a
    # MagicMock as the position_sizing method.
    cfg.get = MagicMock(side_effect=lambda *args, **kwargs: kwargs.get("default", {}))
    return cfg


def _strategy():
    return {
        "weights": {
            "technical": 0.30,
            "fundamental": 0.25,
            "pattern": 0.15,
            "statistical": 0.20,
            "trend": 0.10,
        },
        "thresholds": {
            "strong_buy": 80, "buy": 65, "hold_upper": 50,
            "hold_lower": 35, "sell": 20,
        },
    }


def test_analyzer_crash_emits_sentinel_not_dropped():
    """When technical.analyze raises mid-loop, the ticker must still
    appear in the output — as a HOLD with score_valid=False — not be
    silently dropped.
    """
    price_data = {"CRASH": _ohlcv(), "OK": _ohlcv()}
    fundamentals = {
        "CRASH": {"name": "Crash Co.", "sector": "Technology"},
        "OK": {"name": "OK Inc.", "sector": "Technology"},
    }

    real_technical = __import__(
        "src.scoring.analyzers.technical", fromlist=["analyze"]
    ).analyze

    def selective_crash(df, cfg):
        # We can't tell the ticker from inside technical.analyze, so
        # branch on the first OHLCV value — CRASH and OK have the same
        # synthetic frame, so we use mock state instead.
        raise RuntimeError("simulated analyzer crash")

    events: list[dict] = []

    # Patch only for the CRASH ticker by counting calls.
    call_count = {"n": 0}

    def crash_first_call(df, cfg):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated analyzer crash")
        return real_technical(df, cfg)

    with patch(
        "src.scoring.service.technical.analyze",
        side_effect=crash_first_call,
    ):
        results = analyze_and_score(
            price_data_map=price_data,
            fundamentals_map=fundamentals,
            config=_config_stub(),
            strategy=_strategy(),
            on_event=events.append,
        )

    # The crash ticker must NOT vanish.
    tickers = {r["ticker"] for r in results}
    assert "CRASH" in tickers, (
        "ticker that crashed mid-analysis must still appear in results "
        "(as HOLD with score_valid=False), not be dropped silently"
    )
    crash_rec = next(r for r in results if r["ticker"] == "CRASH")
    assert crash_rec["action"] == "HOLD"
    # Either gate ("Low" from score-invalid or "None" from new gates)
    # is acceptable here — the contract is "not a confident action".
    assert crash_rec["confidence"] in ("Low", "None")
    assert crash_rec["score_valid"] is False
    # error_count counts the required analyzers that erred. The sentinel
    # flags all five required slots, but some are forced to None which
    # the engine may or may not count — we only assert >0.
    assert crash_rec["error_count"] > 0

    # The 'analyze_ticker_failed' event must fire for the crashed ticker
    # so the SSE caller can surface progress + the failure reason.
    failed = [e for e in events if e.get("stage") == "analyze_ticker_failed"]
    assert len(failed) == 1
    assert failed[0]["ticker"] == "CRASH"
    assert "simulated analyzer crash" in failed[0]["error"]
