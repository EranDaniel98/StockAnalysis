"""Kronos spike — does it forecast US daily bars at all sensibly?

VERDICT 2026-05-19: KILL. 67% sign agreement is misleading; model has
severe negative-return bias on OOD US daily bars (5/6 forecasts in the
-25% to -38% range; mean err 31.55pp, max 61.50pp). Out of distribution.
See reports/kronos_spike_summary.json + memory project_kronos_spike_kill.

To re-run: clone https://github.com/shiyu-coder/Kronos.git to
vendor/kronos/, then `uv run python scripts/spike_kronos_forecast.py`.

Killswitch criteria (defined when task #5 was created):
  - 2-hour timebox
  - abort if (a) CPU inference > 60s/ticker (we have GPU, n/a)
            (b) forecasts are uncalibrated/unusable on out-of-distribution US daily

Test design
-----------
Pick anchor date deep enough in the snapshot to have both a full
400-day lookback and a full 63-day forward window (matches our
quarterly rebalance). Forecast 63 days forward for several tickers,
compare forecast 63-day return to realized 63-day return.

Sign agreement on >=4 of 6 tickers AND no order-of-magnitude errors
(|fc - actual| < 30 percentage points on every ticker) → escalate
to a real factor build.

Otherwise → kill.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "vendor" / "kronos"))

from model import Kronos, KronosTokenizer, KronosPredictor  # noqa: E402

SNAPSHOT = "1dd88cad8e1f7534"  # 2024-05-13 .. 2026-05-13
# 20-ticker cross-sector basket for short-horizon re-test.
TICKERS = [
    "NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA",  # mega-cap tech
    "JPM", "BAC", "WFC",                                       # banks
    "XOM", "CVX",                                              # energy
    "WMT", "COST", "PG", "KO",                                 # consumer staples
    "JNJ", "PFE", "UNH",                                       # healthcare
    "CAT",                                                     # industrial
]
LOOKBACK = 400
# Horizon under test. 63 = quarterly (failed 2026-05-19, see kill memo).
# 5 = one trading week, the most plausible horizon for daily-trade use.
PRED_LEN = 5

# Killswitch thresholds for the SHORT-HORIZON re-test:
# Sign agreement above coin flip (>55%) AND mean abs error below typical
# 5-day move magnitude (<3pp). Anything weaker = same OOD failure mode.
SIGN_THRESHOLD = 0.55
MEAN_ERR_THRESHOLD_PP = 3.0
MAX_ERR_THRESHOLD_PP = 10.0


def load_prices() -> pd.DataFrame:
    """Wide OHLCV from snapshot parquet, indexed by date."""
    path = REPO / "data" / "snapshots" / SNAPSHOT / "prices.parquet"
    df = pd.read_parquet(path)
    return df


def slice_ticker(prices: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Long-format OHLCV for one ticker. Returns columns
    [open, high, low, close, volume, amount] indexed by date.
    """
    if "ticker" in prices.columns:
        df = prices[prices["ticker"] == ticker].copy()
        df = df.sort_values("date").set_index("date")
    else:
        # MultiIndex case — bail and let caller adapt.
        raise NotImplementedError(
            f"unexpected prices schema (no 'ticker' col): {prices.columns.tolist()}"
        )
    df = df.rename(columns=str.lower)
    needed = ["open", "high", "low", "close", "volume"]
    missing = [c for c in needed if c not in df.columns]
    if missing:
        raise ValueError(f"{ticker}: missing columns {missing}")
    df["amount"] = df["close"] * df["volume"]
    return df[["open", "high", "low", "close", "volume", "amount"]]


