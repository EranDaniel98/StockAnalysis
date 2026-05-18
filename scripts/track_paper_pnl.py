"""Realized P&L tracker — compare paper account to backtest predictions.

Pulls the Alpaca portfolio history, the SPY benchmark over the same
window, and the latest production backtest's expected alpha. Computes:

  * Realized total return (strategy vs SPY)
  * Realized alpha = strategy_return - spy_return
  * Backtest-implied alpha scaled to the elapsed period
  * Gap = realized - predicted

Persists daily snapshots to ``data/paper_pnl/YYYY-MM-DD.json`` so a
weekly trend builds up. The point: detect divergence between paper
P&L and backtest predictions BEFORE it gets large. If realized alpha
diverges from predicted by >half-window over multiple weeks, the
backtest is not a useful predictor and either (a) the strategy is
broken, (b) the regime shifted, or (c) the data/cost model in the
backtest is wrong.

Usage
-----

  uv run python -m scripts.track_paper_pnl \\
      --period 1M --baseline-window be2f46f43e6e9d0e

Optional ``--period`` (Alpaca shorthand: 1D, 1W, 1M, 3M, 6M, 1A) sets
how far back to read. The backtest comparison is scaled to the
elapsed days in the chosen period.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("track_paper_pnl")

# The production config's most recent bull-window backtest. Source of
# the predicted alpha used as the comparison baseline. Update when the
# config materially changes.
DEFAULT_BACKTEST_PATH = Path("reports/ab_raw_be2f46.json")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--period", default="1M",
                   help="Alpaca portfolio-history period: 1D / 1W / 1M "
                        "/ 3M / 6M / 1A. Default 1M.")
    p.add_argument("--backtest-path",
                   default=str(DEFAULT_BACKTEST_PATH),
                   help="Path to the backtest JSON whose alpha is the "
                        "comparison baseline. Default points at the "
                        "production d05_r63 + PEAD on the bull window.")
    p.add_argument("--output-dir", default="data/paper_pnl",
                   help="Where the daily snapshot JSON lands.")
    p.add_argument("--quiet", action="store_true",
                   help="Suppress the markdown table — only set exit "
                        "code and a one-line summary.")
    return p.parse_args()


def _spy_total_return(start: pd.Timestamp, end: pd.Timestamp) -> Optional[float]:
    """SPY total return over [start, end] from yfinance.

    Returns None if data is unavailable. Both timestamps are coerced to
    date-only so weekends / time-of-day misalignment doesn't matter.
    """
    from src.config_loader import Config
    from src.data.cache import DataCache
    from src.data.fetcher import DataFetcher

    config = Config()
    cache = DataCache(
        expiry_hours=config.get("data", "cache_expiry_hours", default=24),
        market_hours_expiry_minutes=config.get(
            "data", "market_hours_cache_minutes", default=5,
        ),
    )
    fetcher = DataFetcher(config, cache)
    raw = fetcher.fetch_batch(["SPY"]).get("SPY")
    if raw is None or raw.empty:
        return None
    # The fetcher caches at 5y. Restrict to the window. Convert tz-aware
    # indices to tz-naive so the comparison doesn't blow up.
    idx = raw.index
    if getattr(idx, "tz", None) is not None:
        raw = raw.copy()
        raw.index = raw.index.tz_localize(None)
    start_n = pd.Timestamp(start).normalize().tz_localize(None) \
        if pd.Timestamp(start).tz is not None else pd.Timestamp(start).normalize()
    end_n = pd.Timestamp(end).normalize().tz_localize(None) \
        if pd.Timestamp(end).tz is not None else pd.Timestamp(end).normalize()
    window = raw[(raw.index >= start_n) & (raw.index <= end_n)]
    if len(window) < 2:
        return None
    start_close = float(window["Close"].iloc[0])
    end_close = float(window["Close"].iloc[-1])
    if start_close <= 0:
        return None
    return end_close / start_close - 1.0


def _load_backtest(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(
            f"Backtest baseline missing: {path}. Run "
            "scripts.run_factor_backtest first or pass --backtest-path."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _alpaca_history(period: str) -> dict:
    """Pull Alpaca's portfolio history for the period. Wrapped in a try
    to surface a clean error if Alpaca isn't reachable."""
    from src.execution.alpaca import AlpacaClient
    from src.execution.safety_gates import (
        CircuitBreakerThresholds, TradingSafetyGate,
    )
    gate = TradingSafetyGate(
        trading_enabled=False,  # read-only
        thresholds=CircuitBreakerThresholds(),
    )
    client = AlpacaClient(safety_gate=gate)
    return client.get_portfolio_history(period=period, timeframe="1D")


