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
from src.factors.exposure_scaling import (
    DEFAULT_FLOOR as EXPOSURE_DEFAULT_FLOOR,
    DEFAULT_HIGH_THRESHOLD as EXPOSURE_DEFAULT_HIGH,
    DEFAULT_LOW_THRESHOLD as EXPOSURE_DEFAULT_LOW,
    DEFAULT_SMOOTHING_WINDOW as EXPOSURE_DEFAULT_SMOOTHING,
    exposure_at,
)
from src.factors.insider_cluster import insider_cluster_factor
from src.factors.momentum import momentum_12_1
from src.factors.pead import pead_factor
from src.factors.quality import quality_factor
from src.factors.regime import (
    ENTRY_SMA_WINDOW as REGIME_DEFAULT_ENTRY_SMA,
    is_risk_on,
    trend_state_asymmetric_series,
    trend_state_series,
)
from src.factors.regime_weights import list_profiles, weights_for
from src.factors.residual_momentum import residual_momentum_12_1
from src.factors.value import value_factor
from src.factors.vix_regime import (
    DEFAULT_ABSOLUTE_THRESHOLD as VIX_DEFAULT_ABSOLUTE_THRESHOLD,
    DEFAULT_CUTOFF as VIX_DEFAULT_CUTOFF,
    DEFAULT_SMOOTHING_WINDOW as VIX_DEFAULT_SMOOTHING_WINDOW,
    DEFAULT_WINDOW as VIX_DEFAULT_WINDOW,
    vix_percentile_series,
    vix_smoothed_series,
)
from src.factors.volatility import low_vol_filter
from src.storage.snapshot import load_snapshot