def main() -> int:
    print(f"[spike] loading prices from snapshot {SNAPSHOT}")
    prices_wide = load_prices()
    print(f"[spike] prices schema: cols={prices_wide.columns.tolist()[:8]}... "
          f"rows={len(prices_wide)}")

    print("[spike] loading Kronos-small + tokenizer (HF)")
    t0 = time.time()
    tokenizer = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
    model = Kronos.from_pretrained("NeoQuasar/Kronos-small")
    predictor = KronosPredictor(model, tokenizer, max_context=512)
    print(f"[spike] model loaded in {time.time()-t0:.1f}s on device={predictor.device}")

    rows = []
    for ticker in TICKERS:
        try:
            df = slice_ticker(prices_wide, ticker)
        except Exception as e:
            print(f"[spike] {ticker}: skip ({e})")
            continue

        if len(df) < LOOKBACK + PRED_LEN:
            print(f"[spike] {ticker}: insufficient history "
                  f"({len(df)} < {LOOKBACK + PRED_LEN})")
            continue

        # Anchor at end of available history minus PRED_LEN so we have
        # ground truth for the full forecast window.
        anchor_idx = len(df) - PRED_LEN
        x_df = df.iloc[anchor_idx - LOOKBACK:anchor_idx].copy()
        y_truth = df.iloc[anchor_idx:anchor_idx + PRED_LEN].copy()

        x_timestamp = pd.Series(x_df.index, name="ts")
        y_timestamp = pd.Series(y_truth.index, name="ts")
        # Kronos expects pd.Series.dt accessor — index is DatetimeIndex
        # already from parquet (verify below).
        if not pd.api.types.is_datetime64_any_dtype(x_timestamp):
            x_timestamp = pd.to_datetime(x_timestamp)
        if not pd.api.types.is_datetime64_any_dtype(y_timestamp):
            y_timestamp = pd.to_datetime(y_timestamp)

        t0 = time.time()
        pred = predictor.predict(
            df=x_df.reset_index(drop=True),
            x_timestamp=x_timestamp,
            y_timestamp=y_timestamp,
            pred_len=PRED_LEN,
            T=1.0, top_p=0.9, sample_count=4,  # 4 samples averaged
            verbose=False,
        )
        dt = time.time() - t0

        last_close = float(x_df["close"].iloc[-1])
        pred_close_final = float(pred["close"].iloc[-1])
        actual_close_final = float(y_truth["close"].iloc[-1])

        pred_ret = (pred_close_final / last_close) - 1.0
        actual_ret = (actual_close_final / last_close) - 1.0
        sign_match = (pred_ret > 0) == (actual_ret > 0)

        rows.append({
            "ticker": ticker,
            "anchor_date": x_df.index[-1].date().isoformat(),
            "last_close": round(last_close, 2),
            "fc_close": round(pred_close_final, 2),
            "actual_close": round(actual_close_final, 2),
            "fc_63d_ret_pct": round(pred_ret * 100, 2),
            "actual_63d_ret_pct": round(actual_ret * 100, 2),
            "sign_match": sign_match,
            "abs_err_pp": round(abs(pred_ret - actual_ret) * 100, 2),
            "inference_s": round(dt, 1),
        })
        print(f"[spike] {ticker}: fc={pred_ret*100:+.2f}%  "
              f"actual={actual_ret*100:+.2f}%  "
              f"sign_match={sign_match}  "
              f"err={abs(pred_ret-actual_ret)*100:.2f}pp  "
              f"t={dt:.1f}s")

    if not rows:
        print("[spike] no tickers ran — abort")
        return 1

    out = pd.DataFrame(rows)
    print("\n=== Spike summary ===")
    print(out.to_string(index=False))
    print()
    sign_rate = out["sign_match"].mean()
    mean_abs_err = out["abs_err_pp"].mean()
    max_abs_err = out["abs_err_pp"].max()
    print(f"sign agreement: {sign_rate*100:.0f}% ({int(out['sign_match'].sum())}/{len(out)})")
    print(f"mean |err|: {mean_abs_err:.2f}pp   max |err|: {max_abs_err:.2f}pp")
    print()
    # Killswitch
    passes = (
        sign_rate >= SIGN_THRESHOLD
        and mean_abs_err < MEAN_ERR_THRESHOLD_PP
        and max_abs_err < MAX_ERR_THRESHOLD_PP
    )
    if passes:
        print(f"[verdict] PASS at pred_len={PRED_LEN} — escalate to real factor build")
    else:
        print(f"[verdict] KILL at pred_len={PRED_LEN} — out-of-distribution / poor calibration")
        print(f"  thresholds: sign>={SIGN_THRESHOLD:.0%}  "
              f"mean_err<{MEAN_ERR_THRESHOLD_PP}pp  max_err<{MAX_ERR_THRESHOLD_PP}pp")

    out_path = REPO / "reports" / f"kronos_spike_summary_pl{PRED_LEN}.json"
    out.to_json(out_path, orient="records", indent=2)
    print(f"[spike] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
