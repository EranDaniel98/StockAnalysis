"""Today's composite factor picks.

Generates the top-N names by the m+q+v composite factor for the
current trading day. Thin wrapper around
``src.factors.pipeline.run_factor_picks`` — the single source of truth
for the composite-factor pipeline shared with the CLI's
``factor-picks`` command and any future API endpoint.

Recommended deployment config (per
`reports/factor_strategy_report_2026_05_16.md`):

  uv run python -m scripts.daily_factor_picks \\
      --top-n 24 \\
      --output-dir data/daily_picks/

24 names = top 5% of S&P 500. Rebalance quarterly (every ~63 trading
days) for the live strategy — don't trade these picks daily.

This script is read-only and DOES NOT place orders. Hand the output
to the paper-trading runner or review by eye before any execution.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.factors.pipeline import FactorPicksResult, run_factor_picks

logger = logging.getLogger("daily_factor_picks")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--top-n", type=int, default=24,
                   help="Number of picks (default 24 = top 5%% of ~500).")
    p.add_argument("--snapshot-id", default=None,
                   help="Use a frozen snapshot for prices (deterministic) "
                        "instead of pulling fresh from yfinance.")
    p.add_argument("--as-of", default=None,
                   help="As-of date (YYYY-MM-DD). Default = today.")
    p.add_argument("--output-dir", default="data/daily_picks",
                   help="Where to write the JSON.")
    p.add_argument("--include-pead", action=argparse.BooleanOptionalAction,
                   default=True,
                   help="Include the PEAD factor in the composite. "
                        "Validated 2026-05-18: +2.53pp avg α across 3 "
                        "windows, tighter drawdowns. ON by default; pass "
                        "--no-include-pead to disable (e.g., debugging "
                        "without the earnings cache).")
    p.add_argument("--earnings-cache-dir", default="data/earnings_history",
                   help="Where to cache per-ticker earnings parquets so "
                        "subsequent --include-pead runs are fast.")
    p.add_argument("--max-sector-pct", type=float, default=30.0,
                   help="Per-sector cap as %% of top_n (default 30). 100 or "
                        "negative disables the cap (legacy naive top-N).")
    p.add_argument("--trend-gate", action=argparse.BooleanOptionalAction,
                   default=True,
                   help="When SPY closes below its --trend-entry-sma, emit "
                        "empty picks (skip the rebalance). On by default. "
                        "Backed by the 2026-05-18 asymmetric-filter backtest: "
                        "75-SMA improves 2022-2024 alpha by +10.87pp vs the "
                        "old 200-SMA filter while staying bit-identical on "
                        "the 2024-2026 window. Pass --no-trend-gate to "
                        "disable.")
    p.add_argument("--trend-entry-sma", type=int, default=75,
                   help="SMA window for --trend-gate (default 75 td). "
                        "Calibrated by the asymmetric-filter sweep: 75 is "
                        "the most aggressive setting that still ignores the "
                        "Aug-2024 Japan-carry single-day spike.")
    p.add_argument("--vix-gate", action="store_true",
                   help="When today's VIX trailing 252d percentile is at or "
                        "above --vix-cutoff, return an empty picks list "
                        "(skip the rebalance). Motivated by the 2026-05-18 "
                        "regime IC report showing fundamental IC degrades "
                        "3.5x in high_vix. Off by default until backtest-"
                        "validated.")
    p.add_argument("--vix-cutoff", type=float, default=0.80,
                   help="VIX-percentile cutoff for --vix-gate (default 0.80).")
    p.add_argument("--vix-window", type=int, default=252,
                   help="Rolling window for --vix-gate (default 252 td).")
    p.add_argument("--long-short", action="store_true",
                   help="Emit BOTH long (top-N composite) and short "
                        "(bottom-N composite) sets. Picks JSON gains a "
                        "'shorts' key. paper_trade_factor_picks --long-short "
                        "consumes both. Off by default; the long-only path "
                        "remains the production default.")
    p.add_argument("--short-n", type=int, default=None,
                   help="Number of shorts to emit when --long-short. "
                        "Defaults to --top-n for a balanced book.")
    p.add_argument("--hysteresis-bonus", type=float, default=0.75,
                   help="Stickiness for previously-held names as a "
                        "fraction of --top-n. 0.0 disables (pure rank). "
                        "0.75 default = held name keeps its slot if its "
                        "fresh composite rank stays within top-N×1.75. "
                        "Validated 2026-05-18 against d05_r63+PEAD: "
                        "+4.31pp avg α cross-window vs no hysteresis, "
                        "stress-window DD improves -15.41%% -> -8.24%%. "
                        "Picks from yesterday's `--output-dir` are loaded "
                        "automatically.")
    p.add_argument("--sector-neutral-quality",
                   action=argparse.BooleanOptionalAction,
                   default=True,
                   help="Rank quality WITHIN sector instead of "
                        "cross-sectional. On by default since 2026-05-18; "
                        "validated +4.93pp avg α cross-window stacked with "
                        "hysteresis. Pass --no-sector-neutral-quality to "
                        "revert to cross-sectional quality.")
    return p.parse_args()


def _render_markdown(picks: pd.DataFrame, as_of: pd.Timestamp,
                     total_universe: int) -> str:
    lines = []
    lines.append(f"# Composite Factor Picks — {as_of.date().isoformat()}\n")
    lines.append(f"**Universe:** PIT S&P 500, {total_universe} eligible names")
    lines.append(f"**Strategy:** equal-weight rank-blend of momentum + quality + value")
    lines.append(f"**Selection:** top {len(picks)} by composite rank "
                 f"(~{100*len(picks)/max(1,total_universe):.1f}% of universe)\n")
    has_pead = "pead_rank" in picks.columns
    has_sector = "sector" in picks.columns
    header_cols = ["Rank", "Ticker"]
    if has_sector:
        header_cols.append("Sector")
    header_cols += ["Momentum", "Quality", "Value"]
    if has_pead:
        header_cols.append("PEAD")
    header_cols.append("Composite z")
    lines.append("| " + " | ".join(header_cols) + " |")
    lines.append("|" + "|".join("---" for _ in header_cols) + "|")
    for _, r in picks.iterrows():
        cells = [
            f"{int(r['rank']):>4d}",
            f"{r['ticker']:>6s}",
        ]
        if has_sector:
            cells.append(f"{(r.get('sector') or 'Unknown'):>20s}")
        cells += [
            f"{r['mom_rank'] if pd.notna(r['mom_rank']) else '-':>8}",
            f"{r['qual_rank'] if pd.notna(r['qual_rank']) else '-':>7}",
            f"{r['val_rank'] if pd.notna(r['val_rank']) else '-':>5}",
        ]
        if has_pead:
            pead_cell = r['pead_rank'] if pd.notna(r['pead_rank']) else '-'
            cells.append(f"{pead_cell:>4}")
        cells.append(f"{r['z_score']:>+10.2f}")
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("**Allocation:** equal-weight (1/N each)")
    lines.append("**Hold period:** quarterly rebalance recommended "
                 "(~63 trading days)")
    lines.append("")
    lines.append("*Generated by scripts/daily_factor_picks.py — read-only; "
                 "DOES NOT place orders.*")
    return "\n".join(lines)


def _write_outputs(result: FactorPicksResult, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    out_json = output_dir / f"{result.as_of.date().isoformat()}.json"
    long_short_mode = not result.shorts.empty
    payload = {
        "as_of": result.as_of.date().isoformat(),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "strategy": (
            result.strategy + "_ls" if long_short_mode else result.strategy
        ),
        "factors": result.factors_used,
        "universe_size": result.universe_size,
        "top_n": len(result.top_n),
        "picks": result.top_n.to_dict(orient="records"),
        "shorts": (
            result.shorts.to_dict(orient="records") if long_short_mode else []
        ),
        "long_short": long_short_mode,
        "snapshot_id": result.snapshot_id,
        "sector_cap_skipped": result.sector_cap_skipped,
    }
    out_json.write_text(json.dumps(payload, indent=2, default=str),
                        encoding="utf-8")

    md = _render_markdown(result.top_n, result.as_of, result.universe_size)
    print(md)
    out_md = output_dir / f"{result.as_of.date().isoformat()}.md"
    out_md.write_text(md, encoding="utf-8")
    logger.info("Wrote %s and %s", out_json, out_md)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = _parse_args()

    as_of = (
        pd.Timestamp(args.as_of) if args.as_of
        else pd.Timestamp.utcnow().normalize().tz_localize(None)
    )
    logger.info("As-of: %s | top_n: %d", as_of.date(), args.top_n)

    # Trend gate (default ON) -- skip the rebalance entirely when SPY is
    # below its --trend-entry-sma. Run BEFORE the heavy factor pipeline so
    # we short-circuit the expensive EDGAR load on gate-off days.
    # Backed by the 2026-05-18 asymmetric-filter backtest (75-SMA: +10.87pp
    # on 2022-2024 stress, bit-identical on 2024-2026 recent).
    if args.trend_gate:
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
        spy_data = fetcher.fetch_batch(["SPY"]).get("SPY")
        if spy_data is None or spy_data.empty:
            logger.warning(
                "--trend-gate active but no SPY data available; "
                "treating today as risk-on and proceeding."
            )
        else:
            if getattr(spy_data.index, "tz", None) is not None:
                spy_data = spy_data.copy()
                spy_data.index = spy_data.index.tz_localize(None)
            close = spy_data["Close"].astype(float)
            sma = close.rolling(
                window=args.trend_entry_sma,
                min_periods=args.trend_entry_sma,
            ).mean()
            eligible = sma[sma.index <= as_of].dropna()
            if eligible.empty:
                logger.warning(
                    "--trend-gate active but %d-SMA hasn't warmed up at %s; "
                    "treating today as risk-on and proceeding.",
                    args.trend_entry_sma, as_of.date(),
                )
            else:
                latest_sma = float(eligible.iloc[-1])
                latest_close = float(close.loc[eligible.index[-1]])
                if latest_close < latest_sma:
                    logger.warning(
                        "Trend gate BLOCKING as_of=%s: SPY $%.2f < %d-SMA "
                        "$%.2f. Returning empty picks. Skip the rebalance.",
                        as_of.date(), latest_close, args.trend_entry_sma,
                        latest_sma,
                    )
                    output_dir = Path(args.output_dir)
                    output_dir.mkdir(parents=True, exist_ok=True)
                    out_json = output_dir / f"{as_of.date().isoformat()}.json"
                    out_json.write_text(json.dumps({
                        "as_of": as_of.date().isoformat(),
                        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                        "strategy": "composite_d05_r63",
                        "factors": [],
                        "universe_size": 0,
                        "top_n": 0,
                        "picks": [],
                        "snapshot_id": args.snapshot_id,
                        "sector_cap_skipped": [],
                        "gate": {
                            "trend_blocked": True,
                            "trend_entry_sma": args.trend_entry_sma,
                            "spy_close": round(latest_close, 2),
                            "spy_sma": round(latest_sma, 2),
                        },
                    }, indent=2, default=str), encoding="utf-8")
                    return 0

    # VIX gate (opt-in) — pulled BEFORE the heavy factor pipeline so we
    # short-circuit the expensive EDGAR load when the gate blocks us.
    if args.vix_gate:
        from src.config_loader import Config
        from src.data.cache import DataCache
        from src.data.fetcher import DataFetcher
        from src.factors.vix_regime import is_calm

        config = Config()
        cache = DataCache(
            expiry_hours=config.get("data", "cache_expiry_hours", default=24),
            market_hours_expiry_minutes=config.get(
                "data", "market_hours_cache_minutes", default=5,
            ),
        )
        fetcher = DataFetcher(config, cache)
        vix_data = fetcher.fetch_batch(["^VIX"]).get("^VIX")
        if vix_data is None or vix_data.empty:
            logger.warning(
                "--vix-gate requested but no VIX data available; "
                "treating today as calm and proceeding."
            )
        else:
            # tz-normalize so as_of compares cleanly with the index.
            if getattr(vix_data.index, "tz", None) is not None:
                vix_data = vix_data.copy()
                vix_data.index = vix_data.index.tz_localize(None)
            calm = is_calm(
                vix_data, as_of, window=args.vix_window,
                cutoff=args.vix_cutoff,
            )
            if not calm:
                logger.warning(
                    "VIX gate BLOCKING as_of=%s (cutoff=%.2f); "
                    "returning empty picks. Skip the rebalance.",
                    as_of.date(), args.vix_cutoff,
                )
                # Emit empty picks so downstream tooling sees the gate
                # explicitly rather than yesterday's stale file.
                output_dir = Path(args.output_dir)
                output_dir.mkdir(parents=True, exist_ok=True)
                out_json = output_dir / f"{as_of.date().isoformat()}.json"
                out_json.write_text(json.dumps({
                    "as_of": as_of.date().isoformat(),
                    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                    "strategy": "composite_d05_r63",
                    "factors": [],
                    "universe_size": 0,
                    "top_n": 0,
                    "picks": [],
                    "snapshot_id": args.snapshot_id,
                    "sector_cap_skipped": [],
                    "gate": {"vix_blocked": True,
                              "vix_cutoff": args.vix_cutoff,
                              "vix_window": args.vix_window},
                }, indent=2, default=str), encoding="utf-8")
                return 0

    max_sector_pct: float | None = args.max_sector_pct
    if max_sector_pct is not None and (max_sector_pct >= 100 or max_sector_pct <= 0):
        max_sector_pct = None

    # Load yesterday's picks for hysteresis. The most recent JSON in
    # output_dir BEFORE today is the right input. Skipping today's file
    # (in case the script is re-run on the same day) avoids carrying
    # forward a half-baked rerun.
    prev_longs: list[str] = []
    prev_shorts: list[str] = []
    if args.hysteresis_bonus > 0:
        output_dir = Path(args.output_dir)
        today_iso = as_of.date().isoformat()
        if output_dir.exists():
            prior_files = sorted(
                f for f in output_dir.glob("*.json")
                if f.stem < today_iso
            )
            if prior_files:
                latest = prior_files[-1]
                try:
                    prev_data = json.loads(latest.read_text(encoding="utf-8"))
                    prev_longs = [
                        p["ticker"] for p in prev_data.get("picks", [])
                        if isinstance(p, dict) and p.get("ticker")
                    ]
                    prev_shorts = [
                        p["ticker"] for p in prev_data.get("shorts", [])
                        if isinstance(p, dict) and p.get("ticker")
                    ]
                    logger.info(
                        "Hysteresis: loaded %d prior longs / %d prior shorts "
                        "from %s", len(prev_longs), len(prev_shorts),
                        latest.name,
                    )
                except (OSError, json.JSONDecodeError) as exc:
                    logger.warning(
                        "Hysteresis: failed to read %s (%s); proceeding "
                        "without prior picks", latest.name, exc,
                    )

    result = run_factor_picks(
        as_of=as_of,
        top_n=args.top_n,
        snapshot_id=args.snapshot_id,
        include_pead=args.include_pead,
        earnings_cache_dir=Path(args.earnings_cache_dir),
        max_sector_pct=max_sector_pct,
        long_short=args.long_short,
        short_n=args.short_n,
        hysteresis_bonus=args.hysteresis_bonus,
        previous_longs=prev_longs,
        previous_shorts=prev_shorts,
        sector_neutral_quality=args.sector_neutral_quality,
    )
    if result.composite.empty:
        return 2

    _write_outputs(result, Path(args.output_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
