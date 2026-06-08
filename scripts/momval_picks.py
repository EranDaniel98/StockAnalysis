"""Momentum-Value "biggest-risers" book — daily picks.

A SECOND book alongside the risk-balanced production composite. The right-tail
research (project_factor_horizon_decomp / right_tail_variant) showed momentum
carries the biggest-riser signal (lift 2.08 vs the equal blend's 1.25) and that
quality/PEAD DILUTE it. This book is momentum 0.6 / value 0.4 (quality + PEAD
dropped) over the live PIT S&P 500 — tuned for UPSIDE precision at a 3-6 month
horizon, NOT risk-adjusted stability.

HONEST RISK (measured): vs the production blend this book has higher upside in
trends but deeper drawdowns (~-19% median / -24% worst vs -14% / -18%) and a
LOWER risk-adjusted alpha. Observe it; it is not a replacement for the
production book.

    uv run python -m scripts.momval_picks                 # today's picks
    uv run python -m scripts.momval_picks --as-of 2026-06-05 --top-n 24
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

logger = logging.getLogger("momval_picks")

OUTPUT = Path("reports") / "momval_picks_latest.json"
WEIGHTS = {"momentum": 0.6, "value": 0.4}


def _coerce(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f  # drop NaN


def build(as_of: pd.Timestamp, top_n: int, max_sector_pct: float | None) -> dict:
    from src.factors.pipeline import run_factor_picks

    res = run_factor_picks(
        as_of=as_of, top_n=top_n,
        composite_factors="mv", factor_weights=WEIGHTS,
        include_pead=False, sector_neutral_quality=False,
        min_overlap=1, max_sector_pct=max_sector_pct, min_history_days=504,
    )
    picks = []
    for _, r in res.top_n.iterrows():
        picks.append({
            "rank": int(r.get("rank")) if pd.notna(r.get("rank")) else None,
            "ticker": str(r.get("ticker")),
            "composite_z": _coerce(r.get("z_score")),
            "mom_rank": int(r["mom_rank"]) if pd.notna(r.get("mom_rank")) else None,
            "val_rank": int(r["val_rank"]) if pd.notna(r.get("val_rank")) else None,
            "sector": r.get("sector") if "sector" in res.top_n.columns else None,
        })
    return {
        "strategy": "momval_6_4",
        "label": "Momentum-Value (biggest-risers)",
        "as_of": as_of.date().isoformat(),
        "weights": WEIGHTS,
        "factors_used": res.factors_used,
        "universe_size": res.universe_size,
        "top_n": len(picks),
        "horizon_note": "Tuned for UPSIDE precision at a 3-6 month horizon. "
                        "Higher drawdowns than the production blend (research: "
                        "median maxDD ~-19% vs -14%). Observe, do not size as the core.",
        "picks": picks,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--as-of", default=None, help="YYYY-MM-DD (default: today UTC)")
    ap.add_argument("--top-n", type=int, default=24)
    ap.add_argument("--max-sector-pct", type=float, default=30.0,
                    help="per-sector cap as %% of top_n (None to disable)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    as_of = pd.Timestamp(args.as_of) if args.as_of else \
        pd.Timestamp(datetime.now(timezone.utc).date())
    payload = build(as_of, args.top_n, args.max_sector_pct)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    logger.info("MOMVAL 6/4 picks for %s (%d names, universe %d):",
                payload["as_of"], payload["top_n"], payload["universe_size"])
    for p in payload["picks"][:12]:
        logger.info("  #%-2s %-6s z=%s  mom#%s val#%s",
                    p["rank"], p["ticker"],
                    f"{p['composite_z']:+.2f}" if p["composite_z"] is not None else "—",
                    p["mom_rank"], p["val_rank"])
    logger.info("wrote %s", OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
