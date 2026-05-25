"""Build a market-breadth regime gate from the broad-universe snapshot, to test
against the whippy single-SPY-SMA gate (the diagnosed H1-2025 whipsaw/crash-timing
leak — see project_regime_whipsaw_h1_2025).

Breadth_t = fraction of the ~2000 broad-universe names trading above their own
200-day SMA. Healthy market = broad participation. Hysteresis band avoids chop:
risk-OFF when breadth <= LO, risk-ON when breadth >= HI, hold in between. Output:
data/regime_breadth.json {YYYY-MM-DD: bool} for run_factor_backtest --regime-file.

Usage: uv run python scripts/research/breadth_gate.py [BROAD_SNAPSHOT_ID]
"""
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.storage.snapshot import load_snapshot  # noqa: E402

SNAP = sys.argv[1] if len(sys.argv) > 1 else "9f448161ca59e465"
SMA = 200
LO, HI = 0.45, 0.55     # hysteresis band on fraction-above-200SMA
KEY_DATES = ["2024-10-02", "2025-01-02", "2025-04-04", "2025-07-08"]  # the whipsaw + crash rebalances


def main():
    snap = load_snapshot(SNAP)
    closes = pd.DataFrame(
        {t: df["Close"].astype(float) for t, df in snap.price_data.items()
         if df is not None and not df.empty and "Close" in df.columns}
    ).sort_index()
    sma = closes.rolling(SMA, min_periods=SMA).mean()
    breadth = (closes >= sma).where(sma.notna()).mean(axis=1, skipna=True)  # frac above 200-SMA
    breadth = breadth.dropna()

    on, regime = False, {}
    for d, b in breadth.items():
        if on and b <= LO:
            on = False
        elif (not on) and b >= HI:
            on = True
        regime[d.date().isoformat()] = on

    out = ROOT / "data" / "regime_breadth.json"
    out.write_text(json.dumps(regime))
    print(f"breadth gate from {SNAP}: {closes.shape[1]} names, "
          f"{len(regime)} dated regime flags (hysteresis {LO}/{HI})")
    print(f"  risk-on days: {sum(regime.values())}/{len(regime)} "
          f"({100*sum(regime.values())/len(regime):.0f}%)")
    print("\nbreadth + gate at key rebalances (vs the SPY-75-SMA whipsaw):")
    bidx = breadth.index
    for k in KEY_DATES:
        a = pd.Timestamp(k)
        pos = bidx.searchsorted(a, side="right") - 1
        if pos < 0:
            print(f"  {k}: no breadth yet")
            continue
        d = bidx[pos]
        print(f"  {k}: breadth={breadth.iloc[pos]:.2f}  gate={'RISK-ON' if regime[d.date().isoformat()] else 'risk-off'}")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