logger = logging.getLogger("run_factor_backtest")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--snapshot-id", required=True)
    p.add_argument("--top-decile", type=float, default=0.03,
                   help="Fraction of universe to hold (default 0.03 = top 3%%). "
                        "Calibrated 2026-05-19: d03 doubles cross-window α vs "
                        "d05 (+5.70%% → +10.80%%) and flips bull-window from "
                        "-6.60%% to +2.37%%. Cost: bull-window DD widens from "
                        "-14.5%% to -19.2%%. Matches live daily_factor_picks.")
    p.add_argument("--rebalance-days", type=int, default=63,
                   help="Trading-day cadence for rebalance (default 63 = "
                        "quarterly, matches d05/d03 production since 2026-05-19. "
                        "Pass 21 for monthly, 252 for annual.)")
    p.add_argument("--cost-bps", type=float, default=5.0,
                   help="One-way transaction cost in basis points (default 5).")
    p.add_argument("--starting-cash", type=float, default=10_000.0)
    p.add_argument("--strategy-label", default="momentum_12_1+regime",
                   help="Label printed in the output; useful when sweeping.")
    p.add_argument("--no-regime-filter", action="store_true",
                   help="Disable the SPY 200d-SMA trend filter (run "
                        "always-on momentum). Use only for ablation.")
    p.add_argument("--asymmetric-trend", action=argparse.BooleanOptionalAction,
                   default=True,
                   help="Use the asymmetric trend filter (fast entry-SMA "
                        "level check both ways). Default ON since "
                        "2026-05-19 to match live daily picks. Pass "
                        "--no-asymmetric-trend to revert to the symmetric "
                        "200-SMA filter (used only for ablation). The "
                        "2026-05-18 diagnosis showed the 200-SMA is too "
                        "lagging for re-entry: post-Oct-2022 the strategy "
                        "missed +16%% of recovery waiting for the slow signal.")
    p.add_argument("--entry-sma", type=int, default=REGIME_DEFAULT_ENTRY_SMA,
                   help=f"Re-entry SMA for --asymmetric-trend (default "
                        f"{REGIME_DEFAULT_ENTRY_SMA} td). Faster = catches "
                        f"recoveries earlier but more sensitive to chop.")
    p.add_argument("--regime-file",
                   help="JSON {YYYY-MM-DD: bool} risk-on/off series used as the "
                        "regime gate, OVERRIDING the SPY-SMA trend filter. For "
                        "testing alternative gates (e.g. market-breadth).")
    p.add_argument("--daily-regime", action=argparse.BooleanOptionalAction, default=False,
                   help="Evaluate the regime gate EVERY trading day — exit to cash "
                        "the day it flips off, re-enter the standing target when it "
                        "flips back on — decoupling it from the 63-day factor "
                        "rebalance. Default off = legacy (regime checked only at "
                        "rebalances). Targets the cadence leak (project_regime_whipsaw).")
    p.add_argument("--rebal-offset", type=int, default=0,
                   help="Shift the rebalance-grid start by N trading days (phase). "
                        "Phase-envelope robustness: sweep 0..rebalance_days-1 to see "
                        "if a result is an artifact of WHERE the 63-day grid lands.")
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
    p.add_argument("--vix-abs-gate", action="store_true",
                   help="Block new entries when the smoothed-VIX absolute "
                        "level >= --vix-abs-threshold. Complement to "
                        "--vix-gate: percentile self-normalizes (sustained "
                        "stress reads as median); this one uses an absolute "
                        "level so 2022 actually triggers. Both gates can "
                        "fire independently; either firing blocks.")
    p.add_argument("--vix-abs-threshold", type=float,
                   default=VIX_DEFAULT_ABSOLUTE_THRESHOLD,
                   help=f"Absolute VIX threshold for --vix-abs-gate "
                        f"(default {VIX_DEFAULT_ABSOLUTE_THRESHOLD:.0f}). "
                        f"28 catches May 2022 (21d-MA 28.3) without "
                        f"firing on the Aug 2024 single-day spike (21d-MA "
                        f"never crossed 20).")
    p.add_argument("--vix-abs-smoothing", type=int,
                   default=VIX_DEFAULT_SMOOTHING_WINDOW,
                   help=f"Rolling-mean window for --vix-abs-gate (default "
                        f"{VIX_DEFAULT_SMOOTHING_WINDOW} td).")
    p.add_argument("--vix-exposure-scaling", action="store_true",
                   help="Continuous VIX-based exposure scaling. Replaces "
                        "the binary --vix-abs-gate / --vix-gate with a "
                        "piecewise-linear ramp from 1.0 (at smoothed-VIX <= "
                        "--vix-exposure-low) to --vix-exposure-floor (at "
                        ">= --vix-exposure-high). Motivated by the "
                        "2026-05-19 bull-DD diagnostic: 70%% of the d03 "
                        "wider DD is mechanical (concentration -> higher "
                        "beta -> more market exposure in corrections); "
                        "continuous derisking targets that mechanical "
                        "portion without the V-shape failure mode of "
                        "binary gates. Off by default; validate before "
                        "promoting.")
    p.add_argument("--vix-exposure-low", type=float,
                   default=EXPOSURE_DEFAULT_LOW,
                   help=f"Smoothed-VIX level at and below which exposure "
                        f"stays at 1.0 (default {EXPOSURE_DEFAULT_LOW:.1f}).")
    p.add_argument("--vix-exposure-high", type=float,
                   default=EXPOSURE_DEFAULT_HIGH,
                   help=f"Smoothed-VIX level at and above which exposure "
                        f"clamps to --vix-exposure-floor (default "
                        f"{EXPOSURE_DEFAULT_HIGH:.1f}). Calibrated to fire "
                        f"on May 2022 sustained stress without firing on "
                        f"Aug 2024 single-day spikes.")
    p.add_argument("--vix-exposure-floor", type=float,
                   default=EXPOSURE_DEFAULT_FLOOR,
                   help=f"Minimum exposure multiplier at extreme stress "
                        f"(default {EXPOSURE_DEFAULT_FLOOR:.2f}). Never "
                        f"goes to zero -- keeps factor exposure live so "
                        f"V-shape recoveries can still earn.")
    p.add_argument("--vix-exposure-smoothing", type=int,
                   default=EXPOSURE_DEFAULT_SMOOTHING,
                   help=f"Rolling-mean window for --vix-exposure-scaling "
                        f"(default {EXPOSURE_DEFAULT_SMOOTHING} td).")
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
    p.add_argument("--include-pead", action=argparse.BooleanOptionalAction,
                   default=True,
                   help="Add the Bernard-Thomas PEAD factor as a 4th "
                        "(or 5th) rank frame. Default ON since 2026-05-19 "
                        "to match live daily picks (+2.53pp avg α validated "
                        "2026-05-18). Pass --no-include-pead for ablation. "
                        "Loads earnings histories from --earnings-cache-dir.")
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
    p.add_argument("--sector-neutral-quality",
                   action=argparse.BooleanOptionalAction, default=True,
                   help="Rank quality WITHIN sector instead of "
                        "cross-sectional. Default ON since 2026-05-19 to "
                        "match live daily picks (+4.93pp avg α stacked "
                        "with hysteresis, 2026-05-18). Pass "
                        "--no-sector-neutral-quality for ablation. "
                        "Motivated by 2026-05-18: cross-sectional quality "
                        "picks defensive sectors that get killed in "
                        "rotation regimes.")
    p.add_argument("--momentum-flavor",
                   default="raw",
                   choices=("raw", "residual"),
                   help="Momentum implementation. 'raw' is the canonical "
                        "Jegadeesh-Titman 12-1 (current default). 'residual' "
                        "is Blitz-Huij-Martens 2011 residual momentum — "
                        "strips SPY beta before cumulating. Applies to the "
                        "'momentum' single factor and to the momentum sleeve "
                        "inside 'composite'.")
    p.add_argument("--hysteresis-bonus", type=float, default=0.75,
                   help="Hysteresis (stickiness) bonus for currently-held "
                        "names, expressed as a fraction of the target N. "
                        "Default 0.75 since 2026-05-19 to match live daily "
                        "picks (+4.31pp avg α validated 2026-05-18; stress-"
                        "window DD improves -15.4%% → -8.2%%). Pass 0.0 "
                        "for ablation (pure rank-based selection).")
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
    from src.factors.fundamentals_pit_loader import (
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


def _capm_alpha_beta(strat_rets: pd.Series, spy_rets: pd.Series) -> tuple[float, float]:
    """Jensen's alpha (annualized %) and market beta from an OLS of daily
    strategy returns on SPY.

    Risk-free is taken as 0 — a documented simplification; over our windows
    it shifts alpha by < the phase-noise envelope. Unlike raw excess return,
    this separates stock-selection skill from the beta a regime-gated /
    cash-heavy book carries: sitting in cash through a selloff is LOW BETA,
    not alpha, and `alpha_vs_spy_pct` (excess return) credits it as alpha.
    """
    df = pd.concat([strat_rets.rename("s"), spy_rets.rename("m")], axis=1).dropna()
    if len(df) < 30 or df["m"].var() == 0:
        return 0.0, 0.0
    beta = float(df["s"].cov(df["m"]) / df["m"].var())
    alpha_daily = float(df["s"].mean() - beta * df["m"].mean())
    return ((1.0 + alpha_daily) ** 252 - 1.0) * 100.0, beta


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


def _load_earnings_histories_if_pead(args: argparse.Namespace, universe_tickers: list[str]):
    """PEAD analyzer needs per-ticker earnings histories. Loaded once
    up front (parquet cache hits after the first run)."""
    if not args.include_pead:
        return None
    from src.factors.earnings_cache import load_earnings_histories
    logger.info("Loading earnings histories for PEAD...")
    histories = load_earnings_histories(
        universe_tickers, Path(args.earnings_cache_dir),
    )
    logger.info(
        "Loaded earnings histories for %d / %d tickers",
        sum(1 for h in histories.values() if h is not None),
        len(universe_tickers),
    )
    return histories


def _load_fundamentals_if_needed(args: argparse.Namespace, universe_tickers: list[str]):
    """Quality / value / composite all need the EDGAR PIT panel. Momentum-
    only runs skip this load entirely.

    Reproducibility caching: if the snapshot dir has a frozen EDGAR PIT
    panel (``fundamentals_pit.json``), load from there instead of from
    Postgres. First run on a snapshot pulls from Postgres AND writes the
    cache; subsequent runs read from the cache. This eliminates the
    cross-session drift observed on 2026-05-19 where the same backtest
    config produced different alpha (+39.5% vs +29.9%) hours apart
    because Postgres EDGAR rows had been re-ingested between runs.
    """
    if args.factor not in ("quality", "value", "composite"):
        return None
    from src.factors.fundamentals_pit_loader import FundamentalsPITLoader

    cache_path = Path("data/snapshots") / args.snapshot_id / "fundamentals_pit.json"
    if cache_path.exists():
        logger.info(
            "Loading EDGAR PIT panel from snapshot cache: %s", cache_path,
        )
        loader = FundamentalsPITLoader.from_json(cache_path)
    else:
        logger.info(
            "Pre-loading EDGAR PIT fundamentals for %d tickers from Postgres...",
            len(universe_tickers),
        )
        loader = _load_pit_fundamentals(universe_tickers)
        try:
            loader.to_json(cache_path)
            logger.info(
                "Cached EDGAR PIT panel to %s for reproducible future runs",
                cache_path,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "Failed to write EDGAR PIT cache to %s: %s "
                "(backtest continues; next run will re-query Postgres)",
                cache_path, e,
            )
    cov = loader.coverage()
    n_covered = sum(1 for c in cov.values() if c > 0)
    logger.info(
        "Fundamentals coverage: %d/%d tickers have ≥1 EDGAR row "
        "(%.1f%%)",
        n_covered, len(universe_tickers),
        100.0 * n_covered / max(1, len(universe_tickers)),
    )
    return loader


def _load_sectors_if_sn_quality(args: argparse.Namespace, universe_tickers: list[str]) -> dict[str, str]:
    """Sectors are only needed when sector-neutral quality is on. yfinance
    cache is shared with daily_factor_picks, so first-run pays the
    network and subsequent runs are hot."""
    if not (args.sector_neutral_quality and args.factor == "composite"):
        return {}
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
    return sectors


def _build_trading_calendar(spy: pd.DataFrame, snap_manifest) -> pd.DatetimeIndex:
    """SPY-indexed trading days inside the snapshot's window."""
    window_start = pd.Timestamp(snap_manifest.window_start)
    window_end = pd.Timestamp(snap_manifest.window_end)
    spy_idx = spy.index
    calendar = spy_idx[(spy_idx >= window_start) & (spy_idx <= window_end)]
    if calendar.empty:
        raise SystemExit("snapshot has no SPY rows inside the backtest window")
    return calendar


def _build_vix_state(args: argparse.Namespace, snap, spy: pd.DataFrame) -> pd.Series | None:
    """Aligned VIX-percentile series for the gate. ffill onto SPY calendar
    so weekend / holiday gaps don't accidentally gate-out a Monday.
    Returns None when the gate is off or VIX data is missing."""
    if not args.vix_gate:
        return None
    vix_df = snap.vix_df
    if vix_df is None or vix_df.empty:
        logger.warning(
            "--vix-gate requested but snapshot has no VIX frame; "
            "the gate will be inert (every day reads as calm)."
        )
        return None
    pct_series = vix_percentile_series(vix_df, window=args.vix_window)
    return pct_series.reindex(spy.index, method="ffill")


def _build_vix_abs_state(args: argparse.Namespace, snap, spy: pd.DataFrame) -> pd.Series | None:
    """Smoothed-VIX absolute level on the SPY calendar. None when the
    --vix-abs-gate is off or VIX data missing."""
    if not args.vix_abs_gate:
        return None
    vix_df = snap.vix_df
    if vix_df is None or vix_df.empty:
        logger.warning(
            "--vix-abs-gate requested but snapshot has no VIX frame; "
            "the abs-gate will be inert (no day reads as stress)."
        )
        return None
    smoothed = vix_smoothed_series(vix_df, window=args.vix_abs_smoothing)
    return smoothed.reindex(spy.index, method="ffill")


def _record_exposure(
    holdings: dict[str, int], cash: float,
    prices: dict, d: pd.Timestamp,
) -> dict:
    """One row of the per-day exposure log: gross long, gross short, net,
    cash. Used by long-short runs for diagnostic plots."""
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
    return {
        "date": d.date().isoformat(),
        "gross_long": round(gross_long, 2),
        "gross_short": round(gross_short, 2),
        "net": round(gross_long - gross_short, 2),
        "cash": round(cash, 2),
    }


def _gate_blocks_entries(
    args: argparse.Namespace,
    trend_state: pd.Series,
    vix_state: pd.Series | None,
    vix_abs_state: pd.Series | None,
    d: pd.Timestamp,
) -> tuple[bool, bool]:
    """Return ``(blocked, vix_blocked)``. Three-channel gate: any one of
    (200-SMA trend off, VIX percentile >= cutoff, smoothed-VIX >=
    abs threshold) blocks new entries. vix_blocked is True iff either
    of the VIX channels fired."""
    risk_on = (not args.no_regime_filter) and (
        bool(trend_state.loc[d]) if d in trend_state.index else False
    )
    vix_blocked = False
    if args.vix_gate and vix_state is not None:
        pct = vix_state.loc[d] if d in vix_state.index else None
        if pct is not None and not pd.isna(pct) and pct >= args.vix_cutoff:
            vix_blocked = True
    if args.vix_abs_gate and vix_abs_state is not None:
        lvl = vix_abs_state.loc[d] if d in vix_abs_state.index else None
        if lvl is not None and not pd.isna(lvl) and lvl >= args.vix_abs_threshold:
            vix_blocked = True
    blocked = (not args.no_regime_filter and not risk_on) or vix_blocked
    return blocked, vix_blocked


def _liquidate_all_to_cash(
    holdings: dict[str, int], cash: float,
    trades: list[dict], rebalance_log: list[dict],
    prices: dict, d: pd.Timestamp,
    cost_rate: float, vix_blocked: bool,
) -> float:
    """Sell every position to cash. Used when the regime trend filter is
    off OR the VIX gate fires. Returns the updated cash balance."""
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
    return cash


def _apply_hysteresis_to_ranking(
    args: argparse.Namespace, ranking: pd.DataFrame,
    holdings: dict[str, int], n_long: int,
) -> pd.DataFrame:
    """Held-name rank bonus: longs get rank reduced (lower = better),
    shorts get rank increased (higher = stays short). Names that drop
    past the envelope still get evicted."""
    if args.hysteresis_bonus <= 0 or not holdings:
        return ranking
    held_longs = {t for t, sh in holdings.items() if sh > 0}
    held_shorts = {t for t, sh in holdings.items() if sh < 0}
    bonus_slots = max(1, int(round(args.hysteresis_bonus * n_long)))
    ranking = ranking.copy()

    def _adjust(row):
        r = int(row["rank"])
        t = row["ticker"]
        if t in held_longs:
            return max(1, r - bonus_slots)
        if t in held_shorts:
            return r + bonus_slots
        return r

    ranking["_eff_rank"] = ranking.apply(_adjust, axis=1)
    return ranking.sort_values("_eff_rank").reset_index(drop=True)


def _select_long_short_targets(
    args: argparse.Namespace, ranking: pd.DataFrame,
    prices: dict, d: pd.Timestamp,
    n_long: int, short_decile: float,
) -> tuple[set[str], set[str]]:
    """Top-N longs + bottom-N shorts after low-vol filter. Shorts can't
    overlap with longs (defensive — d05_r63 on a 480-name universe
    wouldn't produce overlap, but the slice math doesn't enforce it)."""
    long_target = ranking.iloc[:n_long]["ticker"].tolist()
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
        short_target = ranking.iloc[-n_short:]["ticker"].tolist()
        if 0 < args.low_vol_keep_pct < 1.0:
            short_target = low_vol_filter(
                prices, short_target, d,
                window=args.low_vol_window,
                keep_pct=args.low_vol_keep_pct,
            )
        short_set = set(short_target) - long_set
    return long_set, short_set


def _close_off_target_positions(
    target_set: set[str], holdings: dict[str, int], cash: float,
    trades: list[dict], prices: dict, d: pd.Timestamp, cost_rate: float,
) -> float:
    """Sell every currently-held name that's NOT in the new target set.
    Negative-share positions produce negative proceeds (cover the short).
    Returns the updated cash balance."""
    for t in list(holdings.keys()):
        if t in target_set:
            continue
        sh = holdings.pop(t)
        px = _close_on(prices, t, d)
        if px is None or sh == 0:
            continue
        proceeds = sh * px
        cost = abs(proceeds) * cost_rate
        cash += proceeds - cost
        trades.append({
            "date": d.date().isoformat(), "ticker": t,
            "side": "close_rebalance",
            "shares": int(sh), "price": round(px, 4),
            "cost": round(cost, 4),
        })
    return cash


def _resize_one_side(
    target_set: set[str], holdings: dict[str, int], cash: float,
    trades: list[dict], prices: dict, d: pd.Timestamp,
    per_position: float, cost_rate: float,
    *, is_long: bool,
) -> float:
    """Buy / sell to bring each target to its sized share count. Long
    side: target_shares > 0; short side: target_shares < 0. A negative
    delta on a short ADDs cash (the short sale itself). Returns the
    updated cash balance."""
    # sorted() not raw set iteration: set order is non-deterministic across
    # runs, which left trades_sample byte-unstable (metrics were unaffected
    # because per_position is precomputed, but order-dependent sizing would
    # break). Deterministic ticker order keeps backtest output bit-identical.
    for t in sorted(target_set):
        px = _close_on(prices, t, d)
        if px is None or px <= 0:
            continue
        magnitude = int(per_position // px)
        target_shares = magnitude if is_long else -magnitude
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
        if is_long:
            side_tag = "buy" if delta > 0 else "sell_rebalance"
        else:
            side_tag = "short" if delta < 0 else "cover"
        trades.append({
            "date": d.date().isoformat(), "ticker": t,
            "side": side_tag,
            "shares": int(abs(delta)), "price": round(px, 4),
            "cost": round(cost, 4),
        })
    return cash


def _compute_metrics_and_assemble(
    args: argparse.Namespace, snap,
    calendar: pd.DatetimeIndex, spy: pd.DataFrame,
    equity_history: list[tuple[str, float]],
    trades: list[dict], rebalance_log: list[dict],
    exposure_history: list[dict],
) -> dict:
    """Compute every metric + benchmark comparison + walk-forward gate
    and assemble the final result dict that callers persist as JSON."""
    eq_series = pd.Series(
        [v for _, v in equity_history],
        index=pd.to_datetime([d for d, _ in equity_history]),
    )
    daily_rets = eq_series.pct_change().dropna()
    ann_sharpe = _annualize_sharpe(daily_rets)
    total_return = float(eq_series.iloc[-1] / args.starting_cash - 1.0)
    max_dd = _max_drawdown(eq_series)

    spy_win = spy[(spy.index >= calendar[0]) & (spy.index <= calendar[-1])]
    spy_total = float(spy_win["Close"].iloc[-1] / spy_win["Close"].iloc[0] - 1.0)
    spy_daily = spy_win["Close"].pct_change().dropna()
    spy_sharpe = _annualize_sharpe(spy_daily)
    spy_dd = _max_drawdown(spy_win["Close"])
    capm_alpha_pct, beta = _capm_alpha_beta(daily_rets, spy_daily)

    years = max(1e-6, (calendar[-1] - calendar[0]).days / 365.25)
    cagr = (1 + total_return) ** (1 / years) - 1
    wf = _walk_forward_folds(daily_rets, n_folds=5)

    return {
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
            "asymmetric_trend": bool(args.asymmetric_trend),
            "entry_sma": args.entry_sma,
            "include_pead": bool(args.include_pead),
            "sector_neutral_quality": bool(args.sector_neutral_quality),
            "hysteresis_bonus": args.hysteresis_bonus,
            "factor": args.factor,
            "composite_factors": args.composite_factors,
            "momentum_flavor": args.momentum_flavor,
            "vix_exposure_scaling": bool(args.vix_exposure_scaling),
            "vix_exposure_low": args.vix_exposure_low,
            "vix_exposure_high": args.vix_exposure_high,
            "vix_exposure_floor": args.vix_exposure_floor,
            "vix_exposure_smoothing": args.vix_exposure_smoothing,
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
        # Raw total-return gap — beta-blind. For a regime-gated/cash-heavy or
        # long-short book this OVERSTATES skill (cash beating a falling SPY
        # reads as "alpha"). Use capm_alpha_pct for the honest measure.
        "alpha_vs_spy_pct": round((total_return - spy_total) * 100, 2),
        "capm_alpha_pct": round(capm_alpha_pct, 2),
        "beta": round(beta, 3),
        "walk_forward": wf,
        "trades_sample": trades[:200],
        "rebalance_log": rebalance_log,
        "equity_curve": equity_history,
        "long_short_enabled": bool(args.long_short),
        "exposure_history_sample": exposure_history[::21] if exposure_history else [],
    }


def _load_frozen_membership(snapshot_id: str):
    """Load the snapshot's frozen S&P 500 PIT oracle (audit #16) for
    per-rebalance universe re-resolution. Returns None for snapshots built
    before membership-freezing (legacy / ad-hoc / russell_1000); callers
    then fall back to the frozen ticker list."""
    cur = Path("data/snapshots") / snapshot_id / "sp500_current.csv"
    ch = Path("data/snapshots") / snapshot_id / "sp500_changes.csv"
    if not (cur.exists() and ch.exists()):
        return None
    from src.universe.sp500_pit import SP500Membership

    return SP500Membership.from_csvs(current_path=cur, changes_path=ch)


def run(args: argparse.Namespace) -> dict:
    snap = load_snapshot(args.snapshot_id)
    prices = snap.price_data
    spy = snap.spy_df
    if spy is None or spy.empty:
        raise SystemExit(f"snapshot {args.snapshot_id} has no SPY frame")

    universe_tickers = sorted(prices.keys())
    membership = _load_frozen_membership(args.snapshot_id)
    if membership is None:
        logger.warning(
            "no frozen PIT membership in snapshot %s — universe is FROZEN at "
            "its ticker set (audit #16 eligibility bias); rebuild via "
            "scripts.build_snapshot to re-resolve membership per rebalance.",
            args.snapshot_id,
        )
    earnings_histories = _load_earnings_histories_if_pead(args, universe_tickers)
    fund_loader = _load_fundamentals_if_needed(args, universe_tickers)
    sectors = _load_sectors_if_sn_quality(args, universe_tickers)
    calendar = _build_trading_calendar(spy, snap.manifest)
    if args.regime_file:
        _raw = json.loads(Path(args.regime_file).read_text())
        _rs = pd.Series({pd.Timestamp(k): bool(v) for k, v in _raw.items()}).sort_index()
        _full = pd.date_range(_rs.index.min(), _rs.index.max(), freq="D")
        trend_state = (_rs.reindex(_rs.index.union(_full)).sort_index()
                       .ffill().fillna(False).astype(bool))
    elif args.asymmetric_trend:
        trend_state = trend_state_asymmetric_series(
            spy, entry_sma=args.entry_sma,
        )
    else:
        trend_state = trend_state_series(spy)
    vix_state = _build_vix_state(args, snap, spy)
    vix_abs_state = _build_vix_abs_state(args, snap, spy)

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

    standing_long: set[str] = set()   # latest factor target, for daily re-entry
    standing_short: set[str] = set()

    def _apply_target(long_set, short_set, cash):
        """Resize holdings to (long_set, short_set), equal-weight per side,
        VIX-scaled. Shared by the 63-day rebalance and the daily regime re-entry.
        Reads d/holdings/trades from the enclosing loop scope at call time."""
        cash = _close_off_target_positions(
            long_set | short_set, holdings, cash, trades, prices, d, cost_rate,
        )
        current_eq = _mark_to_market(holdings, cash, prices, d)
        if args.vix_exposure_scaling and snap.vix_df is not None and not snap.vix_df.empty:
            em = exposure_at(
                snap.vix_df, d, smoothing_window=args.vix_exposure_smoothing,
                low_threshold=args.vix_exposure_low, high_threshold=args.vix_exposure_high,
                floor=args.vix_exposure_floor,
            )
        else:
            em = 1.0
        long_capital = (current_eq * 0.5 if args.long_short else current_eq) * em
        short_capital = (current_eq * 0.5 if args.long_short else 0.0) * em
        per_long = long_capital / max(1, len(long_set)) if long_set else 0.0
        per_short = short_capital / max(1, len(short_set)) if short_set else 0.0
        cash = _resize_one_side(long_set, holdings, cash, trades, prices, d, per_long,
                                cost_rate, is_long=True)
        cash = _resize_one_side(short_set, holdings, cash, trades, prices, d, per_short,
                                cost_rate, is_long=False)
        return cash, em

    # Step through every trading day.
    prev_day: pd.Timestamp | None = None
    for i, d in enumerate(calendar):
        # Daily borrow charge on short notional, applied BEFORE
        # mark-to-market so the equity series reflects realized cost.
        if args.long_short and prev_day is not None:
            short_notional = sum(
                abs(sh) * (_close_on(prices, t, d) or 0)
                for t, sh in holdings.items() if sh < 0
            )
            if short_notional > 0:
                cash -= short_notional * borrow_per_day
        prev_day = d

        eq = _mark_to_market(holdings, cash, prices, d)
        equity_history.append((d.date().isoformat(), eq))
        if args.long_short:
            exposure_history.append(_record_exposure(holdings, cash, prices, d))

        is_rebal = (i % rebal_every == args.rebal_offset % rebal_every)
        check_regime = args.daily_regime or is_rebal
        blocked = vix_blocked = False
        if check_regime:
            blocked, vix_blocked = _gate_blocks_entries(
                args, trend_state, vix_state, vix_abs_state, d,
            )

        # EXIT: a risk-off check-day while holding -> liquidate to cash. With
        # --daily-regime this fires intra-rebalance (the cadence fix: exit the
        # day the gate flips, not up to 63 days later); else only at rebalances.
        if check_regime and blocked:
            if holdings:
                cash = _liquidate_all_to_cash(
                    holdings, cash, trades, rebalance_log, prices, d, cost_rate, vix_blocked,
                )
            continue

        if is_rebal:
            # Audit #16: rank only names IN the index as-of this rebalance.
            # Removals drop out of the target here and get closed by the
            # off-target logic in _apply_target; additions become eligible.
            rebal_universe = (
                sorted(set(universe_tickers) & membership.as_of(d))
                if membership is not None else universe_tickers
            )
            ranking, regime_label = _resolve_ranking(
                args.factor, prices, fund_loader, d, rebal_universe,
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
                # audit C2: don't silently skip — a skipped rebalance drifts
                # exposure and undercounts n_rebalances. Log it + record it.
                logger.warning("empty ranking at %s — rebalance skipped, holding prior book",
                               d.date())
                rebalance_log.append({"date": d.date().isoformat(),
                                      "action": "skipped_empty_ranking",
                                      "n_positions": len(holdings)})
                continue
            n_long = max(1, int(round(len(ranking) * args.top_decile)))
            ranking = _apply_hysteresis_to_ranking(args, ranking, holdings, n_long)
            standing_long, standing_short = _select_long_short_targets(
                args, ranking, prices, d, n_long, short_decile,
            )
            cash, exposure_mult = _apply_target(standing_long, standing_short, cash)
            rebalance_log.append({
                "date": d.date().isoformat(), "action": "rebalance",
                "n_positions": len(holdings),
                "n_long": sum(1 for v in holdings.values() if v > 0),
                "n_short": sum(1 for v in holdings.values() if v < 0),
                "regime": regime_label, "exposure_mult": round(exposure_mult, 4),
            })
        elif args.daily_regime and not holdings and (standing_long or standing_short):
            # RE-ENTRY: regime flipped back on between rebalances while in cash
            # -> re-buy the standing target, resized to current equity.
            cash, exposure_mult = _apply_target(standing_long, standing_short, cash)
            rebalance_log.append({
                "date": d.date().isoformat(), "action": "regime_reentry",
                "n_positions": len(holdings),
                "n_long": sum(1 for v in holdings.values() if v > 0),
                "n_short": sum(1 for v in holdings.values() if v < 0),
                "regime": "risk_on", "exposure_mult": round(exposure_mult, 4),
            })

    return _compute_metrics_and_assemble(
        args, snap, calendar, spy,
        equity_history, trades, rebalance_log, exposure_history,
    )


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
        "CAPM alpha: %+.2f%% (beta=%.2f) | excess-return vs SPY: %+.2f%% | "
        "Walk-forward: mean_sharpe=%.2f min_sharpe=%.2f passed=%s",
        result["capm_alpha_pct"], result["beta"], result["alpha_vs_spy_pct"],
        wf["mean_sharpe"], wf["min_sharpe"], wf["passed"],
    )
    logger.warning(
        "SINGLE-PHASE result (rebal-offset=%d). A 2yr/63d backtest has a "
        "+/-20-30pp phase-noise envelope — do NOT read this as an edge. Run "
        "scripts/phase_envelope.py for the phase-averaged number (see "
        "project_phase_luck_capstone).", args.rebal_offset,
    )
    print(args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
