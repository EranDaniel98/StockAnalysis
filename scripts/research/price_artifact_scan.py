# /// script
# dependencies = ["pandas", "numpy"]
# ///
"""Flag corporate-action price artifacts in snapshot prices.

Polygon returns one ticker's whole history even across ticker REUSE/renames
(META = Meta Materials penny stock until Meta Platforms took the ticker from
FB in 2022-06; GEN = phantom early ticker then Gen Digital 2022-11), splits/
spinoffs (DD/DOW), and delistings-to-$0 (SBNY/SOLS). When a snapshot's fetch
window SPANS the event, two price levels (or a $0 + a stray tick) get stitched
into one series -> a physically-impossible single-day move. The momentum factor
then reads it as astronomical 12-1 momentum and the backtest BUYS the artifact.

This flags the signature: |daily move| over a threshold, or a large internal
date gap. Use it to audit snapshots and to seed the live-path guard.

    uv run python -m scripts.research.price_artifact_scan <snapshot_id> [<id> ...]
    uv run python -m scripts.research.price_artifact_scan --all
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SNAP_DIR = ROOT / "data" / "snapshots"

MAX_DAY_MOVE_PCT = 80.0   # |close-to-close| above this = not a real equity move
MAX_GAP_DAYS = 45         # internal calendar gap above this = a stitched series


def scan_snapshot(snap: str) -> list[dict]:
    p = SNAP_DIR / snap / "prices.parquet"
    if not p.exists():
        return []
    df = pd.read_parquet(p).sort_values(["ticker", "date"])
    out: list[dict] = []
    for t, g in df.groupby("ticker"):
        c = g["Close"].values
        c = c[c > 0]
        dts = pd.to_datetime(g["date"])
        if len(c) < 5:
            continue
        dr = np.diff(c) / c[:-1]
        max_move = float(np.nanmax(np.abs(dr)) * 100)
        max_gap = int(dts.diff().dt.days.max())
        if max_move > MAX_DAY_MOVE_PCT or max_gap > MAX_GAP_DAYS:
            i = int(np.nanargmax(np.abs(dr)))
            out.append({
                "ticker": t, "max_move_pct": round(max_move),
                "max_gap_days": max_gap, "n": len(c),
                "jump_from": round(float(c[i]), 2), "jump_to": round(float(c[i + 1]), 2),
            })
    return out


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: price_artifact_scan.py <snapshot_id> ... | --all")
        return 2
    snaps = ([d.name for d in SNAP_DIR.iterdir() if d.is_dir()]
             if argv[0] == "--all" else argv)
    total = 0
    for snap in snaps:
        bad = scan_snapshot(snap)
        total += len(bad)
        if bad:
            names = ", ".join(f"{b['ticker']}({b['max_move_pct']}%/{b['max_gap_days']}d)" for b in bad)
            print(f"{snap}: {len(bad)} flagged -> {names}")
    print(f"\n{total} artifact-flags across {len(snaps)} snapshot(s). "
          f"Thresholds: |day move|>{MAX_DAY_MOVE_PCT}% or gap>{MAX_GAP_DAYS}d.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
