"""Run the minimal_baseline strategy (review item #6) against the
clean-pipeline universe and dump the full backtest result + walk-forward
report to ``data/baseline/minimal_baseline.json``.

This is the CONTROL ARM for evaluating whether the experimental sources
(PEAD, Alpha158, patterns, ML ensemble, insider, catalysts, sector
flows, short interest, research agent) add real edge. Any richer
strategy that fails to beat this on OOS Sharpe + alpha-vs-SPY does NOT
deserve to keep its extra sources.

Usage:
    uv run python -m scripts.run_minimal_baseline \\
        [--universe russell_1000] \\
        [--years 2] \\
        [--starting-cash 10000]

Output written to data/baseline/minimal_baseline.json. Consumed by
``scripts/produce_mvtp_report.py`` (review item #7).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.config_loader import Config

logger = logging.getLogger("minimal_baseline")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run the minimal_baseline control strategy.",
    )
    p.add_argument("--universe", default="russell_1000",
                   choices=("russell_1000",))
    p.add_argument("--years", type=float, default=2.0,
                   help="Backtest window length, years (default 2)")
    p.add_argument("--starting-cash", type=float, default=10_000.0)
    p.add_argument("--output",
                   default="data/baseline/minimal_baseline.json")
    p.add_argument("--pit-fundamentals", action="store_true",
                   help="Use EDGAR PIT loader for fundamentals "
                        "(strongly recommended).")
    p.add_argument("--walk-forward-folds", type=int, default=5,
                   help="N-fold walk-forward CV (review #5)")
    p.add_argument("--min-mean-sharpe", type=float, default=0.5,
                   help="Walk-forward gate threshold")
    p.add_argument("--end-date",
                   help="ISO date; defaults to min(today, universe-captured). "
                        "Pass explicitly to test a custom window.")
    p.add_argument(
        "--regime-mode",
        default="off",
        choices=("off", "skip_bear", "skip_bear_and_chop"),
        help="Override risk_management.regime_filter.mode for this run. "
             "'off' = no gate (default). 'skip_bear' refuses new entries "
             "when SPY < 200d SMA AND VIX > 25. 'skip_bear_and_chop' is "
             "stricter (only enters in confirmed bull). Used to test the "
             "hypothesis that 2022-bear folds drag minimal_baseline's "
             "walk-forward result.",
    )
    p.add_argument(
        "--strategy",
        default="minimal_baseline",
        help="Strategy key from config/strategies.yaml. Defaults to the "
             "control. Use minimal_baseline_v2 / _v3 for the IC-driven "
             "redesigns.",
    )
    p.add_argument(
        "--snapshot-id",
        help="Read every yfinance-sourced input from "
             "data/snapshots/<snapshot_id>/ instead of pulling fresh. "
             "Pins the run for reproducibility — eliminates ±0.4 Sharpe "
             "yfinance drift across pulls. Build snapshots with "
             "scripts/freeze_snapshot.py.",
    )
    # Ablation overrides. Each leaves the strategy YAML untouched and
    # only the engine-side mechanic is disabled / loosened. Used to
    # answer the hypothesis "non-score machinery is delivering the
    # apparent alpha" (project_yfinance_nondeterminism follow-up).
    p.add_argument(
        "--min-score-override", type=float, default=None,
        help="Override the strategy's min_score floor. Setting to 0 "
             "ablates the min_score gate entirely.",
    )
    p.add_argument(
        "--atr-stop-mult-override", type=float, default=None,
        help="Override engine atr_stop_mult. Setting to a very large "
             "value (e.g. 99) effectively disables the ATR stop.",
    )
    p.add_argument(
        "--atr-target-mult-override", type=float, default=None,
        help="Override engine atr_target_mult (take-profit).",
    )
    p.add_argument(
        "--max-hold-days-override", type=int, default=None,
        help="Override engine max_hold_days (time stop). Setting to "
             "9999 ablates the hold-time exit.",
    )
    p.add_argument(
        "--ablation-label", default="",
        help="Free-text label stamped into the slim JSON so a comparison "
             "harness can tell ablation runs apart.",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Lazy imports — the engine module pulls in the full analyzer chain,
    # which we want only after argparse has done its thing.
    from src.backtest.engine import (
        BacktestConfig,
        SurvivorshipGuardError,
        fetch_earnings_history,
        run_backtest,
    )
    from src.data.cache import DataCache
    from src.data.fetcher import DataFetcher
    from src.data.fundamentals import FundamentalsFetcher

    config = Config()
    strategy_name = args.strategy
    strategy = config.get_strategy(strategy_name)
    if strategy is None:
        logger.error(
            "Strategy %r not found in config/strategies.yaml.",
            strategy_name,
        )
        return 2

    # Universe selection
    if args.universe == "russell_1000":
        tickers = config.get_russell_1000_tickers()
    else:
        logger.error("Unknown universe %s", args.universe)
        return 2

    if not tickers:
        logger.error(
            "Universe %s has no tickers. Run scripts/fetch_russell_1000.py "
            "first.", args.universe,
        )
        return 2

    logger.info("Universe %s: %d tickers", args.universe, len(tickers))

    # ----- snapshot vs fresh-fetch branch -----
    # When --snapshot-id is set the run reads from a frozen Parquet
    # snapshot and refuses fresh yfinance calls. Eliminates the ±0.4
    # Sharpe drift between pulls (project_yfinance_nondeterminism).
    if args.snapshot_id:
        from src.storage.snapshot import load_snapshot
        logger.info("Loading snapshot %s ...", args.snapshot_id)
        snap = load_snapshot(args.snapshot_id)
        logger.info(
            "Snapshot loaded: window %s -> %s, %d tickers with prices, "
            "spy=%s vix=%s",
            snap.manifest.window_start, snap.manifest.window_end,
            snap.manifest.n_tickers_with_prices,
            snap.manifest.has_spy, snap.manifest.has_vix,
        )
        if args.universe != snap.manifest.universe_label:
            logger.error(
                "Snapshot universe %s != requested %s",
                snap.manifest.universe_label, args.universe,
            )
            return 2
        price_data = snap.price_data
        fundamentals = snap.fundamentals
        earnings_history = snap.earnings_history
        spy_df = snap.spy_df
        vix_df = snap.vix_df

        # Window comes from the snapshot manifest unless caller
        # explicitly overrode --end-date. The runner's --years
        # determines how far back we slice into the snapshot.
        if args.end_date:
            end = pd.Timestamp(args.end_date)
        else:
            end = pd.Timestamp(snap.manifest.window_end)
        start = end - pd.DateOffset(years=int(args.years))
        snapshot_id_for_record = args.snapshot_id
    else:
        # Cache + fetchers (fresh-pull path)
        cache = DataCache(
            expiry_hours=config.get("data", "cache_expiry_hours", default=24),
            market_hours_expiry_minutes=config.get(
                "data", "market_hours_cache_minutes", default=5,
            ),
        )
        fetcher = DataFetcher(config, cache)
        fund_fetcher = FundamentalsFetcher(config, cache)

        # Default end_date: min(today, universe-captured). The survivorship
        # guard refuses end > captured, so picking the smaller automatically
        # keeps the run within the safe window. Explicit --end-date wins.
        today = pd.Timestamp.utcnow().normalize().tz_localize(None)
        try:
            captured = config.get_universe_captured_date(args.universe)
        except ValueError as exc:
            logger.error("Universe captured-date header malformed: %s", exc)
            return 2
        if args.end_date:
            end = pd.Timestamp(args.end_date)
        elif captured is not None:
            end = min(today, pd.Timestamp(captured))
            if end < today:
                logger.info(
                    "End_date trimmed to universe-capture date %s (today=%s) "
                    "to satisfy the survivorship guard.",
                    end.date(), today.date(),
                )
        else:
            end = today
        start = end - pd.DateOffset(years=int(args.years))

        logger.info("Fetching %d ticker price histories (this can take a while)...",
                    len(tickers))
        price_data = fetcher.fetch_batch(tickers)
        fundamentals = fund_fetcher.fetch_batch(tickers)

        # Earnings (used by the engine's blackout filter)
        logger.info("Fetching earnings history...")
        earnings_history = fetch_earnings_history(list(price_data.keys()), workers=8)

        # SPY benchmark
        logger.info("Fetching SPY benchmark...")
        spy_df = fetcher.fetch_price_data("SPY", period=f"{int(args.years)+1}y")

        # VIX — required for the regime gate's bear-classification when
        # --regime-mode is non-off.
        vix_df = None
        if args.regime_mode != "off":
            logger.info("Fetching ^VIX history for regime gate (%s)...",
                        args.regime_mode)
            vix_df = fetcher.fetch_price_data("^VIX",
                                              period=f"{int(args.years)+1}y")
            if vix_df is None or vix_df.empty:
                logger.error(
                    "Regime gate requested but ^VIX fetch returned empty; "
                    "refusing to run silently with gate=off."
                )
                return 2
        snapshot_id_for_record = None

    # The regime gate's config monkey-patch is independent of which
    # data path supplied the bars. Apply it now (after vix_df is known)
    # so snapshot runs can also use --regime-mode.
    if args.regime_mode != "off":
        if vix_df is None or vix_df.empty:
            logger.error(
                "Regime gate %s requested but VIX data is missing from "
                "the data source (snapshot or fetch). Refusing.",
                args.regime_mode,
            )
            return 2
        _orig_get_regime_filter = config.get_regime_filter

        def _patched_get_regime_filter():
            base = _orig_get_regime_filter() or {}
            return {**base, "enabled": True, "mode": args.regime_mode}

        config.get_regime_filter = _patched_get_regime_filter  # type: ignore[assignment]

    # PIT loader (recommended for fundamental-weighted strategies).
    # Async API: pull all EDGAR rows for the universe in one query, then
    # the engine resolves (ticker, as_of) lookups in-memory. Same shape
    # as scripts/sweep_insider_flow.py and sweep_pit_fundamentals.py.
    pit_loader = None
    if args.pit_fundamentals:
        import asyncio
        from src.scoring.fundamentals_pit_loader import FundamentalsPITLoader
        from src.db.repositories import PostgresFundamentalsRepository
        from src.db.session import get_sessionmaker, dispose_engine

        async def _build_loader() -> FundamentalsPITLoader:
            SL = get_sessionmaker()
            async with SL() as session:
                repo = PostgresFundamentalsRepository(session)
                loader = await FundamentalsPITLoader.from_repository(
                    repo, list(price_data.keys()),
                )
            # Dispose so subsequent asyncio.run() calls don't inherit a
            # connection pool bound to this closed loop (Windows asyncpg
            # proactor crash, audit fix 4199d8a).
            await dispose_engine()
            return loader

        try:
            pit_loader = asyncio.run(_build_loader())
            logger.info(
                "PIT loader active — %d tickers indexed from EDGAR.",
                len(pit_loader._by_ticker),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "PIT loader build failed (%s); proceeding without. "
                "Fundamental weight in minimal_baseline is 0.30 so this WILL "
                "raise LookaheadGuardError unless EDGAR coverage is healthy. "
                "Re-run with EDGAR DB populated to fix.", exc,
            )

    # Resolve final mechanic values: CLI override wins, else strategy
    # YAML, else engine default. Each override gets a log line so the
    # ablation provenance is loud.
    resolved_min_score = (
        args.min_score_override
        if args.min_score_override is not None
        else strategy.get("min_score", 55)
    )
    if args.min_score_override is not None:
        logger.warning("ABLATION: min_score override = %.2f (strategy YAML was %s)",
                       resolved_min_score, strategy.get("min_score", 55))

    bt_kwargs: dict = {
        "start_date": start,
        "end_date": end,
        "starting_cash": args.starting_cash,
        "universe_label": args.universe,
        "apply_survivorship_haircut": True,
        "refuse_survivor_only_window": True,
        "walk_forward_folds": args.walk_forward_folds,
        "walk_forward_min_mean_sharpe": args.min_mean_sharpe,
        "bootstrap_resamples": 500,
        "compound": False,
        "min_score": resolved_min_score,
    }
    if args.atr_stop_mult_override is not None:
        bt_kwargs["atr_stop_mult"] = args.atr_stop_mult_override
        logger.warning("ABLATION: atr_stop_mult override = %.2f",
                       args.atr_stop_mult_override)
    if args.atr_target_mult_override is not None:
        bt_kwargs["atr_target_mult"] = args.atr_target_mult_override
        logger.warning("ABLATION: atr_target_mult override = %.2f",
                       args.atr_target_mult_override)
    if args.max_hold_days_override is not None:
        bt_kwargs["max_hold_days"] = args.max_hold_days_override
        logger.warning("ABLATION: max_hold_days override = %d",
                       args.max_hold_days_override)
    bt_cfg = BacktestConfig(**bt_kwargs)

    logger.info("Backtest start: %s end: %s walk_forward_folds=%d",
                start.date(), end.date(), args.walk_forward_folds)

    try:
        result = run_backtest(
            price_data=price_data,
            fundamentals=fundamentals,
            config=config,
            strategy=strategy,
            bt_cfg=bt_cfg,
            spy_df=spy_df,
            vix_df=vix_df,
            earnings_history=earnings_history,
            fundamentals_pit_loader=pit_loader,
        )
    except SurvivorshipGuardError as exc:
        logger.error("Survivorship guard: %s", exc)
        return 3

    if "error" in result:
        logger.error("Backtest returned error: %s", result["error"])
        return 4

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Strip the full equity curve to keep the file readable; keep just
    # the summary blocks + the walk-forward report (the things the MVTP
    # report consumer reads).
    # Provenance stamps so a result JSON is self-describing — caller
    # can verify which code + data + config produced this number.
    import subprocess
    try:
        git_sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parent.parent,
        ).decode().strip()
    except Exception:  # noqa: BLE001
        git_sha = None

    slim = {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "universe": args.universe,
        "strategy": strategy_name,
        "window": {
            "start": start.date().isoformat(),
            "end": end.date().isoformat(),
            "years": args.years,
        },
        "starting_cash": args.starting_cash,
        "pit_fundamentals": args.pit_fundamentals,
        "regime_mode": args.regime_mode,
        "snapshot_id": snapshot_id_for_record,
        "git_sha": git_sha,
        "ablation_label": args.ablation_label or None,
        "ablation_overrides": {
            "min_score": args.min_score_override,
            "atr_stop_mult": args.atr_stop_mult_override,
            "atr_target_mult": args.atr_target_mult_override,
            "max_hold_days": args.max_hold_days_override,
        },
        "effective_config": {
            "min_score": resolved_min_score,
            "atr_stop_mult": bt_kwargs.get("atr_stop_mult", 2.0),
            "atr_target_mult": bt_kwargs.get("atr_target_mult", 6.0),
            "max_hold_days": bt_kwargs.get("max_hold_days", 90),
        },
        "full": result.get("full"),
        "in_sample": result.get("in_sample"),
        "out_of_sample": result.get("out_of_sample"),
        "split_date": result.get("split_date"),
        "walk_forward": result.get("walk_forward"),
        "regimes": result.get("regimes"),
        "data_quality": result.get("data_quality"),
        "n_trades": len(result.get("trades") or []),
        "warnings": result.get("warnings") or [],
        # PIPELINE_VERSION lives under data_quality.pipeline_version in the
        # engine result (see engine.py:106). Earlier slim build pulled it
        # from top-level and got None; the MVTP report's freshness gate then
        # failed against an unknown pipeline.
        "pipeline_version": (
            (result.get("data_quality") or {}).get("pipeline_version")
        ),
        # Block bootstrap CIs (return + win rate + expectancy + Sharpe).
        # bootstrap_label says whether the CI is on the OOS slice or the
        # full window — engine picks OOS if oos_trades >= 20.
        "bootstrap": result.get("bootstrap"),
        "bootstrap_label": result.get("bootstrap_label"),
        # Top-N-removed concentration sensitivity (review #7 auto-check).
        # MVTP gate fires FAIL if Sharpe drop > 0.4.
        "concentration_sensitivity": result.get("concentration_sensitivity"),
    }
    out.write_text(json.dumps(slim, indent=2, default=str), encoding="utf-8")
    logger.info("Wrote %s", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