def _build_snapshot(args: argparse.Namespace) -> dict:
    history = _alpaca_history(args.period)
    timestamps = history["timestamps"]
    equities = history["equity"]
    if not timestamps or not equities:
        raise SystemExit(
            f"Alpaca portfolio history returned empty for period={args.period}."
        )

    start_ts = pd.Timestamp(timestamps[0], unit="s", tz="UTC")
    end_ts = pd.Timestamp(timestamps[-1], unit="s", tz="UTC")
    start_eq = float(equities[0])
    end_eq = float(equities[-1])
    if start_eq <= 0:
        raise SystemExit(
            f"Alpaca history start equity = {start_eq}; nothing to "
            "compute against."
        )
    strategy_return = end_eq / start_eq - 1.0
    elapsed_days = max(1, (end_ts - start_ts).days)

    spy_return = _spy_total_return(start_ts, end_ts)
    if spy_return is None:
        logger.warning(
            "SPY benchmark unavailable; skipping alpha computation."
        )
        realized_alpha = None
    else:
        realized_alpha = strategy_return - spy_return

    bt = _load_backtest(Path(args.backtest_path))
    bt_alpha_pct = float(bt.get("alpha_vs_spy_pct") or 0.0)
    bt_window_start = pd.Timestamp(
        bt["snapshot_manifest"]["window_start"]
    )
    bt_window_end = pd.Timestamp(
        bt["snapshot_manifest"]["window_end"]
    )
    bt_window_days = max(1, (bt_window_end - bt_window_start).days)
    # Scale the backtest's total-window alpha to the elapsed paper
    # period. Linear scaling is the simple model — assumes alpha
    # accrues at a constant rate. For multi-month windows this is
    # noisy but fine as a sanity baseline.
    scaled_predicted_alpha = (bt_alpha_pct / 100.0) * (
        elapsed_days / bt_window_days
    )

    gap = (
        realized_alpha - scaled_predicted_alpha
        if realized_alpha is not None else None
    )
    if gap is None:
        verdict = "spy_data_missing"
    elif gap > 0.005:  # +0.5pp ahead
        verdict = "ahead_of_backtest"
    elif gap < -0.01:  # -1pp behind
        verdict = "behind_backtest"
    else:
        verdict = "on_track"

    return {
        "as_of": datetime.now(timezone.utc).date().isoformat(),
        "period": args.period,
        "elapsed_days": elapsed_days,
        "strategy_window": {
            "start": start_ts.isoformat(),
            "end": end_ts.isoformat(),
            "start_equity": start_eq,
            "end_equity": end_eq,
        },
        "strategy_return_pct": round(strategy_return * 100, 3),
        "spy_return_pct": (
            round(spy_return * 100, 3) if spy_return is not None else None
        ),
        "realized_alpha_pct": (
            round(realized_alpha * 100, 3)
            if realized_alpha is not None else None
        ),
        "backtest_baseline": {
            "path": str(args.backtest_path),
            "strategy_label": bt.get("strategy"),
            "window_alpha_pct": bt_alpha_pct,
            "window_days": bt_window_days,
            "scaled_alpha_for_period_pct": round(scaled_predicted_alpha * 100, 3),
        },
        "gap_vs_backtest_pct": (
            round(gap * 100, 3) if gap is not None else None
        ),
        "verdict": verdict,
    }


def _render_markdown(s: dict) -> str:
    lines = []
    verdict_label = {
        "ahead_of_backtest": "AHEAD",
        "on_track": "ON-TRACK",
        "behind_backtest": "BEHIND",
        "spy_data_missing": "SPY-DATA-MISSING",
    }.get(s["verdict"], s["verdict"])
    lines.append(f"# Paper P&L vs Backtest — [{verdict_label}]")
    lines.append("")
    lines.append(f"**As-of:** {s['as_of']}")
    lines.append(f"**Period:** {s['period']} ({s['elapsed_days']} days elapsed)")
    lines.append("")
    w = s["strategy_window"]
    lines.append(
        f"**Equity:** ${w['start_equity']:,.2f} -> "
        f"${w['end_equity']:,.2f}  "
        f"({s['strategy_return_pct']:+.2f}%)"
    )
    if s["spy_return_pct"] is not None:
        lines.append(
            f"**SPY:**    {s['spy_return_pct']:+.2f}% over same window"
        )
        lines.append(
            f"**Realized alpha:** {s['realized_alpha_pct']:+.3f}pp"
        )
    bt = s["backtest_baseline"]
    lines.append("")
    lines.append(
        f"**Backtest baseline:** {bt['strategy_label']} | "
        f"{bt['window_alpha_pct']:+.2f}% alpha over {bt['window_days']}d "
        f"-> scaled to {bt['scaled_alpha_for_period_pct']:+.3f}pp for "
        f"this {s['elapsed_days']}d window"
    )
    if s["gap_vs_backtest_pct"] is not None:
        lines.append(
            f"**Gap (realized - scaled-backtest):** "
            f"{s['gap_vs_backtest_pct']:+.3f}pp"
        )
    return "\n".join(lines)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = _parse_args()

    snapshot = _build_snapshot(args)

    if not args.quiet:
        print(_render_markdown(snapshot))

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{snapshot['as_of']}.json"
    out_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    logger.info("Wrote daily snapshot to %s", out_path)
    summary = (
        f"Paper P&L: {snapshot['verdict'].upper()} | "
        f"realized {snapshot['realized_alpha_pct']}% vs predicted "
        f"{snapshot['backtest_baseline']['scaled_alpha_for_period_pct']}%"
        if snapshot["realized_alpha_pct"] is not None
        else f"Paper P&L: SPY DATA MISSING ({snapshot['verdict']})"
    )
    logger.info(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
