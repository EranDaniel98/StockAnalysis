"""Kronos proper test — multi-anchor × multi-ticker × multi-horizon grid.

Replaces the under-powered single-anchor spike. Tests whether Kronos has
directional skill or magnitude calibration on US daily bars at horizons
relevant to {daily trade (5d), monthly hold (21d)}.

Design
------
* 1 snapshot (1dd88cad8e1f7534, 2024-2026 bull window) — strongest
  signal-to-noise for the calibration question.
* 20 anchor dates spread across the valid range (lookback=400 forward
  enough; anchor + max_horizon must fit in snapshot).
* 50 large-cap tickers across sectors.
* Horizons {5, 21} trading days.
* Baseline: predict-zero return (the honest null on a stochastic process).
* Stats: binomial CI on sign rate, paired comparison vs baseline MAE,
  Wilcoxon signed-rank (non-parametric, robust to outliers).

Killswitch for adoption (any horizon must satisfy ALL):
* Sign rate strictly > 50% with 95% binomial CI lower bound > 50%
* Kronos MAE strictly < predict-zero MAE with Wilcoxon p < 0.05
* No order-of-magnitude pathologies (|fc| < 5 × realized std)

Otherwise: no measurable edge over null at the tested horizons.
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sps

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "vendor" / "kronos"))

from model import Kronos, KronosTokenizer, KronosPredictor  # noqa: E402

SNAPSHOT = "1dd88cad8e1f7534"
LOOKBACK = 400
HORIZONS = [5, 21]
N_ANCHORS = 20
SAMPLE_COUNT = 4  # samples per inference averaged inside Kronos

# 50 large-cap tickers across sectors. All have continuous history
# through the 2024-2026 window in our snapshot.
TICKERS = [
    # mega-cap tech (10)
    "NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA",
    "ADBE", "CRM", "ORCL",
    # banks / financials (8)
    "JPM", "BAC", "WFC", "GS", "MS", "C", "BLK", "AXP",
    # energy (5)
    "XOM", "CVX", "COP", "EOG", "SLB",
    # consumer staples (6)
    "WMT", "COST", "PG", "KO", "PEP", "PM",
    # consumer discretionary (5)
    "HD", "LOW", "MCD", "NKE", "SBUX",
    # healthcare (6)
    "JNJ", "PFE", "UNH", "MRK", "ABBV", "LLY",
    # industrial (5)
    "CAT", "GE", "HON", "UPS", "BA",
    # utilities + comms (5)
    "NEE", "SO", "DUK", "VZ", "T",
]
assert len(TICKERS) == 50, f"want 50 tickers got {len(TICKERS)}"


@dataclass
class Row:
    horizon: int
    ticker: str
    anchor: str
    last_close: float
    realized_ret: float
    kronos_ret: float
    zero_ret: float = 0.0

    @property
    def kronos_err(self) -> float:
        return abs(self.kronos_ret - self.realized_ret)

    @property
    def zero_err(self) -> float:
        return abs(self.zero_ret - self.realized_ret)

    @property
    def kronos_sign_match(self) -> bool:
        if self.realized_ret == 0:
            return self.kronos_ret == 0
        return (self.kronos_ret > 0) == (self.realized_ret > 0)


def load_prices() -> pd.DataFrame:
    return pd.read_parquet(REPO / "data" / "snapshots" / SNAPSHOT / "prices.parquet")


def slice_ticker(prices_wide: pd.DataFrame, ticker: str) -> pd.DataFrame | None:
    df = prices_wide[prices_wide["ticker"] == ticker].copy()
    if df.empty:
        return None
    df = df.sort_values("date").set_index("date")
    df = df.rename(columns=str.lower)
    df["amount"] = df["close"] * df["volume"]
    return df[["open", "high", "low", "close", "volume", "amount"]]


def pick_anchor_indices(n_rows: int, n_anchors: int, max_horizon: int) -> list[int]:
    """Evenly spaced anchor indices in the valid range.

    Valid = lookback <= idx <= n_rows - max_horizon - 1, so each anchor
    has both a full lookback AND a full forward window for the largest
    horizon under test.
    """
    lo = LOOKBACK
    hi = n_rows - max_horizon - 1
    if hi <= lo:
        raise ValueError(f"snapshot too small: lo={lo} hi={hi} rows={n_rows}")
    return list(np.linspace(lo, hi, n_anchors).astype(int))


def main() -> int:
    print(f"[proper] snapshot={SNAPSHOT}  lookback={LOOKBACK}  "
          f"horizons={HORIZONS}  anchors={N_ANCHORS}  tickers={len(TICKERS)}")

    prices_wide = load_prices()

    t0 = time.time()
    tokenizer = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
    model = Kronos.from_pretrained("NeoQuasar/Kronos-small")
    predictor = KronosPredictor(model, tokenizer, max_context=512)
    print(f"[proper] model loaded in {time.time()-t0:.1f}s on {predictor.device}")

    # Index ticker frames once.
    frames: dict[str, pd.DataFrame] = {}
    for t in TICKERS:
        f = slice_ticker(prices_wide, t)
        if f is None or len(f) < LOOKBACK + max(HORIZONS) + 5:
            print(f"[proper] {t}: insufficient history, skipping")
            continue
        frames[t] = f
    if not frames:
        print("[proper] no usable tickers")
        return 1

    # Use the first frame's date axis for anchor selection (all snapshots
    # share the same calendar by construction).
    sample_frame = next(iter(frames.values()))
    anchors_idx = pick_anchor_indices(len(sample_frame), N_ANCHORS, max(HORIZONS))
    anchor_dates = [sample_frame.index[i] for i in anchors_idx]
    print(f"[proper] anchor range: {anchor_dates[0].date()} .. {anchor_dates[-1].date()}")

    rows: list[Row] = []
    total_runs = len(HORIZONS) * len(anchors_idx) * len(frames)
    done = 0
    t_grid_start = time.time()

    for horizon in HORIZONS:
        print(f"\n[proper] === horizon={horizon}d ===")
        for ai, idx in enumerate(anchors_idx):
            anchor = sample_frame.index[idx]
            anchor_iso = anchor.date().isoformat()
            t_anchor = time.time()
            for ticker, frame in frames.items():
                if idx + horizon >= len(frame):
                    continue
                x_df = frame.iloc[idx - LOOKBACK:idx].copy()
                y_truth = frame.iloc[idx:idx + horizon].copy()
                last_close = float(x_df["close"].iloc[-1])
                actual_close = float(y_truth["close"].iloc[-1])
                actual_ret = (actual_close / last_close) - 1.0

                x_ts = pd.Series(x_df.index)
                y_ts = pd.Series(y_truth.index)

                pred = predictor.predict(
                    df=x_df.reset_index(drop=True),
                    x_timestamp=x_ts, y_timestamp=y_ts,
                    pred_len=horizon, T=1.0, top_p=0.9,
                    sample_count=SAMPLE_COUNT, verbose=False,
                )
                pred_close = float(pred["close"].iloc[-1])
                kronos_ret = (pred_close / last_close) - 1.0

                rows.append(Row(
                    horizon=horizon, ticker=ticker, anchor=anchor_iso,
                    last_close=round(last_close, 4),
                    realized_ret=round(actual_ret, 6),
                    kronos_ret=round(kronos_ret, 6),
                ))
                done += 1
            elapsed = time.time() - t_anchor
            est_total = (time.time() - t_grid_start) / done * total_runs
            remaining = est_total - (time.time() - t_grid_start)
            print(f"[proper] h={horizon} anchor {ai+1}/{N_ANCHORS} "
                  f"({anchor_iso}) done={done}/{total_runs} "
                  f"anchor_time={elapsed:.1f}s eta={remaining/60:.1f}min")

    print(f"\n[proper] inference complete: {len(rows)} rows in "
          f"{(time.time()-t_grid_start)/60:.1f}min")

    df_rows = pd.DataFrame([r.__dict__ for r in rows])
    df_rows["kronos_err"] = (df_rows["kronos_ret"] - df_rows["realized_ret"]).abs()
    df_rows["zero_err"] = df_rows["realized_ret"].abs()
    df_rows["kronos_sign_match"] = (
        (df_rows["kronos_ret"] > 0) == (df_rows["realized_ret"] > 0)
    )
    df_rows["zero_sign_match"] = df_rows["realized_ret"] == 0  # always False

    out_dir = REPO / "reports"
    out_dir.mkdir(exist_ok=True)
    rows_path = out_dir / "kronos_proper_rows.json"
    df_rows.to_json(rows_path, orient="records", indent=2)
    print(f"[proper] wrote {rows_path}")

    # Per-horizon stats.
    summary: dict = {"snapshot": SNAPSHOT, "horizons": {}}
    print("\n=== SUMMARY ===")
    print(f"{'horizon':>7} {'n':>5} {'sign%':>7} {'ci95':>15} "
          f"{'k_MAE':>8} {'0_MAE':>8} {'wilcoxon_p':>12} {'verdict':>10}")
    for h in HORIZONS:
        sub = df_rows[df_rows["horizon"] == h]
        n = len(sub)
        n_sign = int(sub["kronos_sign_match"].sum())
        sign_rate = n_sign / n
        # Binomial 95% CI (Wilson)
        ci_lo, ci_hi = sps.binomtest(n_sign, n, p=0.5).proportion_ci(method="wilson")
        k_mae = float(sub["kronos_err"].mean()) * 100
        z_mae = float(sub["zero_err"].mean()) * 100
        # Wilcoxon: H0 = kronos_err == zero_err
        try:
            w_stat, w_p = sps.wilcoxon(
                sub["kronos_err"], sub["zero_err"], alternative="less",
            )
        except ValueError as e:
            w_p = float("nan")

        ci_str = f"[{ci_lo*100:.1f}, {ci_hi*100:.1f}]"
        sign_better = ci_lo > 0.50
        mae_better = (k_mae < z_mae) and (not np.isnan(w_p) and w_p < 0.05)
        passes = sign_better and mae_better
        verdict = "EDGE" if passes else "NO EDGE"
        print(f"{h:>7} {n:>5} {sign_rate*100:>6.1f}% {ci_str:>15} "
              f"{k_mae:>7.2f}p {z_mae:>7.2f}p {w_p:>12.4f} {verdict:>10}")
        summary["horizons"][h] = {
            "n": int(n),
            "sign_rate": round(sign_rate, 4),
            "sign_ci95": [round(ci_lo, 4), round(ci_hi, 4)],
            "kronos_mae_pp": round(k_mae, 4),
            "zero_mae_pp": round(z_mae, 4),
            "wilcoxon_p_less": None if np.isnan(w_p) else round(float(w_p), 6),
            "edge": bool(passes),
        }

    summary_path = out_dir / "kronos_proper_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[proper] wrote {summary_path}")

    any_edge = any(h["edge"] for h in summary["horizons"].values())
    print()
    if any_edge:
        edges = [k for k, v in summary["horizons"].items() if v["edge"]]
        print(f"[verdict] EDGE detected at horizons {edges} — escalate")
    else:
        print(f"[verdict] NO EDGE at horizons {HORIZONS} — Kronos does not "
              f"beat predict-zero baseline at the tested horizons on this "
              f"snapshot with this universe and anchor schedule.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
