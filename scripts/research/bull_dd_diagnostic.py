"""Bull-window DD diagnostic for d03 vs d05.

Memory `project_d03_concentration` shows top-3% (d03) widens 2024-26
max DD from -14.53% (d05) to -19.21%. Question: is the wider DD
explained by mechanical concentration (more beta, same direction as
the market correction) or by idiosyncratic name selection (bad
picks specifically)?

If mechanical -> can't "fix" without de-risking the strategy.
If idiosyncratic -> name selection at the rebalance preceding the DD
                    was a real miss; mitigations possible.

Method (no position-reconstruction needed):
1. Load equity curves for d05 (top_5%) and d03 (top_3%) from the
   saved ablations.
2. Load SPY benchmark from the same snapshot.
3. Identify the DD trough date for each. Compute the DD window
   (peak->trough) and SPY's behavior over the same window.
4. Fit a simple beta of strategy daily returns vs SPY over the full
   window. Then ask: does (strategy DD) ~= (beta * SPY DD) ?
   - YES (within +/-1pp) -> mechanical / systematic.
   - NO (worse) -> idiosyncratic excess loss.
5. Surface verdict + mitigation options.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
BASE = REPO / "data" / "backtests" / "post_24of24"

D05_PATH = BASE / "2024_2026_full_stack.json"
D03_PATH = BASE / "ablation_2024_2026_top3pct.json"
SNAPSHOT_DIR = REPO / "data" / "snapshots" / "1dd88cad8e1f7534"


def load_curve(path: Path) -> pd.DataFrame:
    j = json.loads(path.read_text())
    eq = pd.DataFrame(j["equity_curve"], columns=["date", "eq"])
    eq["date"] = pd.to_datetime(eq["date"])
    eq = eq.sort_values("date").set_index("date")
    eq["ret"] = eq["eq"].pct_change()
    eq["hwm"] = eq["eq"].cummax()
    eq["dd"] = eq["eq"] / eq["hwm"] - 1
    return eq


def find_dd_window(eq: pd.DataFrame) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Peak->trough dates spanning the max drawdown."""
    trough = eq["dd"].idxmin()
    # Walk back to find the peak that defined the DD.
    peak = eq.loc[:trough, "hwm"].idxmax()
    # Refine peak: the most recent date BEFORE trough where eq == hwm.
    pre = eq.loc[:trough]
    matches = pre[pre["eq"] == pre["hwm"]]
    if len(matches) > 0:
        peak = matches.index[-1]
    return peak, trough


