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
from src.factors.momentum import momentum_12_1
from src.factors.quality import quality_factor
from src.factors.regime import is_risk_on, trend_state_series
from src.factors.regime_weights import list_profiles, weights_for
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
    p.add_argument("--factor",
                   default="momentum",
                   choices=("momentum", "quality", "value", "composite"),
                   help="Which factor to rank by. composite = "
                        "equal-weight rank-blend of all three.")
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


def _resolve_ranking(
    factor: str,
    prices: dict,
    fund_loader,
    as_of: pd.Timestamp,
    universe_tickers: list[str],
    *,
    regime_profile: str = "equal",
    vix_df: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, str]:
    """Dispatch to the requested factor. Returns ``(ranking, regime_label)``.

    For single-factor runs (momentum / quality / value alone) the
    regime_label is always "low_vix" because there's no blend to
    reshape. The composite path consults the regime-weights profile.
    """
    if factor == "momentum":
        return momentum_12_1(prices, as_of), "low_vix"
    if factor == "quality":
        return quality_factor(fund_loader, universe_tickers, as_of), "low_vix"
    if factor == "value":
        return value_factor(fund_loader, prices, universe_tickers, as_of), "low_vix"
    if factor == "composite":
        m = momentum_12_1(prices, as_of)
        q = quality_factor(fund_loader, universe_tickers, as_of)
        v = value_factor(fund_loader, prices, universe_tickers, as_of)
        weights, regime = weights_for(
            regime_profile, as_of=as_of, vix_df=vix_df,
        )
        # Permissive overlap: a ticker that's in 2 of 3 factors still
        # gets ranked. Strict overlap (must be in all 3) drops too
        # many names from the universe at any given as_of.
        ranking = combine_factors(
            [m, q, v], min_overlap=2, weights=weights,
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

    cost_rate = args.cost_bps / 10_000.0
    rebal_every = max(1, int(args.rebalance_days))

    # Step through every trading day.
    for i, d in enumerate(calendar):
        eq = _mark_to_market(holdings, cash, prices, d)
        equity_history.append((d.date().isoformat(), eq))

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
            vix_df=snap.vix_df if args.regime_weights != "equal" else None,
        )
        if ranking.empty:
            continue
        n_pick = max(1, int(round(len(ranking) * args.top_decile)))
        top = ranking.iloc[:n_pick]
        target_list = top["ticker"].tolist()
        # Optional post-composite low-vol filter: drop the top-vol
        # names from the picks. Computed on the full snapshot universe
        # so a factor-skewed top decile doesn't shift the vol cutoff.
        if 0 < args.low_vol_keep_pct < 1.0:
            kept = low_vol_filter(
                prices, target_list, d,
                window=args.low_vol_window,
                keep_pct=args.low_vol_keep_pct,
            )
            target_list = kept
        target_set = set(target_list)

        # Sell names not in target.
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
                "side": "sell_rebalance", "shares": int(sh),
                "price": round(px, 4), "cost": round(cost, 4),
            })

        # Equal-weight allocation across target set.
        current_eq = _mark_to_market(holdings, cash, prices, d)
        per_position = current_eq / max(1, len(target_set))

        for t in target_set:
            px = _close_on(prices, t, d)
            if px is None or px <= 0:
                continue
            target_shares = int(per_position // px)
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

        rebalance_log.append({
            "date": d.date().isoformat(),
            "action": "rebalance",
            "n_positions": len(holdings),
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
