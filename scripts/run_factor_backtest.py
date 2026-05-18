"""Factor-strategy backtest runner.

Long-only top-decile-momentum portfolio with a 200-day-SMA SPY trend
filter, rebalanced every ``--rebalance-days`` trading sessions
(default 21 = monthly). Replaces the 6-analyzer composite that the
2026-05-16 audit found has no defensible edge.

Reads from a frozen snapshot (yfinance non-determinism is the death
of comparability — see ``project_yfinance_nondeterminism``). The
snapshot pins prices, SPY, and the universe; this runner does NOT
touch the network.

Outputs JSON with:
  - window metadata + snapshot id
  - equity_curve (date, equity)
  - daily_returns
  - trades (truncated to first 200)
  - metrics: total return, ann Sharpe, max DD, alpha vs SPY
  - walk-forward folds (5 rolling, mean + min Sharpe)

Usage
-----

    uv run python -m scripts.run_factor_backtest \\
        --snapshot-id 234de3c737aa1eb2 \\
        --top-decile 0.10 \\
        --rebalance-days 21 \\
        --cost-bps 5 \\
        --starting-cash 10000 \\
        --output data/factors/momentum_v1_<snap>.json
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from src.factors.composite import combine as combine_factors
from src.factors.insider_cluster import insider_cluster_factor
from src.factors.momentum import momentum_12_1
from src.factors.pead import pead_factor
from src.factors.quality import quality_factor
from src.factors.regime import is_risk_on, trend_state_series
from src.factors.regime_weights import list_profiles, weights_for
from src.factors.residual_momentum import residual_momentum_12_1
from src.factors.value import value_factor
from src.factors.vix_regime import (
    DEFAULT_CUTOFF as VIX_DEFAULT_CUTOFF,
    DEFAULT_WINDOW as VIX_DEFAULT_WINDOW,
    vix_percentile_series,
)
from src.factors.volatility import low_vol_filter
from src.storage.snapshot import load_snapshot

logger = logging.getLogger("run_factor_backtest")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--snapshot-id", required=True)
    p.add_argument("--top-decile", type=float, default=0.10,
                   help="Fraction of universe to hold (default 0.10 = top 10%).")
    p.add_argument("--rebalance-days", type=int, default=21,
                   help="Trading-day cadence for rebalance (default 21 = monthly).")
    p.add_argument("--cost-bps", type=float, default=5.0,
                   help="One-way transaction cost in basis points (default 5).")
    p.add_argument("--starting-cash", type=float, default=10_000.0)
    p.add_argument("--strategy-label", default="momentum_12_1+regime",
                   help="Label printed in the output; useful when sweeping.")
    p.add_argument("--no-regime-filter", action="store_true",
                   help="Disable the SPY 200d-SMA trend filter (run "
                        "always-on momentum). Use only for ablation.")
    p.add_argument("--vix-gate", action="store_true",
                   help="Block new entries when VIX is in the top "
                        "(1 - vix_cutoff) of its trailing 252d distribution. "
                        "Motivated by the 2026-05-18 regime IC report: "
                        "fundamental's IC degrades 3.5x in high_vix. Mutually "
                        "compatible with --no-regime-filter — both can fire "
                        "independently.")
    p.add_argument("--vix-cutoff", type=float, default=VIX_DEFAULT_CUTOFF,
                   help=f"VIX-percentile cutoff for --vix-gate "
                        f"(default {VIX_DEFAULT_CUTOFF:.2f}). Block when the "
                        "trailing percentile is at or above this.")
    p.add_argument("--vix-window", type=int, default=VIX_DEFAULT_WINDOW,
                   help=f"Rolling window for --vix-gate (default "
                        f"{VIX_DEFAULT_WINDOW} trading days).")
    p.add_argument("--regime-weights",
                   default="equal",
                   choices=tuple(list_profiles()),
                   help="Composite rank-blend weight profile. 'equal' is "
                        "today's default (equal weight m+q+v). Other "
                        "profiles weight differently per VIX regime; see "
                        "src/factors/regime_weights.py for the full table.")
    p.add_argument("--low-vol-keep-pct", type=float, default=1.0,
                   help="Post-composite vol filter: keep names in the "
                        "bottom N%% of realized vol. 1.0 (default) disables. "
                        "0.80 = drop the top 20%% most-volatile from the "
                        "factor top-decile before allocation. Matches the "
                        "'low-vol quality sleeve' from the 2026-05-18 plan.")
    p.add_argument("--low-vol-window", type=int, default=63,
                   help="Rolling window for low-vol filter (default 63 td).")
    p.add_argument("--include-insider", action="store_true",
                   help="Add the Cohen-Malloy-Pomorski insider-cluster "
                        "factor as a 4th rank frame in the composite. "
                        "Requires insider_transactions table loaded; off "
                        "by default until backtest-validated.")
    p.add_argument("--insider-window-days", type=int, default=90,
                   help="Trailing window for insider clusters (default 90).")
    p.add_argument("--insider-min-cluster", type=int, default=2,
                   help="Minimum distinct insiders required to count as a "
                        "cluster (default 2).")
    p.add_argument("--include-pead", action="store_true",
                   help="Add the Bernard-Thomas PEAD factor as a 4th "
                        "(or 5th) rank frame. Loads earnings histories "
                        "from --earnings-cache-dir.")
    p.add_argument("--earnings-cache-dir", default="data/earnings_history",
                   help="Per-ticker earnings parquet cache for PEAD.")
    p.add_argument("--pead-drift-window", type=int, default=60,
                   help="PEAD drift envelope in calendar days (default 60).")
    p.add_argument("--long-short", action="store_true",
                   help="Run the strategy as long-short: top decile by "
                        "composite (longs) PLUS bottom decile (shorts), "
                        "half-capital each. Net exposure ~0; gross ~1x. "
                        "Authorized by user 2026-05-18. Backtest only; "
                        "live execution NOT wired (margin/locate/borrow on "
                        "Alpaca is a separate project).")
    p.add_argument("--short-decile", type=float, default=None,
                   help="Bottom-decile size for shorts. Defaults to "
                        "--top-decile so longs and shorts have equal count.")
    p.add_argument("--borrow-bps", type=float, default=50.0,
                   help="Annualized borrow cost in bps charged on short "
                        "notional (default 50 = 0.5%%/yr, typical for liquid "
                        "SP500 names). Hard-to-borrow names cost much more "
                        "in reality; raise this for stress scenarios.")
    p.add_argument("--factor",
                   default="momentum",
                   choices=("momentum", "quality", "value", "composite"),
                   help="Which factor to rank by. composite = "
                        "equal-weight rank-blend of all three.")
    p.add_argument("--composite-factors", default="mqv",
                   help="Which factors to include in the composite. "
                        "Subset of 'mqv' (e.g. 'mv' drops quality). Default "
                        "'mqv' is the full three-factor blend. Used by "
                        "ablation runs (which factor is the loser in a "
                        "given window).")
    p.add_argument("--sector-neutral-quality", action="store_true",
                   help="Rank quality WITHIN sector instead of "
                        "cross-sectional. Picks the best names INSIDE "
                        "each sector instead of overweighting whichever "
                        "sectors happen to have the highest absolute "
                        "quality scores. Motivated by the 2026-05-18 "
                        "ablation: quality cross-sectional picks defensive "
                        "sectors that get killed in rotation regimes.")
    p.add_argument("--momentum-flavor",
                   default="raw",
                   choices=("raw", "residual"),
                   help="Momentum implementation. 'raw' is the canonical "
                        "Jegadeesh-Titman 12-1 (current default). 'residual' "
                        "is Blitz-Huij-Martens 2011 residual momentum — "
                        "strips SPY beta before cumulating. Applies to the "
                        "'momentum' single factor and to the momentum sleeve "
                        "inside 'composite'.")
    p.add_argument("--hysteresis-bonus", type=float, default=0.0,
                   help="Hysteresis (stickiness) bonus for currently-held "
                        "names, expressed as a fraction of the target N. "
                        "0.0 (default) disables — pure rank-based selection. "
                        "0.5 = held names get their rank reduced by 0.5*N "
                        "slots before re-selection, so a top-24 portfolio "
                        "keeps any held name still in the top-36. Reduces "
                        "turnover and the cost drag that comes with it.")
    p.add_argument("--output", required=True,
                   help="Output JSON path.")
    return p.parse_args()


def _load_pit_fundamentals(tickers: list[str]):
    """Sync wrapper around the async EDGAR PIT loader.

    Pulls the full panel of EDGAR rows for the universe once at
    startup. The loader is then in-memory and serves O(log n)
    point-in-time lookups inside the rebalance loop.
    """
    from src.db.repositories.fundamentals import (
        PostgresFundamentalsRepository,
    )
    from src.db.session import get_sessionmaker, run_with_dispose
    from src.scoring.fundamentals_pit_loader import (
        FundamentalsPITLoader,
    )

    async def _go():
        async with get_sessionmaker()() as session:
            repo = PostgresFundamentalsRepository(session)
            return await FundamentalsPITLoader.from_repository(repo, tickers)

    return run_with_dispose(_go())


def _fetch_insider_factor_sync(
    tickers: list[str], as_of: pd.Timestamp,
    *, window_days: int, min_cluster: int,
) -> pd.DataFrame:
    """Synchronous wrapper for the async insider factor — used inside the
    sync backtest loop. Spins a fresh session per call (cheap relative
    to factor compute), closes it cleanly."""
    from src.db.session import get_sessionmaker, run_with_dispose

    async def _go():
        async with get_sessionmaker()() as session:
            return await insider_cluster_factor(
                session, tickers=tickers, as_of=as_of,
                window_days=window_days, min_cluster=min_cluster,
            )
    return run_with_dispose(_go())


def _resolve_ranking(
    factor: str,
    prices: dict,
    fund_loader,
    as_of: pd.Timestamp,
    universe_tickers: list[str],
    *,
    regime_profile: str = "equal",
    vix_df: pd.DataFrame | None = None,
    spy_df: pd.DataFrame | None = None,
    momentum_flavor: str = "raw",
    composite_factors: str = "mqv",
    sector_neutral_quality: bool = False,
    sectors: dict[str, str] | None = None,
    include_insider: bool = False,
    insider_window_days: int = 90,
    insider_min_cluster: int = 2,
    include_pead: bool = False,
    earnings_histories: dict | None = None,
    pead_drift_window: int = 60,
) -> tuple[pd.DataFrame, str]:
    """Dispatch to the requested factor. Returns ``(ranking, regime_label)``.

    For single-factor runs (momentum / quality / value alone) the
    regime_label is always "low_vix" because there's no blend to
    reshape. The composite path consults the regime-weights profile.
    """
    def _mom(p, a):
        if momentum_flavor == "residual":
            if spy_df is None or spy_df.empty:
                raise ValueError(
                    "momentum_flavor='residual' requires spy_df; got None/empty"
                )
            return residual_momentum_12_1(p, spy_df, a)
        return momentum_12_1(p, a)

    if factor == "momentum":
        return _mom(prices, as_of), "low_vix"
    if factor == "quality":
        return quality_factor(fund_loader, universe_tickers, as_of), "low_vix"
    if factor == "value":
        return value_factor(fund_loader, prices, universe_tickers, as_of), "low_vix"
    if factor == "composite":
        # Ablation support: composite_factors='mqv' (default) uses all
        # three; 'mv' drops quality; 'qv' drops momentum; etc.
        wants_m = "m" in composite_factors
        wants_q = "q" in composite_factors
        wants_v = "v" in composite_factors
        if not any([wants_m, wants_q, wants_v]):
            raise ValueError(
                f"--composite-factors={composite_factors!r} excludes "
                "every base factor"
            )
        m = _mom(prices, as_of) if wants_m else pd.DataFrame()
        q = quality_factor(fund_loader, universe_tickers, as_of) if wants_q else pd.DataFrame()
        v = value_factor(fund_loader, prices, universe_tickers, as_of) if wants_v else pd.DataFrame()
        if sector_neutral_quality and wants_q and not q.empty:
            from src.factors.sector_neutralize import sector_neutralize
            if not sectors:
                raise ValueError(
                    "sector_neutral_quality=True requires a non-empty "
                    "sectors map; pass via the backtest harness."
                )
            q = sector_neutralize(q, sectors)
        weights_all, regime = weights_for(
            regime_profile, as_of=as_of, vix_df=vix_df,
        )
        # Project the regime weights onto the surviving base factors.
        # weights_all order matches [m, q, v]; reuse only the ones we
        # asked for and re-normalize would happen inside combine().
        frames = []
        weights = []
        for keep, w, frame in zip(
            [wants_m, wants_q, wants_v], list(weights_all), [m, q, v],
        ):
            if keep:
                frames.append(frame)
                weights.append(float(w))
        if include_insider:
            ins = _fetch_insider_factor_sync(
                universe_tickers, as_of,
                window_days=insider_window_days,
                min_cluster=insider_min_cluster,
            )
            # Insider sparsity is real (often <100 of 500 names have a
            # qualifying cluster). min_overlap stays at 2 so a ticker
            # without insider data is still ranked on m+q+v.
            frames.append(ins)
            # Weights extension: insider gets the same weight as
            # momentum unless the profile dictates otherwise.
            weights.append(float(weights[0]))
        if include_pead and earnings_histories is not None:
            pead = pead_factor(
                earnings_histories, as_of,
                prices=prices, drift_window_days=pead_drift_window,
            )
            frames.append(pead)
            # PEAD coverage is ~60-70% of names (quarterly cycle + 60d
            # window); weight on par with momentum.
            weights.append(float(weights[0]))
        # Permissive overlap: a ticker that's in 2 of N factors still
        # gets ranked. Strict overlap (must be in all) drops too many
        # names from the universe at any given as_of.
        ranking = combine_factors(
            frames, min_overlap=2, weights=weights,
        )
        return ranking, regime
    raise ValueError(f"unknown factor {factor!r}")


def _annualize_sharpe(daily_rets: pd.Series, periods_per_year: int = 252) -> float:
    if daily_rets.empty:
        return 0.0
    mu = daily_rets.mean()
    sigma = daily_rets.std(ddof=0)
    if sigma == 0:
        return 0.0
    return float(mu / sigma * math.sqrt(periods_per_year))


def _max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    return float((equity / equity.cummax() - 1.0).min())


def _walk_forward_folds(daily_rets: pd.Series, n_folds: int = 5) -> dict:
    """Split daily_rets into ``n_folds`` contiguous folds and report
    each fold's Sharpe + return. Mirrors the gating used elsewhere."""
    if daily_rets.empty or len(daily_rets) < n_folds:
        return {"folds": [], "mean_sharpe": 0.0, "min_sharpe": 0.0, "passed": False}
    fold_size = len(daily_rets) // n_folds
    folds = []
    for i in range(n_folds):
        start = i * fold_size
        end = (i + 1) * fold_size if i < n_folds - 1 else len(daily_rets)
        chunk = daily_rets.iloc[start:end]
        sharpe = _annualize_sharpe(chunk)
        ret_pct = (1 + chunk).prod() - 1
        folds.append({
            "fold": i,
            "sharpe": round(sharpe, 3),
            "return_pct": round(ret_pct * 100, 2),
            "n_days": len(chunk),
        })
    sharpes = [f["sharpe"] for f in folds]
    mean_s = float(np.mean(sharpes))
    min_s = float(np.min(sharpes))
    # Strict gate: every fold > 0 AND mean ≥ 0.5 (matches the engine's
    # walk_forward.passed convention).
    passed = all(s > 0 for s in sharpes) and mean_s >= 0.5
    return {
        "folds": folds,
        "mean_sharpe": round(mean_s, 3),
        "min_sharpe": round(min_s, 3),
        "passed": passed,
    }