def main() -> int:
    d05 = load_curve(D05_PATH)
    d03 = load_curve(D03_PATH)

    spy = pd.read_parquet(SNAPSHOT_DIR / "spy.parquet")
    if "date" in spy.columns:
        spy["date"] = pd.to_datetime(spy["date"]).dt.tz_localize(None)
        spy = spy.sort_values("date").set_index("date")
    else:
        spy.index = pd.to_datetime(spy.index).tz_localize(None)
        spy = spy.sort_index()
    # Strip time-of-day so SPY index aligns cleanly with equity-curve dates.
    spy.index = spy.index.normalize()
    spy["ret"] = spy["Close"].pct_change()
    spy["hwm"] = spy["Close"].cummax()
    spy["dd"] = spy["Close"] / spy["hwm"] - 1

    # Restrict SPY to backtest window.
    win_lo = max(d05.index.min(), d03.index.min())
    win_hi = min(d05.index.max(), d03.index.max())
    spy_win = spy.loc[win_lo:win_hi].copy()
    spy_win["hwm"] = spy_win["Close"].cummax()
    spy_win["dd"] = spy_win["Close"] / spy_win["hwm"] - 1

    print(f"Window: {win_lo.date()} .. {win_hi.date()}")
    print()
    for name, eq, price_col in [
        ("d05 (top 5%)", d05, "eq"),
        ("d03 (top 3%)", d03, "eq"),
        ("SPY", spy_win, "Close"),
    ]:
        if eq.empty:
            print(f"{name:>14}: EMPTY frame")
            continue
        trough_idx = eq["dd"].idxmin()
        pre = eq.loc[:trough_idx]
        matches = pre[pre[price_col] == pre["hwm"]]
        peak = matches.index[-1] if len(matches) else pre[price_col].idxmax()
        max_dd = float(eq["dd"].min())
        days = (trough_idx - peak).days
        print(f"{name:>14}: peak {peak.date()}  trough {trough_idx.date()}  "
              f"DD {max_dd*100:+.2f}%  ({days} cal days)")

    # Focus: d03 drawdown window
    d03_peak, d03_trough = find_dd_window(d03)
    print()
    print(f"=== d03 drawdown window: {d03_peak.date()} -> {d03_trough.date()} ===")
    print()

    win = (d03_peak, d03_trough)
    d05_in = d05.loc[win[0]:win[1]]
    d03_in = d03.loc[win[0]:win[1]]
    spy_in = spy_win.loc[win[0]:win[1]]

    def total_drop(eq, col):
        first, last = eq[col].iloc[0], eq[col].iloc[-1]
        return (last / first - 1) * 100

    spy_drop = total_drop(spy_in, "Close")
    d05_drop = total_drop(d05_in, "eq")
    d03_drop = total_drop(d03_in, "eq")
    print(f"  SPY  drop over window: {spy_drop:+.2f}%")
    print(f"  d05  drop over window: {d05_drop:+.2f}%")
    print(f"  d03  drop over window: {d03_drop:+.2f}%")
    print()

    # Beta: full-window regression of strategy returns on SPY returns
    full = pd.concat({"d05": d05["ret"], "d03": d03["ret"],
                      "spy": spy_win["ret"]}, axis=1).dropna()
    for name in ("d05", "d03"):
        cov = np.cov(full[name], full["spy"])
        beta = cov[0, 1] / cov[1, 1]
        # Expected DD given SPY DD and beta (if betas were stable)
        expected = beta * spy_drop
        excess = (d05_drop if name == "d05" else d03_drop) - expected
        print(f"  {name} beta vs SPY (full window): {beta:.3f}")
        print(f"       expected DD (beta * spy_drop): {expected:+.2f}%")
        actual = d05_drop if name == "d05" else d03_drop
        print(f"       actual DD: {actual:+.2f}%  excess: {excess:+.2f}pp")
        print()

    print("=== Verdict ===")
    print()
    cov_d03 = np.cov(full["d03"], full["spy"])
    beta_d03 = cov_d03[0, 1] / cov_d03[1, 1]
    cov_d05 = np.cov(full["d05"], full["spy"])
    beta_d05 = cov_d05[0, 1] / cov_d05[1, 1]
    print(f"d03 beta = {beta_d03:.3f}  vs  d05 beta = {beta_d05:.3f} "
          f"(delta {(beta_d03-beta_d05):+.3f})")
    expected_excess = (beta_d03 - beta_d05) * spy_drop
    actual_excess = d03_drop - d05_drop
    print(f"  Higher beta from concentration alone predicts d03 drops "
          f"{expected_excess:+.2f}pp more than d05.")
    print(f"  Actual d03 - d05 in DD window: {actual_excess:+.2f}pp.")
    residual = actual_excess - expected_excess
    print(f"  Unexplained (idiosyncratic) excess: {residual:+.2f}pp")
    print()
    if abs(residual) < 1.0:
        print("[verdict] DD widening is MECHANICAL — explained by higher")
        print("          beta from concentration. Can't fix without")
        print("          de-risking the strategy itself.")
    elif residual < -1.0:
        print("[verdict] d03 dropped MORE than beta-scaled SPY would predict.")
        print("          IDIOSYNCRATIC name selection at the pre-DD rebalance")
        print("          was a real miss. Worth investigating which names.")
    else:
        print("[verdict] d03 dropped LESS than its beta would predict.")
        print("          The concentration actually picked DEFENSIVELY into")
        print("          the correction. Beta-only model underestimates.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