def _close_on(prices: dict[str, pd.DataFrame], ticker: str, date: pd.Timestamp) -> float | None:
    df = prices.get(ticker)
    if df is None or df.empty:
        return None
    eligible = df[df.index <= date]
    if eligible.empty:
        return None
    last = eligible["Close"].iloc[-1]
    return None if pd.isna(last) else float(last)


def _mark_to_market(
    holdings: dict[str, int], cash: float,
    prices: dict[str, pd.DataFrame], date: pd.Timestamp,
) -> float:
    eq = cash
    for t, sh in holdings.items():
        px = _close_on(prices, t, date)
        if px is not None:
            eq += sh * px
    return eq


def run(args: argparse.Namespace) -> dict:
    snap = load_snapshot(args.snapshot_id)
    prices = snap.price_data
    spy = snap.spy_df
    if spy is None or spy.empty:
        raise SystemExit(f"snapshot {args.snapshot_id} has no SPY frame")

    universe_tickers = sorted(prices.keys())
    # Quality/value/composite need EDGAR PIT fundamentals. Pull once.
    earnings_histories: dict | None = None
    if args.include_pead:
        from src.scoring.earnings_cache import load_earnings_histories
        logger.info("Loading earnings histories for PEAD...")
        earnings_histories = load_earnings_histories(
            universe_tickers, Path(args.earnings_cache_dir),
        )
        logger.info(
            "Loaded earnings histories for %d / %d tickers",
            sum(1 for h in earnings_histories.values() if h is not None),
            len(universe_tickers),
        )
    fund_loader = None
    if args.factor in ("quality", "value", "composite"):
        logger.info(
            "Pre-loading EDGAR PIT fundamentals for %d tickers...",
            len(universe_tickers),
        )
        fund_loader = _load_pit_fundamentals(universe_tickers)
        cov = fund_loader.coverage()
        n_covered = sum(1 for c in cov.values() if c > 0)
        logger.info(
            "Fundamentals coverage: %d/%d tickers have ≥1 EDGAR row "
            "(%.1f%%)",
            n_covered, len(universe_tickers),
            100.0 * n_covered / max(1, len(universe_tickers)),
        )

    # Sectors: needed when --sector-neutral-quality is on. yfinance
    # cache is shared with daily_factor_picks, so this is a hot read
    # after the first fetch.
    sectors: dict[str, str] = {}
    if args.sector_neutral_quality and args.factor == "composite":
        from src.data.sector_cache import get_sectors
        logger.info(
            "Loading sectors (yfinance cache) for sector-neutral quality..."
        )
        sectors = get_sectors(universe_tickers)
        n_sector = sum(1 for s in sectors.values() if s)
        logger.info(
            "Sector classification: %d/%d names (%.1f%%)",
            n_sector, len(universe_tickers),
            100.0 * n_sector / max(1, len(universe_tickers)),
        )

    window_start = pd.Timestamp(snap.manifest.window_start)
    window_end = pd.Timestamp(snap.manifest.window_end)

    # Trading calendar from SPY (most reliable continuous series).
    spy_idx = spy.index
    calendar = spy_idx[(spy_idx >= window_start) & (spy_idx <= window_end)]
    if calendar.empty:
        raise SystemExit("snapshot has no SPY rows inside the backtest window")

    # Precompute trend state for the whole snapshot (uses full pre-window
    # history so the 200-SMA is computable on day 1 of the window).
    trend_state = trend_state_series(spy)

    # Optional VIX-percentile gate. Aligned to the SPY trading calendar
    # because rebalance days are SPY-indexed; missing VIX dates ffill so
    # weekend / holiday gaps don't accidentally gate-out a Monday.
    vix_state: pd.Series | None = None
    if args.vix_gate:
        vix_df = snap.vix_df
        if vix_df is None or vix_df.empty:
            logger.warning(
                "--vix-gate requested but snapshot has no VIX frame; "
                "the gate will be inert (every day reads as calm)."
            )
        else:
            pct_series = vix_percentile_series(vix_df, window=args.vix_window)
            # Align to SPY trading calendar with ffill so trade days that
            # land on a VIX-missing date inherit the prior reading.
            vix_state = pct_series.reindex(
                spy.index, method="ffill"
            )

    cash = float(args.starting_cash)
    holdings: dict[str, int] = {}
    trades: list[dict] = []
    equity_history: list[tuple[str, float]] = []
    rebalance_log: list[dict] = []
    exposure_history: list[dict] = []

    cost_rate = args.cost_bps / 10_000.0
    rebal_every = max(1, int(args.rebalance_days))
    # Annual borrow rate → per-trading-day fraction. 252 td/year is the
    # convention; calendar-day basis would be 365 and a touch cheaper.
    borrow_per_day = (args.borrow_bps / 10_000.0) / 252.0
    short_decile = (
        args.short_decile if args.short_decile is not None else args.top_decile
    )

    # Step through every trading day.
    prev_day: pd.Timestamp | None = None
    for i, d in enumerate(calendar):
        # Daily borrow charge on short notional. Applied BEFORE the
        # mark-to-market so the equity series reflects realized cost.
        if args.long_short and prev_day is not None:
            short_notional = 0.0
            for t, sh in holdings.items():
                if sh >= 0:
                    continue
                px = _close_on(prices, t, d)
                if px is not None:
                    short_notional += abs(sh) * px
            if short_notional > 0:
                cash -= short_notional * borrow_per_day
        prev_day = d

        eq = _mark_to_market(holdings, cash, prices, d)
        equity_history.append((d.date().isoformat(), eq))

        # Track gross + net exposure for diagnostics.
        if args.long_short:
            gross_long = 0.0
            gross_short = 0.0
            for t, sh in holdings.items():
                px = _close_on(prices, t, d)
                if px is None:
                    continue
                if sh > 0:
                    gross_long += sh * px
                else:
                    gross_short += abs(sh) * px
            exposure_history.append({
                "date": d.date().isoformat(),
                "gross_long": round(gross_long, 2),
                "gross_short": round(gross_short, 2),
                "net": round(gross_long - gross_short, 2),
                "cash": round(cash, 2),
            })

        # Rebalance on day 0 and every rebal_every days thereafter.
        if i % rebal_every != 0:
            continue

        risk_on = (not args.no_regime_filter) and (
            bool(trend_state.loc[d]) if d in trend_state.index else False
        )

        # VIX gate: block entries when the trailing VIX percentile is
        # at-or-above cutoff. Independent of the trend filter — both can
        # fire on the same day. Defaults to permissive when VIX data
        # isn't loaded.
        vix_blocked = False
        if args.vix_gate and vix_state is not None:
            pct = vix_state.loc[d] if d in vix_state.index else None
            if pct is not None and not pd.isna(pct) and pct >= args.vix_cutoff:
                vix_blocked = True

        # If regime is off-and-required OR VIX gate blocks, liquidate
        # everything to cash.
        if (not args.no_regime_filter and not risk_on) or vix_blocked:
            for t, sh in list(holdings.items()):
                px = _close_on(prices, t, d)
                if px is None or sh == 0:
                    holdings.pop(t, None)
                    continue
                proceeds = sh * px
                cost = abs(proceeds) * cost_rate
                cash += proceeds - cost
                side_tag = "sell_vix_gate" if vix_blocked else "sell_regime_off"
                trades.append({
                    "date": d.date().isoformat(),
                    "ticker": t, "side": side_tag,
                    "shares": int(sh), "price": round(px, 4),
                    "cost": round(cost, 4),
                })
                holdings.pop(t)
            rebalance_log.append({
                "date": d.date().isoformat(),
                "action": "vix_off" if vix_blocked else "risk_off",
                "n_positions": 0,
            })
            continue

        # Compute factor; pick top decile.
        ranking, regime_label = _resolve_ranking(
            args.factor, prices, fund_loader, d, universe_tickers,
            regime_profile=args.regime_weights,
            composite_factors=args.composite_factors,
            sector_neutral_quality=args.sector_neutral_quality,
            sectors=sectors,
            vix_df=snap.vix_df if args.regime_weights != "equal" else None,
            spy_df=spy,
            momentum_flavor=args.momentum_flavor,
            include_insider=args.include_insider,
            insider_window_days=args.insider_window_days,
            insider_min_cluster=args.insider_min_cluster,
            include_pead=args.include_pead,
            earnings_histories=earnings_histories,
            pead_drift_window=args.pead_drift_window,
        )
        if ranking.empty:
            continue
        n_long = max(1, int(round(len(ranking) * args.top_decile)))

        # Hysteresis: held names get their rank reduced before selection.
        # The bonus is expressed as a fraction of n_long (e.g. 0.5 = 12
        # slots when n_long=24). A held name ranked 30 with bonus=0.5*24
        # = 12 → effective rank 18 → stays. A name ranked 50 → effective
        # rank 38 → still out. This reduces churn but won't keep a name
        # that's genuinely cratered.
        if args.hysteresis_bonus > 0 and holdings:
            held_longs = {t for t, sh in holdings.items() if sh > 0}
            held_shorts = {t for t, sh in holdings.items() if sh < 0}
            bonus_slots = max(1, int(round(args.hysteresis_bonus * n_long)))
            ranking = ranking.copy()
            # Effective rank for selection. Longs get rank reduced (lower
            # number = better). Shorts get rank INCREASED (higher = worse
            # = stays as a short) — symmetrical stickiness.
            def _adjust(row):
                r = int(row["rank"])
                t = row["ticker"]
                if t in held_longs:
                    return max(1, r - bonus_slots)
                if t in held_shorts:
                    return r + bonus_slots
                return r
            ranking["_eff_rank"] = ranking.apply(_adjust, axis=1)
            ranking = (
                ranking.sort_values("_eff_rank").reset_index(drop=True)
            )

        long_target = ranking.iloc[:n_long]["ticker"].tolist()
        # Optional post-composite low-vol filter: drop the top-vol
        # names from the picks. Computed on the full snapshot universe
        # so a factor-skewed top decile doesn't shift the vol cutoff.
        if 0 < args.low_vol_keep_pct < 1.0:
            long_target = low_vol_filter(
                prices, long_target, d,
                window=args.low_vol_window,
                keep_pct=args.low_vol_keep_pct,
            )
        long_set = set(long_target)

        short_set: set[str] = set()
        if args.long_short:
            n_short = max(1, int(round(len(ranking) * short_decile)))
            # Bottom-N by rank (highest rank numbers = worst composite).
            short_target = ranking.iloc[-n_short:]["ticker"].tolist()
            # Apply the same low-vol filter to shorts so we don't accumulate
            # the worst-of-vol on the short side either.
            if 0 < args.low_vol_keep_pct < 1.0:
                short_target = low_vol_filter(
                    prices, short_target, d,
                    window=args.low_vol_window,
                    keep_pct=args.low_vol_keep_pct,
                )
            short_set = set(short_target)
            # A ticker that ranks in both decile sets (shouldn't happen
            # for d05_r63 on a 480-name universe, but defensive) is
            # treated as a long. Shorts should never overlap with longs.
            short_set -= long_set

        target_set = long_set | short_set

        # Sell names not in either target set (close out positions).
        for t in list(holdings.keys()):
            if t in target_set:
                continue
            sh = holdings.pop(t)
            px = _close_on(prices, t, d)
            if px is None or sh == 0:
                continue
            proceeds = sh * px  # negative shares produce negative proceeds
            cost = abs(proceeds) * cost_rate
            cash += proceeds - cost
            trades.append({
                "date": d.date().isoformat(), "ticker": t,
                "side": "close_rebalance",
                "shares": int(sh), "price": round(px, 4),
                "cost": round(cost, 4),
            })

        # Sizing: equal-weight within each side. Long-short splits
        # equity in half; long-only puts it all on the long side.
        current_eq = _mark_to_market(holdings, cash, prices, d)
        long_capital = (
            current_eq * 0.5 if args.long_short else current_eq
        )
        short_capital = current_eq * 0.5 if args.long_short else 0.0
        per_long = (
            long_capital / max(1, len(long_set)) if long_set else 0.0
        )
        per_short = (
            short_capital / max(1, len(short_set)) if short_set else 0.0
        )

        # Resize longs.
        for t in long_set:
            px = _close_on(prices, t, d)
            if px is None or px <= 0:
                continue
            target_shares = int(per_long // px)
            current_shares = holdings.get(t, 0)
            delta = target_shares - current_shares
            if delta == 0:
                continue
            notional = abs(delta) * px
            cost = notional * cost_rate
            cash -= delta * px
            cash -= cost
            holdings[t] = current_shares + delta
            if holdings[t] == 0:
                del holdings[t]
            trades.append({
                "date": d.date().isoformat(), "ticker": t,
                "side": "buy" if delta > 0 else "sell_rebalance",
                "shares": int(abs(delta)), "price": round(px, 4),
                "cost": round(cost, 4),
            })

        # Resize shorts (negative target_shares).
        for t in short_set:
            px = _close_on(prices, t, d)
            if px is None or px <= 0:
                continue
            target_shares = -int(per_short // px)  # negative = short
            current_shares = holdings.get(t, 0)
            delta = target_shares - current_shares
            if delta == 0:
                continue
            notional = abs(delta) * px
            cost = notional * cost_rate
            cash -= delta * px  # negative delta on a short ADDs cash (short sale)
            cash -= cost
            holdings[t] = current_shares + delta
            if holdings[t] == 0:
                del holdings[t]
            trades.append({
                "date": d.date().isoformat(), "ticker": t,
                "side": "short" if delta < 0 else "cover",
                "shares": int(abs(delta)), "price": round(px, 4),
                "cost": round(cost, 4),
            })

        rebalance_log.append({
            "date": d.date().isoformat(),
            "action": "rebalance",
            "n_positions": len(holdings),
            "n_long": sum(1 for v in holdings.values() if v > 0),
            "n_short": sum(1 for v in holdings.values() if v < 0),
            "regime": regime_label,
        })

    # ----- metrics -----
    eq_series = pd.Series(
        [v for _, v in equity_history],
        index=pd.to_datetime([d for d, _ in equity_history]),
    )
    daily_rets = eq_series.pct_change().dropna()
    ann_sharpe = _annualize_sharpe(daily_rets)
    total_return = float(eq_series.iloc[-1] / args.starting_cash - 1.0)
    max_dd = _max_drawdown(eq_series)

    # SPY benchmark over the same window.
    spy_win = spy[(spy.index >= calendar[0]) & (spy.index <= calendar[-1])]
    spy_total = float(spy_win["Close"].iloc[-1] / spy_win["Close"].iloc[0] - 1.0)
    spy_daily = spy_win["Close"].pct_change().dropna()
    spy_sharpe = _annualize_sharpe(spy_daily)
    spy_dd = _max_drawdown(spy_win["Close"])

    # CAGR
    years = max(1e-6, (calendar[-1] - calendar[0]).days / 365.25)
    cagr = (1 + total_return) ** (1 / years) - 1

    wf = _walk_forward_folds(daily_rets, n_folds=5)

    out = {
        "strategy": args.strategy_label,
        "snapshot_id": args.snapshot_id,
        "snapshot_manifest": {
            "universe_label": snap.manifest.universe_label,
            "universe_as_of": snap.manifest.universe_as_of,
            "window_start": snap.manifest.window_start,
            "window_end": snap.manifest.window_end,
            "n_tickers_with_prices": snap.manifest.n_tickers_with_prices,
        },
        "parameters": {
            "top_decile": args.top_decile,
            "rebalance_days": args.rebalance_days,
            "cost_bps": args.cost_bps,
            "starting_cash": args.starting_cash,
            "regime_filter_enabled": not args.no_regime_filter,
        },
        "metrics": {
            "total_return_pct": round(total_return * 100, 2),
            "cagr_pct": round(cagr * 100, 2),
            "ann_sharpe": round(ann_sharpe, 3),
            "max_drawdown_pct": round(max_dd * 100, 2),
            "n_trades": len(trades),
            "n_rebalances": sum(1 for r in rebalance_log if r["action"] == "rebalance"),
            "n_risk_off_periods": sum(1 for r in rebalance_log if r["action"] == "risk_off"),
            "final_equity": round(float(eq_series.iloc[-1]), 2),
        },
        "benchmark_spy": {
            "total_return_pct": round(spy_total * 100, 2),
            "ann_sharpe": round(spy_sharpe, 3),
            "max_drawdown_pct": round(spy_dd * 100, 2),
        },
        "alpha_vs_spy_pct": round((total_return - spy_total) * 100, 2),
        "walk_forward": wf,
        "trades_sample": trades[:200],
        "rebalance_log": rebalance_log,
        "equity_curve": equity_history,
        "long_short_enabled": bool(args.long_short),
        "exposure_history_sample": exposure_history[::21] if exposure_history else [],
    }
    return out


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = _parse_args()
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    result = run(args)
    Path(args.output).write_text(
        json.dumps(result, indent=2, default=str),
        encoding="utf-8",
    )
    m = result["metrics"]
    b = result["benchmark_spy"]
    wf = result["walk_forward"]
    logger.info(
        "=== %s | snap=%s window=%s -> %s ===",
        result["strategy"], args.snapshot_id,
        result["snapshot_manifest"]["window_start"],
        result["snapshot_manifest"]["window_end"],
    )
    logger.info(
        "STRATEGY: total=%.2f%% sharpe=%.2f maxDD=%.2f%% trades=%d rebals=%d "
        "risk_off=%d",
        m["total_return_pct"], m["ann_sharpe"], m["max_drawdown_pct"],
        m["n_trades"], m["n_rebalances"], m["n_risk_off_periods"],
    )
    logger.info(
        "SPY:      total=%.2f%% sharpe=%.2f maxDD=%.2f%%",
        b["total_return_pct"], b["ann_sharpe"], b["max_drawdown_pct"],
    )
    logger.info(
        "ALPHA vs SPY: %+.2f%% | Walk-forward: mean_sharpe=%.2f "
        "min_sharpe=%.2f passed=%s",
        result["alpha_vs_spy_pct"], wf["mean_sharpe"], wf["min_sharpe"],
        wf["passed"],
    )
    print(args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
