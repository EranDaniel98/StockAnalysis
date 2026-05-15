"""
Backtest engine: walk-forward simulation that replays the live scoring engine
over historical OHLCV data. Look-ahead is prevented by slicing each ticker's
DataFrame to df.loc[:as_of_date] before passing to analyzers.

Caveat: yfinance fundamentals are point-in-time-NOW (not point-in-time-historical),
so any strategy with non-trivial fundamental weight will be optimistic. The output
flags this loudly.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from src.scoring.analyzers import technical, fundamental, patterns, statistical, alpha158
from src.scoring.fundamentals_adapter import PIT_SAFE_OVERLAY_KEYS as _PIT_SAFE_OVERLAY_KEYS
from src.scoring.analyzers import pead as pead_module
from src.scoring.analyzers import relative_strength
from src.scoring.analyzers import insider_flow
from src.scoring.analyzers import catalyst
from src.scoring.analyzers import short_interest as short_interest_module
from src.scoring.analyzers import sector_flows as sector_flows_module
from src.scoring.analyzers.sector_flows import SECTOR_TO_ETF
from src.scoring.analyzers.trend_detector import analyze_stock_trend
from src.scoring.engine import calculate_composite_score
from src.scoring.sector_stats import compute_sector_stats
from src.backtest.portfolio import SimPortfolio
from src.market_data.regime import (
    GateMode,
    RegimeParams,
    classify_at,
    gate_allows_entry,
)

logger = logging.getLogger(__name__)


# Bumps whenever a scoring-engine change makes prior backtest results
# non-comparable. Stamped onto every BacktestResult so downstream consumers
# (sweep history, dashboards, memory notes) can tell which pipeline
# version a number came from. Previous "OOS Sharpe 1.61" findings sat on
# pre-9345a74 pipelines and are not directly comparable to post-9345a74.
PIPELINE_VERSION = "2026-05-15-survivorship-haircut"


def _build_data_quality_block(
    *,
    n_tickers_traded: int,
    universe_label: str | None = None,
    adjusted_full_summary: dict | None = None,
    adjusted_oos_summary: dict | None = None,
) -> dict:
    """Structured data-quality flags that every backtest result inherits.

    Tier-1 audit #5: surfacing the survivorship-bias warning as a typed
    field (not buried in `warnings`). The follow-on (#5b in
    src/backtest/survivorship.py) computes a Bessembinder-style haircut
    and ships an adjusted summary alongside the headline so the operator
    sees a credible lower bound, not just a qualitative warning.

    When ``adjusted_full_summary`` / ``adjusted_oos_summary`` are passed,
    severity flips from ``"uncorrected"`` to ``"haircut_estimated"`` and
    the adjusted numbers embed in the block. Full PIT index membership
    (CRSP / Norgate / Sharadar) is the proper fix; the haircut is the
    quantitative bridge until that's wired.
    """
    sb: dict = {
        "applies": True,
        "severity": "uncorrected",
        "magnitude_hint_annual_pct": "1-3 (large-cap), more for small-cap or longer windows",
        "source": "current-snapshot ticker lists (e.g. russell_1000_tickers.txt)",
        "details": (
            "Universe is built from a present-day ticker snapshot, so "
            "stocks that delisted / went bankrupt / were acquired before "
            "today are excluded entirely. Headline Sharpe / CAGR are "
            "biased upward by an unknown amount."
        ),
        "remediation": (
            "Adopt point-in-time index membership (CRSP / Norgate / "
            "Sharadar) or apply Bessembinder-style synthetic delisted "
            "returns. Until then, treat all headline numbers as upper "
            "bounds."
        ),
    }
    if universe_label:
        sb["universe_label"] = universe_label
    if adjusted_full_summary is not None or adjusted_oos_summary is not None:
        sb["severity"] = "haircut_estimated"
        sb["adjusted"] = {
            "full": adjusted_full_summary,
            "out_of_sample": adjusted_oos_summary,
            "method": (
                "Flat annual-return + Sharpe haircut applied to headline "
                "metrics per universe. See src/backtest/survivorship.py for "
                "magnitudes and citations. Headline numbers are unchanged; "
                "the adjusted block is the credible lower bound."
            ),
        }
    return {
        "pipeline_version": PIPELINE_VERSION,
        "survivorship_bias": sb,
        "n_tickers_traded": int(n_tickers_traded),
    }


@dataclass
class BacktestConfig:
    start_date: pd.Timestamp
    end_date: pd.Timestamp
    rebalance_weekday: int = 0  # 0=Mon
    min_score: float = 65.0
    max_open_positions: int = 20
    max_position_pct: float = 0.10
    starting_cash: float = 10_000.0
    max_hold_days: int = 90
    atr_stop_mult: float = 2.0
    atr_target_mult: float = 6.0  # 3R if stop=2x ATR
    min_history_bars: int = 200  # need 200d for SMA200
    workers: int = 8
    compound: bool = False
    max_staleness_days: int = 10
    # Realism — Tier 2
    commission_per_trade: float = 0.0       # $ per trade (0 for $0-commission brokers)
    regulatory_bps_on_sale: float = 3.0     # SEC + FINRA fees on sale, ~3bps
    slippage_bps: float = 5.0               # bps each side (entry pays more, exit receives less)
    earnings_blackout_days: int = 3         # skip entry if earnings within ±N days
    accept_lookahead: bool = False          # bypass fundamentals-lookahead guard
    # Statistical validity — Tier 3
    oos_split_pct: float = 0.30             # last X of window held out for OOS
    bootstrap_resamples: int = 2000         # 0 disables bootstrap CIs
    # Review item #5: walk-forward CV. The legacy single-holdout split
    # (one Sharpe estimate) gives no fold variance — a strategy that
    # earned its Sharpe entirely in fold 3 looks identical to one that
    # earned it evenly. ``walk_forward_folds`` > 0 enables an N-fold
    # report on top of the legacy split. 5 folds is the review default.
    # 0 disables (legacy single-split only).
    walk_forward_folds: int = 5
    walk_forward_min_mean_sharpe: float = 0.5  # gate threshold
    # Analytics — Tier 4
    vol_target_risk_pct: float = 0.0        # 0 = fixed-fractional sizing; e.g. 0.01 = risk 1%/trade

    # Data-quality — survivorship-bias haircut (Tier-1 audit #5 follow-on).
    # When set, the result's data_quality.survivorship_bias.adjusted block
    # carries Bessembinder-style adjusted Sharpe / return numbers. None
    # means "haircut applies but no universe label was passed"; the
    # adjusted block still ships, using a conservative fallback haircut.
    universe_label: str | None = None
    apply_survivorship_haircut: bool = True
    # Review item #4: refuse a backtest whose end_date is AFTER the
    # universe-capture date when this is True (default). The universe
    # file only contains names that survived to the capture date, so
    # backtests beyond that point are structurally survivor-biased on a
    # tighter cohort than even the headline survivorship-haircut model
    # accounts for. Override per-run with --accept-survivorship if you
    # explicitly want to look at survivor-only post-capture performance.
    refuse_survivor_only_window: bool = True


class LookaheadGuardError(RuntimeError):
    """Raised when a strategy's fundamental weight would silently leak future knowledge."""


class SurvivorshipGuardError(RuntimeError):
    """Raised when the backtest window extends past the universe-capture
    date and the operator hasn't passed an explicit override.

    Review item #4. A universe captured on 2026-05-13 used for a window
    ending 2026-05-15 contains ONLY names that survived from then to now;
    every delisted/acquired name from 2024-2026 is silently absent. The
    flat survivorship haircut model can't fully correct this — it
    estimates index-level bias, not the additional bias of a 'survivor-
    only' window. Caller must opt in.
    """


def fetch_earnings_dates(tickers: list[str], workers: int = 8) -> dict[str, list[pd.Timestamp]]:
    """
    Fetch historical + upcoming earnings dates for each ticker via yfinance.
    Returns {ticker: sorted list of tz-naive Timestamps}. Empty list on failure.
    Parallelized — each yfinance call is network-bound.

    Each yfinance call is wrapped in a 30s timeout (audit Tier-1 #8 / E#6):
    yfinance has no native timeout, and a single stuck Yahoo connection
    used to wedge a worker for the duration of the backtest. The wrapper
    converts timeouts into empty earnings lists — same shape downstream
    code expects, but logged at warning level so misses are visible.
    """
    import yfinance as yf

    from src.data.fetch_outcome import call_with_timeout

    def _fetch_one(t):
        df, err = call_with_timeout(
            lambda: yf.Ticker(t).get_earnings_dates(limit=40),
            timeout_seconds=30.0,
            name=f"yf.get_earnings_dates({t})",
        )
        if err is not None:
            return t, []
        if df is None or df.empty:
            return t, []
        idx = df.index
        if isinstance(idx, pd.DatetimeIndex) and idx.tz is not None:
            idx = idx.tz_localize(None)
        return t, sorted(pd.to_datetime(idx).tolist())

    results: dict[str, list[pd.Timestamp]] = {}
    workers = max(1, min(workers, len(tickers)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(_fetch_one, t) for t in tickers]
        for fut in as_completed(futures):
            try:
                t, dates = fut.result()
                results[t] = dates
            except Exception:
                pass
    return results


def fetch_earnings_history(tickers: list[str], workers: int = 8) -> dict[str, pd.DataFrame]:
    """
    Fetch full earnings-history DataFrames (with surprise %) per ticker. Used
    by PEAD detector. Parallelized; falls back to empty DataFrame on failure.

    Same 30s yfinance timeout wrapping as ``fetch_earnings_dates`` (audit
    Tier-1 #8 / E#6).
    """
    import yfinance as yf

    from src.data.fetch_outcome import call_with_timeout

    def _fetch_one(t):
        df, err = call_with_timeout(
            lambda: yf.Ticker(t).get_earnings_dates(limit=40),
            timeout_seconds=30.0,
            name=f"yf.get_earnings_dates({t})",
        )
        if err is not None:
            return t, pd.DataFrame()
        if df is None or df.empty:
            return t, pd.DataFrame()
        if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
            df = df.copy()
            df.index = df.index.tz_localize(None)
        return t, df

    results: dict[str, pd.DataFrame] = {}
    workers = max(1, min(workers, len(tickers)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(_fetch_one, t) for t in tickers]
        for fut in as_completed(futures):
            try:
                t, df = fut.result()
                results[t] = df
            except Exception:
                pass
    return results


def _is_in_earnings_blackout(
    ticker: str,
    day: pd.Timestamp,
    earnings_dates: dict[str, list[pd.Timestamp]],
    blackout_days: int,
) -> bool:
    if blackout_days <= 0:
        return False
    dates = earnings_dates.get(ticker)
    if not dates:
        return False
    for ed in dates:
        if abs((day - ed).days) <= blackout_days:
            return True
    return False


def _atr(df: pd.DataFrame, period: int = 14) -> float:
    if len(df) < period + 1:
        return 0.0
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    val = atr.iloc[-1]
    return float(val) if pd.notna(val) else 0.0


def _score_ticker(
    ticker: str,
    df_slice: pd.DataFrame,
    fund: dict,
    config,
    strategy: dict,
    earnings_hist: Optional[pd.DataFrame] = None,
    as_of_date: Optional[pd.Timestamp] = None,
    sector_stats: Optional[dict] = None,
    benchmark_slice: Optional[pd.DataFrame] = None,
    insider_txs_slice: Optional[list] = None,
    catalyst_snapshot: Optional[object] = None,
    short_interest_history: Optional[list] = None,
    sector_etf_slice: Optional[pd.DataFrame] = None,
    sector_etf_symbol: Optional[str] = None,
) -> Optional[dict]:
    """Run all analyzers on a sliced df and return composite score result + ATR.

    ``sector_stats`` is the pre-computed per-sector quantile table from
    ``compute_sector_stats``; when present, fundamental scoring uses
    sector-relative percentiles for valuation metrics.

    ``benchmark_slice`` is the SPY (or other benchmark) history sliced
    to the same as-of date as the ticker. When provided, the relative-
    strength analyzer fires; when None, RS is skipped (composite engine
    treats it as a missing sub-score, same as alpha158 on short history).
    """
    if df_slice is None or len(df_slice) < 50:
        return None
    try:
        tech = technical.analyze(df_slice, config)
        fnd = fundamental.analyze(fund, config, sector_stats=sector_stats)
        pat = patterns.analyze(df_slice, config)
        stat = statistical.analyze(df_slice, config)
        trnd = analyze_stock_trend(df_slice, fund, config)
        # Alpha158 needs 260+ bars; gracefully degrades to None when too short
        a158 = alpha158.analyze(df_slice, config) if len(df_slice) >= 260 else None
        # PEAD if we have earnings history; otherwise None (no bonus)
        pd_result = None
        if earnings_hist is not None and not earnings_hist.empty:
            pd_result = pead_module.analyze(ticker, earnings_hist, as_of_date=as_of_date)
        rs_result = (
            relative_strength.analyze(df_slice, benchmark_slice, config)
            if benchmark_slice is not None else None
        )
        # Insider flow: pass through the per-ticker pre-sliced transaction
        # list. Slicing happens once at the per-Monday level in the caller
        # so we don't re-filter the global list N times.
        if_result = None
        if insider_txs_slice and as_of_date is not None:
            if_result = insider_flow.analyze(
                insider_txs_slice, as_of=as_of_date.date(),
            )
        # Catalyst: pure-function over a pre-selected nearest-snapshot.
        # Caller does the (ticker, cluster_end <= as_of, age <= 60d)
        # filtering once per Monday and hands us the row directly.
        cat_result = None
        if catalyst_snapshot is not None and as_of_date is not None:
            cat_result = catalyst.analyze(
                catalyst_snapshot, as_of=as_of_date.date(),
            )
        # Short interest — fires when the caller pre-sliced rows on or
        # before as_of for this ticker.
        si_result = None
        if short_interest_history and as_of_date is not None:
            si_result = short_interest_module.analyze(
                short_interest_history, as_of=as_of_date.date(),
            )
        # Sector ETF flows — caller resolves ticker.sector -> ETF symbol
        # and passes the ETF's price/volume slice. None when sector is
        # unknown or ETF history is too short.
        sf_result = None
        if sector_etf_slice is not None and as_of_date is not None and not sector_etf_slice.empty:
            sf_result = sector_flows_module.analyze(
                sector_etf_slice, as_of=as_of_date, etf_symbol=sector_etf_symbol,
            )
        score_result = calculate_composite_score(
            tech, fnd, pat, stat, trnd, strategy,
            alpha158_result=a158,
            pead_result=pd_result,
            rel_strength_result=rs_result,
            insider_flow_result=if_result,
            catalyst_result=cat_result,
            short_interest_result=si_result,
            sector_flows_result=sf_result,
        )
        score_result["_atr"] = _atr(df_slice)
        score_result["_close"] = float(df_slice["Close"].iloc[-1])
        # Per-source signal counts: needed by ScoreCache to re-derive the
        # signal-consensus ±5 adjustment when an A/B sweep drops a source.
        named_results = {
            "technical": tech, "fundamental": fnd, "pattern": pat,
            "statistical": stat, "trend": trnd,
            "alpha158": a158, "pead": pd_result,
            "rel_strength": rs_result,
            "insider_flow": if_result, "catalyst": cat_result,
            "short_interest": si_result, "sector_flows": sf_result,
        }
        bull_by_src: dict[str, int] = {}
        bear_by_src: dict[str, int] = {}
        for src, r in named_results.items():
            if r is None:
                continue
            sigs = r.get("signals", []) or []
            bull_by_src[src] = sum(1 for s in sigs if s.get("type") == "bullish")
            bear_by_src[src] = sum(1 for s in sigs if s.get("type") == "bearish")
        score_result["_bullish_by_source"] = bull_by_src
        score_result["_bearish_by_source"] = bear_by_src
        score_result["_pead_bonus"] = (
            float(pd_result.get("composite_bonus", 0.0)) if pd_result is not None else 0.0
        )
        return score_result
    except Exception as e:
        # Promoted from logger.debug: this used to be invisible in prod and
        # the ticker disappeared from scoring entirely. Now it's a warning
        # so it surfaces in the backtest log, and the caller increments a
        # skipped_score_errors counter on the result summary.
        logger.warning(
            "Score error %s @ %s: %s: %s",
            ticker, as_of_date, type(e).__name__, e,
        )
        return None


def _score_all_tickers_for_date(
    as_of: pd.Timestamp,
    price_data: dict[str, pd.DataFrame],
    fundamentals: dict[str, dict],
    config,
    strategy: dict,
    workers: int,
    min_history_bars: int,
    *,
    spy_df: Optional[pd.DataFrame] = None,
    sector_stats: Optional[dict] = None,
    earnings_history: Optional[dict[str, pd.DataFrame]] = None,
    insider_transactions: Optional[dict[str, list]] = None,
    narrative_snapshots: Optional[dict[str, list]] = None,
    fundamentals_pit_loader=None,
    short_interest_history: Optional[dict[str, list]] = None,
    sector_etfs: Optional[dict[str, pd.DataFrame]] = None,
    score_cache=None,
) -> list[tuple[str, dict]]:
    """Per-Monday parallel scoring of every ticker in ``price_data``.

    Factored out of ``run_backtest`` so the multi-mode sweep entry point
    can score each Monday once and replay the portfolio simulation per
    mode without re-running analyzers.

    When ``score_cache`` is a ``ScoreCache``, each successfully scored
    ticker is captured as a ``CachedScore`` keyed by ``(as_of, ticker)``.
    """
    earnings_history = earnings_history or {}
    insider_transactions = insider_transactions or {}
    narrative_snapshots = narrative_snapshots or {}
    short_interest_history = short_interest_history or {}
    sector_etfs = sector_etfs or {}

    spy_slice = None
    if spy_df is not None and not spy_df.empty:
        spy_slice = spy_df.loc[spy_df.index < as_of]
        if spy_slice.empty:
            spy_slice = None

    scored: list[tuple[str, dict]] = []
    skipped_score_errors = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures: dict = {}
        for ticker, df in price_data.items():
            df_slice = df.loc[df.index < as_of]
            if len(df_slice) < min_history_bars:
                continue
            raw_overlay = fundamentals.get(ticker, {}) or {}
            if fundamentals_pit_loader is not None:
                overlay = {
                    k: v for k, v in raw_overlay.items()
                    if k in _PIT_SAFE_OVERLAY_KEYS
                }
                last_close = (
                    float(df_slice["Close"].iloc[-1]) if not df_slice.empty else None
                )
                fund = fundamentals_pit_loader.lookup_dict(
                    ticker, as_of, price=last_close, overlay=overlay,
                )
            else:
                fund = raw_overlay
            eh = earnings_history.get(ticker)
            all_ins = insider_transactions.get(ticker, []) or []
            ins_slice = [
                tx for tx in all_ins if tx.filing_date <= as_of.date()
            ] if all_ins else None
            all_nars = narrative_snapshots.get(ticker, []) or []
            nar_snap = None
            if all_nars:
                valid = [
                    n for n in all_nars if n.cluster_end_date <= as_of.date()
                ]
                if valid:
                    nar_snap = max(valid, key=lambda n: n.cluster_end_date)
            all_si = short_interest_history.get(ticker, []) or []
            si_slice = [
                row for row in all_si if row.settlement_date <= as_of.date()
            ] if all_si else None
            sector_etf_slice = None
            sector_etf_symbol = None
            sec = (fund.get("sector") or "").strip()
            if sec and sec in SECTOR_TO_ETF:
                sector_etf_symbol = SECTOR_TO_ETF[sec]
                etf_df = sector_etfs.get(sector_etf_symbol)
                if etf_df is not None and not etf_df.empty:
                    sector_etf_slice = etf_df.loc[etf_df.index < as_of]
                    if sector_etf_slice.empty:
                        sector_etf_slice = None
            futures[ex.submit(
                _score_ticker, ticker, df_slice, fund, config, strategy,
                eh, as_of, sector_stats, spy_slice, ins_slice, nar_snap,
                si_slice, sector_etf_slice, sector_etf_symbol,
            )] = ticker
        for fut in as_completed(futures):
            ticker = futures[fut]
            try:
                result = fut.result()
            except Exception as e:
                # Promoted from logger.debug. Pickling errors / fundamentals
                # loader transient drops used to disappear silently from the
                # scored set; now they're warnings and counted.
                logger.warning(
                    "Worker error %s @ %s: %s: %s",
                    ticker, as_of, type(e).__name__, e,
                )
                result = None
            if result is None:
                skipped_score_errors += 1
                continue
            scored.append((ticker, result))
            if score_cache is not None:
                from src.backtest.score_cache import CachedScore
                score_cache.put(as_of, ticker, CachedScore(
                    sub_scores=dict(result.get("sub_scores", {})),
                    bullish_by_source=dict(result.get("_bullish_by_source", {})),
                    bearish_by_source=dict(result.get("_bearish_by_source", {})),
                    pead_bonus=float(result.get("_pead_bonus", 0.0)),
                    atr=float(result.get("_atr", 0.0)),
                    close=float(result.get("_close", 0.0)),
                ))
    if skipped_score_errors > 0:
        logger.warning(
            "Score-error skips on %s: %d tickers dropped (worker exception or "
            "_score_ticker returned None).",
            as_of, skipped_score_errors,
        )
    return scored


def _next_trading_day_inclusive(df: pd.DataFrame, on_or_after: pd.Timestamp) -> Optional[pd.Timestamp]:
    """Return the first bar index >= on_or_after, or None."""
    mask = df.index >= on_or_after
    if not mask.any():
        return None
    return df.index[mask][0]


def _normalize_index(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure DataFrame index is tz-naive datetime so comparisons are consistent."""
    if not isinstance(df.index, pd.DatetimeIndex):
        df = df.copy()
        df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df = df.copy()
        df.index = df.index.tz_localize(None)
    return df


def _spy_buy_hold_return(spy_df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> Optional[float]:
    if spy_df is None or spy_df.empty:
        return None
    spy = _normalize_index(spy_df)
    in_range = spy.loc[(spy.index >= start) & (spy.index <= end)]
    if len(in_range) < 2:
        return None
    return (in_range["Close"].iloc[-1] / in_range["Close"].iloc[0] - 1) * 100


def run_backtest(
    price_data: dict[str, pd.DataFrame],
    fundamentals: dict[str, dict],
    config,
    strategy: dict,
    bt_cfg: BacktestConfig,
    spy_df: Optional[pd.DataFrame] = None,
    vix_df: Optional[pd.DataFrame] = None,
    earnings_dates: Optional[dict[str, list[pd.Timestamp]]] = None,
    earnings_history: Optional[dict[str, pd.DataFrame]] = None,
    insider_transactions: Optional[dict[str, list]] = None,
    narrative_snapshots: Optional[dict[str, list]] = None,
    fundamentals_pit_loader=None,  # FundamentalsPITLoader | None
    short_interest_history: Optional[dict[str, list]] = None,
    sector_etfs: Optional[dict[str, pd.DataFrame]] = None,
) -> dict:
    """
    Walk-forward backtest. Returns dict with:
      summary, calibration, trades, exit_reasons, equity_curve, warnings
    """
    # Review item #4: refuse a window that extends past the universe's
    # capture date. The ticker list is a survivor-only snapshot — windows
    # beyond that point are biased on a *tighter* cohort than even the
    # haircut model accounts for. Run this FIRST so we fail before any
    # expensive setup (sector stats, regime classification, schedule build)
    # and before reading any other config field. Operator opts out by
    # setting refuse_survivor_only_window=False explicitly.
    if bt_cfg.refuse_survivor_only_window and bt_cfg.universe_label:
        end_for_guard = pd.Timestamp(bt_cfg.end_date)
        if end_for_guard.tz is not None:
            end_for_guard = end_for_guard.tz_localize(None)
        try:
            captured = (
                config.get_universe_captured_date(bt_cfg.universe_label)
                if hasattr(config, "get_universe_captured_date") else None
            )
        except ValueError as exc:
            raise SurvivorshipGuardError(
                f"Universe {bt_cfg.universe_label!r} has no captured-date "
                f"header. {exc} Set refuse_survivor_only_window=False to "
                f"override, but understand that you are then trading on "
                f"unbounded survivorship bias."
            ) from exc
        if captured is not None and end_for_guard.date() > captured:
            raise SurvivorshipGuardError(
                f"Backtest end_date {end_for_guard.date().isoformat()} is "
                f"AFTER universe {bt_cfg.universe_label!r} capture date "
                f"{captured.isoformat()}. Every name in the universe "
                f"survived from then to now — the window is structurally "
                f"survivor-biased on a tighter cohort than the haircut "
                f"model corrects for. Either trim end_date to "
                f"{captured.isoformat()}, refresh the universe file, or "
                f"set refuse_survivor_only_window=False to override."
            )

    warnings: list[str] = []
    earnings_dates = earnings_dates or {}
    earnings_history = earnings_history or {}
    insider_transactions = insider_transactions or {}
    narrative_snapshots = narrative_snapshots or {}
    short_interest_history = short_interest_history or {}
    sector_etfs = sector_etfs or {}
    if sector_etfs:
        sector_etfs = {k: _normalize_index(v) for k, v in sector_etfs.items() if v is not None and not v.empty}
    skipped_earnings = 0
    skipped_regime = 0
    regime_history: list[dict] = []  # per-Monday {date, label, vix, spy_above_sma}

    # Sector-relative scoring: pre-compute per-sector quantiles once for
    # the run. yfinance fundamentals are current-snapshot, so the stats
    # are inherently snapshot-based — same lookahead caveat as the rest
    # of the fundamental path (flagged loudly below).
    sector_cfg = config.get_sector_relative_scoring() if hasattr(config, "get_sector_relative_scoring") else {}
    sector_stats: Optional[dict] = None
    if sector_cfg.get("enabled", False):
        sector_stats = compute_sector_stats(
            fundamentals,
            min_cohort=int(sector_cfg.get("min_cohort", 5)),
        )

    # Regime entry gate. Reads config; defaults to "off". SPY + VIX frames
    # must be supplied for the gate to fire — otherwise label is 'unknown'
    # and the gate allows entry (don't punish data outages).
    rf_cfg = config.get_regime_filter() if hasattr(config, "get_regime_filter") else {}
    regime_enabled: bool = bool(rf_cfg.get("enabled", False))
    regime_mode: GateMode = rf_cfg.get("mode", "off") if regime_enabled else "off"
    regime_params = RegimeParams(
        sma_period=int(rf_cfg.get("sma_period", 200)),
        vix_low=float(rf_cfg.get("vix_low", 20.0)),
        vix_high=float(rf_cfg.get("vix_high", 25.0)),
    )

    # Normalize all indices once
    price_data = {t: _normalize_index(df) for t, df in price_data.items() if df is not None and not df.empty}
    if not price_data:
        return {"error": "No price data available"}
    # Benchmark frames come from a different fetcher path and can land
    # tz-aware (America/New_York from yfinance) — normalize them so
    # subsequent index comparisons against tz-naive Timestamps don't
    # blow up downstream.
    if spy_df is not None and not spy_df.empty:
        spy_df = _normalize_index(spy_df)
    if vix_df is not None and not vix_df.empty:
        vix_df = _normalize_index(vix_df)

    # Normalize start/end to tz-naive Timestamps for safe comparisons against indices
    start = pd.Timestamp(bt_cfg.start_date)
    if start.tz is not None:
        start = start.tz_localize(None)
    end = pd.Timestamp(bt_cfg.end_date)
    if end.tz is not None:
        end = end.tz_localize(None)

    # Build the schedule: every Monday between start and end
    schedule = pd.date_range(start=start, end=end, freq="W-MON").tolist()
    if not schedule:
        return {"error": "Empty schedule — check start/end dates"}

    portfolio = SimPortfolio(
        starting_cash=bt_cfg.starting_cash,
        max_position_pct=bt_cfg.max_position_pct,
        max_open_positions=bt_cfg.max_open_positions,
        compound=bt_cfg.compound,
        commission_per_trade=bt_cfg.commission_per_trade,
        regulatory_bps_on_sale=bt_cfg.regulatory_bps_on_sale,
        slippage_bps=bt_cfg.slippage_bps,
        vol_target_risk_pct=bt_cfg.vol_target_risk_pct,
    )

    equity_curve: list[dict] = []

    fundamental_weight = strategy.get("weights", {}).get("fundamental", 0)
    if fundamental_weight > 0.05:
        # PIT loader presence determines whether this is a real look-ahead risk.
        # Coverage threshold: if the loader has rows for ≥50% of the price-data
        # universe, we treat fundamentals as PIT-safe and skip the guard.
        pit_coverage = 0.0
        if fundamentals_pit_loader is not None and price_data:
            covered = sum(1 for t in price_data if t.upper() in fundamentals_pit_loader.tickers)
            pit_coverage = covered / max(1, len(price_data))
        if fundamentals_pit_loader is not None and pit_coverage >= 0.5:
            warnings.append(
                f"PIT fundamentals active: loader covers {pit_coverage*100:.0f}% of universe. "
                f"Fundamental weight {fundamental_weight*100:.0f}% scored against EDGAR PIT rows."
            )
        else:
            msg = (
                f"Strategy weights fundamentals at {fundamental_weight*100:.0f}%. "
                f"yfinance exposes only current fundamentals (not point-in-time historical), "
                f"so the score function reads 2026 financials at every historical Monday — "
                f"a hard look-ahead leak that produces fictitious alpha."
            )
            if fundamentals_pit_loader is not None:
                msg += (
                    f" PIT loader supplied but coverage is only {pit_coverage*100:.0f}% — "
                    f"insufficient to override the guard (need ≥50%)."
                )
            if not bt_cfg.accept_lookahead:
                raise LookaheadGuardError(
                    msg + " Re-run with --accept-lookahead to override (results will be invalid)."
                )
            warnings.append(
                "LOOKAHEAD ACCEPTED: " + msg + " Output is for exploration only; do not "
                "trust headline numbers."
            )

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold]Backtest[/bold]"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("{task.fields[when]}"),
        transient=True,
    ) as progress:
        task = progress.add_task("walking", total=len(schedule), when="")

        for as_of in schedule:
            progress.update(task, when=as_of.strftime("%Y-%m-%d"))

            # 1) Process exits for any positions whose stop/target/timeout fires
            #    between the previous as_of and this one. We walk DAILY through
            #    each position's price data.
            _process_exits_through(portfolio, price_data, as_of, bt_cfg.max_staleness_days)

            # 1.5) Classify the broader-market regime using only data strictly
            #      before `as_of`. The classifier degrades to label='unknown'
            #      on missing inputs; the gate allows entry on 'unknown' so
            #      data gaps don't silently flatten the book.
            regime_snap = classify_at(spy_df, vix_df, as_of, regime_params)
            regime_history.append({
                "date": as_of.strftime("%Y-%m-%d"),
                "label": regime_snap.label,
                "vix": regime_snap.vix_level,
                "spy_above_sma": regime_snap.spy_above_sma,
            })
            entries_allowed = gate_allows_entry(regime_snap.label, regime_mode)

            # 2) For each ticker, slice df strictly BEFORE as_of (pre-open scan
            #    semantic — matches live `paper trade` running Sunday with Friday
            #    data) and score in parallel.
            scored = _score_all_tickers_for_date(
                as_of, price_data, fundamentals, config, strategy,
                workers=bt_cfg.workers,
                min_history_bars=bt_cfg.min_history_bars,
                spy_df=spy_df,
                sector_stats=sector_stats,
                earnings_history=earnings_history,
                insider_transactions=insider_transactions,
                narrative_snapshots=narrative_snapshots,
                fundamentals_pit_loader=fundamentals_pit_loader,
                short_interest_history=short_interest_history,
                sector_etfs=sector_etfs,
            )

            # 3) Rank by (composite_score desc, ticker asc). Deterministic
            #    tie-break ensures reproducible results across runs.
            scored.sort(key=lambda x: (-x[1]["composite_score"], x[0]))
            if not entries_allowed:
                # Regime gate blocks new entries this Monday. Count the
                # candidates we would have opened so the report can show the
                # cost of the gate. Open positions are managed normally.
                skipped_regime += sum(
                    1 for _, r in scored
                    if not pd.isna(r["composite_score"])
                    and r["composite_score"] >= bt_cfg.min_score
                )
                scored = []
            for ticker, result in scored:
                composite = result["composite_score"]
                if pd.isna(composite):
                    continue
                # Refuse to act on a structurally-broken score even if its
                # placeholder composite happens to cross min_score (reviewer
                # B1). Engine returns score_valid=False when all required
                # analyzers errored; the 50.0 fallback + PEAD/consensus can
                # otherwise lift composite past the threshold.
                if not result.get("score_valid", True):
                    continue
                if composite < bt_cfg.min_score:
                    break  # sorted: rest are worse
                if not portfolio.can_open(ticker):
                    continue
                df = price_data[ticker]
                # Enter at the first bar on or after as_of (Monday's open if a
                # trading day, otherwise Tuesday's open).
                next_day = _next_trading_day_inclusive(df, as_of)
                if next_day is None:
                    continue
                # Skip if earnings within blackout window — ATR stops are useless
                # against earnings-day gaps.
                if _is_in_earnings_blackout(ticker, next_day, earnings_dates, bt_cfg.earnings_blackout_days):
                    skipped_earnings += 1
                    continue
                next_bar = df.loc[next_day]
                entry_price = float(next_bar["Open"])
                if entry_price <= 0:
                    continue
                atr = result.get("_atr", 0)
                if atr <= 0:
                    continue
                stop_price = entry_price - atr * bt_cfg.atr_stop_mult
                target_price = entry_price + atr * bt_cfg.atr_target_mult
                max_exit_date = next_day + pd.Timedelta(days=bt_cfg.max_hold_days)
                fund = fundamentals.get(ticker, {}) or {}
                portfolio.open_position(
                    ticker=ticker,
                    entry_price=entry_price,
                    entry_date=next_day,
                    stop_price=stop_price,
                    target_price=target_price,
                    max_exit_date=max_exit_date,
                    score=composite,
                    sector=fund.get("sector", "Unknown"),
                )

            # 4) Mark-to-market with staleness cap and record equity
            mtm = {
                t: _close_at_or_before(price_data[t], as_of, bt_cfg.max_staleness_days)
                for t in portfolio.positions
            }
            equity_curve.append({
                "date": as_of.strftime("%Y-%m-%d"),
                "equity": round(portfolio.equity({k: v for k, v in mtm.items() if v is not None}), 2),
                "open_positions": len(portfolio.positions),
                "cash": round(portfolio.cash, 2),
            })
            progress.advance(task)

    # 5) Close out any still-open positions at end_date with staleness cap
    _process_exits_through(portfolio, price_data, end, bt_cfg.max_staleness_days)
    portfolio.force_close_all(
        last_day=end,
        price_lookup=lambda t, d: _close_at_or_before(
            price_data.get(t), d, bt_cfg.max_staleness_days
        ),
    )

    return _finalize_result(
        portfolio=portfolio,
        equity_curve=equity_curve,
        regime_history=regime_history,
        warnings=warnings,
        start=start, end=end,
        bt_cfg=bt_cfg,
        spy_df=spy_df, vix_df=vix_df,
        sector_stats=sector_stats, sector_cfg=sector_cfg,
        regime_enabled=regime_enabled,
        regime_mode=regime_mode,
        regime_params=regime_params,
        skipped_earnings=skipped_earnings,
        skipped_regime=skipped_regime,
    )


def _finalize_result(
    portfolio: SimPortfolio,
    equity_curve: list[dict],
    regime_history: list[dict],
    warnings: list[str],
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    bt_cfg: BacktestConfig,
    spy_df: Optional[pd.DataFrame],
    vix_df: Optional[pd.DataFrame],
    sector_stats: Optional[dict],
    sector_cfg: dict,
    regime_enabled: bool,
    regime_mode: GateMode,
    regime_params: RegimeParams,
    skipped_earnings: int,
    skipped_regime: int,
) -> dict:
    """Build the BacktestResult dict from a completed SimPortfolio + equity curve.

    Pulled out of ``run_backtest`` so the multi-mode sweep can finalize each
    mode independently from the shared walk."""
    from src.backtest.metrics import (
        bootstrap_cis,
        calibration_table,
        cost_sensitivity_grid,
        deployment_matched_spy_return,
        equity_curve_stats,
        excursion_stats,
        exit_reason_breakdown,
        monte_carlo_shuffle,
        monthly_return_grid,
        recommend_live_threshold,
        regime_split,
        summary_stats,
        verdict,
        verdict_with_stats,
    )
    vix_normalized = _normalize_index(vix_df) if vix_df is not None and not vix_df.empty else None
    spy_normalized = _normalize_index(spy_df) if spy_df is not None and not spy_df.empty else None
    spy_ret = _spy_buy_hold_return(spy_df, start, end)
    spy_match_ret = deployment_matched_spy_return(equity_curve, spy_df, start, end)
    exits = exit_reason_breakdown(portfolio.closed_trades)

    # Tier-1 audit #5 (Q#3 / Q-cross): every result currently inherits this
    # bias because universe membership is sourced from a present-day snapshot.
    # The string warning is preserved for back-compat (any CLI/script that
    # iterates `result["warnings"]` keeps showing it), but the structured
    # `data_quality.survivorship_bias` block below is the one dashboards and
    # sweep history should render so this can't be visually ignored.
    warnings.append(
        "Survivorship bias: universe is built from current-snapshot ticker lists. "
        "Stocks that delisted, went bankrupt, or were acquired before today are "
        "excluded entirely — results are biased upward by an unknown amount "
        "(typically 1-3%/yr for large-cap windows, more for small-cap or longer windows)."
    )
    if skipped_earnings > 0:
        warnings.append(
            f"Skipped {skipped_earnings} potential entries due to earnings within "
            f"±{bt_cfg.earnings_blackout_days} days."
        )
    if regime_enabled and skipped_regime > 0:
        warnings.append(
            f"Regime gate ({regime_mode}) blocked {skipped_regime} potential entries "
            f"across {sum(1 for r in regime_history if not gate_allows_entry(r['label'], regime_mode))} Mondays."
        )
    if regime_enabled and (spy_df is None or vix_df is None):
        warnings.append(
            "Regime gate is enabled but SPY/VIX data was not supplied — gate is "
            "effectively off (label='unknown' → entry allowed). Pass spy_df + vix_df "
            "to run_backtest() to activate the gate."
        )

    split_date = start + (end - start) * (1 - bt_cfg.oos_split_pct)
    is_trades = [t for t in portfolio.closed_trades if t.entry_date < split_date]
    oos_trades = [t for t in portfolio.closed_trades if t.entry_date >= split_date]
    is_equity = [e for e in equity_curve if pd.Timestamp(e["date"]) < split_date]
    oos_equity = [e for e in equity_curve if pd.Timestamp(e["date"]) >= split_date]

    def _compute_section(trades, equity_subset, section_start, section_end,
                         starting_capital, ending_equity):
        # Pass bt_cfg.compound through so summary_stats / equity_curve_stats
        # choose the right annualization formula. Tier-2 audit #18.
        return {
            "summary": summary_stats(
                trades,
                starting_cash=starting_capital,
                ending_equity=ending_equity,
                start_date=section_start,
                end_date=section_end,
                spy_return_pct=_spy_buy_hold_return(spy_df, section_start, section_end),
                spy_deployment_matched_pct=deployment_matched_spy_return(
                    equity_subset, spy_df, section_start, section_end
                ),
                total_costs=None,
                compound=bt_cfg.compound,
            ),
            "equity_stats": equity_curve_stats(equity_subset, compound=bt_cfg.compound),
            "calibration": calibration_table(trades),
        }

    is_ending_equity = is_equity[-1]["equity"] if is_equity else bt_cfg.starting_cash
    full_section = _compute_section(
        portfolio.closed_trades, equity_curve, start, end,
        bt_cfg.starting_cash, portfolio.cash,
    )
    full_section["summary"].update({
        "spy_return_pct": round(spy_ret, 2) if spy_ret is not None else None,
        "alpha_vs_spy_pct": round(full_section["summary"]["total_return_pct"] - spy_ret, 2) if spy_ret is not None else None,
        "spy_deployment_matched_pct": round(spy_match_ret, 2) if spy_match_ret is not None else None,
        "alpha_vs_spy_matched_pct": round(full_section["summary"]["total_return_pct"] - spy_match_ret, 2) if spy_match_ret is not None else None,
        "total_costs_paid": round(
            portfolio.total_commissions + portfolio.total_slippage_cost + portfolio.total_regulatory_fees, 2
        ),
        "commissions_paid": round(portfolio.total_commissions, 2),
        "slippage_cost": round(portfolio.total_slippage_cost, 2),
        "regulatory_fees": round(portfolio.total_regulatory_fees, 2),
    })
    is_section = _compute_section(
        is_trades, is_equity, start, split_date,
        bt_cfg.starting_cash, is_ending_equity,
    )
    oos_section = _compute_section(
        oos_trades, oos_equity, split_date, end,
        is_ending_equity, portfolio.cash,
    )

    oos_verdict = verdict_with_stats(oos_section["calibration"])

    sensitivity = cost_sensitivity_grid(
        portfolio.closed_trades,
        starting_cash=bt_cfg.starting_cash,
        fixed_commission=bt_cfg.commission_per_trade,
        fixed_reg_bps=bt_cfg.regulatory_bps_on_sale,
    )

    boot_target = oos_trades if len(oos_trades) >= 20 else portfolio.closed_trades
    boot_label = "OOS" if len(oos_trades) >= 20 else "full window"
    # Pair the trade-target with its matching equity slice so the Sharpe CI
    # the bootstrap computes is on the same window as the trades that
    # populated it. Without this the headline Sharpe and the CI sit on
    # different denominators.
    boot_equity = oos_equity if len(oos_trades) >= 20 else equity_curve
    bootstrap = bootstrap_cis(
        boot_target,
        starting_cash=bt_cfg.starting_cash,
        n_resamples=bt_cfg.bootstrap_resamples,
        equity_curve=boot_equity,
    ) if bt_cfg.bootstrap_resamples > 0 else None

    excursion = excursion_stats(portfolio.closed_trades)
    regimes = regime_split(portfolio.closed_trades, spy_normalized, vix_normalized)
    monthly = monthly_return_grid(equity_curve)

    mc_shuffle = monte_carlo_shuffle(
        portfolio.closed_trades, bt_cfg.starting_cash, n_shuffles=1000
    ) if len(portfolio.closed_trades) >= 5 else None
    live_rec = recommend_live_threshold(oos_section["calibration"])

    # Walk-forward CV report (review item #5). Built post-hoc on the
    # closed-trade timeline + equity curve; the strategy was applied
    # once over the full window — no per-fold retraining (the engine
    # doesn't train a model, it applies rules). Per-fold Sharpe + a
    # strict pass/fail gate let operators read one boolean instead of
    # eyeballing fold variance.
    from src.backtest.walk_forward import compute_walk_forward_report

    walk_forward = None
    if bt_cfg.walk_forward_folds and bt_cfg.walk_forward_folds >= 2:
        walk_forward = compute_walk_forward_report(
            portfolio.closed_trades,
            equity_curve,
            start, end,
            n_folds=bt_cfg.walk_forward_folds,
            min_mean_sharpe=bt_cfg.walk_forward_min_mean_sharpe,
        )

    # Top-N concentration sensitivity. Strip the top 5 winners from the
    # OOS trade set, reconstruct the equity curve, recompute Sharpe.
    # The gate in produce_mvtp_report.py fails the MVTP run if the
    # Sharpe drop > 0.4 — i.e. the edge is concentrated in a handful
    # of lucky names. Computed on OOS trades preferentially; falls back
    # to the full window when OOS has too few.
    from src.backtest.sensitivity import top_n_removed_sensitivity

    sens_trades = oos_trades if len(oos_trades) >= 10 else portfolio.closed_trades
    sens_equity = oos_equity if len(oos_trades) >= 10 else equity_curve
    sens_label = "OOS" if len(oos_trades) >= 10 else "full window"
    sensitivity = top_n_removed_sensitivity(
        sens_trades, sens_equity, bt_cfg.starting_cash, n=5,
    )
    sensitivity["window_label"] = sens_label

    return {
        "full": full_section,
        "in_sample": is_section,
        "out_of_sample": oos_section,
        "split_date": split_date.strftime("%Y-%m-%d"),
        "verdict_oos": oos_verdict,
        "verdict_legacy": verdict(full_section["calibration"]),
        "trades": [t.to_dict() for t in portfolio.closed_trades],
        "exit_reasons": exits,
        "equity_curve": equity_curve,
        "cost_sensitivity": sensitivity,
        "bootstrap": bootstrap,
        "bootstrap_label": boot_label,
        "excursion": excursion,
        "regimes": regimes,
        "monthly_returns": monthly,
        "monte_carlo": mc_shuffle,
        "walk_forward": walk_forward,
        "concentration_sensitivity": sensitivity,
        "live_recommendation": live_rec,
        "sector_relative_scoring": {
            "enabled": sector_stats is not None,
            "min_cohort": int(sector_cfg.get("min_cohort", 5)) if sector_cfg else 5,
            "sectors_with_stats": sorted(sector_stats.keys()) if sector_stats else [],
        },
        "regime_gate": {
            "enabled": regime_enabled,
            "mode": regime_mode,
            "params": {
                "sma_period": regime_params.sma_period,
                "vix_low": regime_params.vix_low,
                "vix_high": regime_params.vix_high,
            },
            "entries_blocked": skipped_regime,
            "mondays_blocked": sum(
                1 for r in regime_history
                if not gate_allows_entry(r["label"], regime_mode)
            ) if regime_enabled else 0,
            "history": regime_history,
        },
        "data_quality": _build_data_quality_block(
            n_tickers_traded=len({t.ticker for t in portfolio.closed_trades}),
            universe_label=bt_cfg.universe_label,
            adjusted_full_summary=_build_adjusted_summary(
                full_section, start, end, bt_cfg,
            ) if bt_cfg.apply_survivorship_haircut else None,
            adjusted_oos_summary=_build_adjusted_summary(
                oos_section, split_date, end, bt_cfg,
            ) if bt_cfg.apply_survivorship_haircut else None,
        ),
        "warnings": warnings,
    }


def _build_adjusted_summary(
    section: dict,
    section_start: pd.Timestamp,
    section_end: pd.Timestamp,
    bt_cfg: "BacktestConfig",
) -> dict:
    """Apply the survivorship haircut to one section's headline metrics.

    Pure helper — does not mutate the input section. The returned dict
    embeds into ``data_quality.survivorship_bias.adjusted.{full,oos}``.
    """
    from src.backtest.survivorship import (
        adjusted_summary_block,
        default_haircut_for_universe,
    )

    haircut = default_haircut_for_universe(bt_cfg.universe_label)
    summary = section.get("summary", {}) or {}
    equity_stats = section.get("equity_stats", {}) or {}
    years = max(0.0, (section_end - section_start).days / 365.25)
    return adjusted_summary_block(
        total_return_pct=summary.get("total_return_pct"),
        cagr_pct=summary.get("cagr_pct"),
        ann_sharpe=equity_stats.get("ann_sharpe"),
        years=years,
        haircut=haircut,
    )


def _close_at_or_before(
    df: Optional[pd.DataFrame],
    day: pd.Timestamp,
    max_staleness_days: Optional[int] = None,
) -> Optional[float]:
    """
    Last close at or before `day`. If max_staleness_days is set and the latest
    bar is more than that many days before `day`, return None — the price is
    stale (delisted/halted) and shouldn't be used as fair value.
    """
    if df is None or df.empty:
        return None
    sub = df.loc[df.index <= day]
    if sub.empty:
        return None
    last_date = sub.index[-1]
    if max_staleness_days is not None and (day - last_date).days > max_staleness_days:
        return None
    return float(sub["Close"].iloc[-1])


def _process_exits_through(
    portfolio: SimPortfolio,
    price_data: dict[str, pd.DataFrame],
    through: pd.Timestamp,
    max_staleness_days: int = 10,
) -> None:
    """
    For each open position, walk daily bars from entry+1 to `through` looking for exits.
    If the ticker stops trading mid-hold (last bar more than max_staleness_days
    before `through`), force-close at the last known price with reason
    'delisted_or_halted' — prevents fictitious end-of-backtest valuations.
    """
    for ticker in list(portfolio.positions.keys()):
        pos = portfolio.positions[ticker]
        df = price_data.get(ticker)
        if df is None or df.empty:
            portfolio._close(ticker, pos.entry_date, pos.entry_price, "no_data")
            continue
        bars = df.loc[(df.index > pos.entry_date) & (df.index <= through)]
        closed_via_exit = False
        for day, bar in bars.iterrows():
            closed = portfolio.evaluate_day(ticker, day, bar)
            if closed is not None:
                closed_via_exit = True
                break
        if closed_via_exit:
            continue
        # Position survived the walk. Check if the ticker has stopped trading.
        last_bar_date = bars.index.max() if not bars.empty else pos.entry_date
        if (through - last_bar_date).days > max_staleness_days:
            last_close = float(bars["Close"].iloc[-1]) if not bars.empty else pos.entry_price
            portfolio._close(ticker, last_bar_date, last_close, "delisted_or_halted")


# ─── Multi-mode sweep entry point ───────────────────────────────────────────


@dataclass
class SweepMode:
    """One variant in a multi-mode A/B sweep.

    The analyzer chain is shared across modes (it only depends on price/
    fundamental/insider data, not on weights), so the multi-mode runner
    scores each Monday once and re-derives the composite per mode by
    re-weighting the cached sub-scores.

    Args:
        label: human name surfaced in the result dict and progress output.
        strategy: the strategy config for THIS mode — its ``weights`` and
            ``use_consensus_scaling`` flag drive the composite. Other
            keys (description, time_horizon, etc.) are passed through.
        enabled_sources: which sub-score sources contribute to the
            composite and the signal-consensus adjustment. ``None`` =
            every source we have in the cache. Use this to drop a
            source entirely (e.g. ``{"technical", ..., "alpha158"}``
            without ``"insider_flow"`` to reproduce the prior
            ``insider_transactions=None`` baseline).
    """
    label: str
    strategy: dict
    enabled_sources: Optional[set[str]] = None


def run_backtest_multi_mode(
    modes: list[SweepMode],
    price_data: dict[str, pd.DataFrame],
    fundamentals: dict[str, dict],
    config,
    bt_cfg: BacktestConfig,
    spy_df: Optional[pd.DataFrame] = None,
    vix_df: Optional[pd.DataFrame] = None,
    earnings_dates: Optional[dict[str, list[pd.Timestamp]]] = None,
    earnings_history: Optional[dict[str, pd.DataFrame]] = None,
    insider_transactions: Optional[dict[str, list]] = None,
    narrative_snapshots: Optional[dict[str, list]] = None,
    fundamentals_pit_loader=None,
    short_interest_history: Optional[dict[str, list]] = None,
    sector_etfs: Optional[dict[str, pd.DataFrame]] = None,
    progress_label: str = "Multi-mode backtest",
) -> dict[str, dict]:
    """Score each Monday once, replay the portfolio simulation per mode.

    Drop-in replacement for the ``for mode in MODES: run_backtest(...)``
    pattern in sweep scripts. Returns ``{label: BacktestResult}`` — each
    value matches the dict shape of ``run_backtest``.

    The first mode's strategy is used to drive the analyzer chain (the
    analyzers themselves are weight-independent; only sub_score
    aggregation differs). Sub-scores, signal counts, PEAD bonus, and
    ATR/close are cached per ``(as_of, ticker)`` and replayed via
    ``recompose_composite`` for each mode's weights + enabled_sources.

    Pre-flight inputs (insider_transactions, narrative_snapshots, etc.)
    must be the *union* of what any mode needs — modes that want to
    exclude a source set ``enabled_sources`` accordingly. Pass
    ``insider_transactions=full_dict`` and let mode=off drop
    ``"insider_flow"`` from ``enabled_sources`` rather than passing
    ``None`` for the off mode.
    """
    from src.backtest.score_cache import ScoreCache, recompose_composite

    if not modes:
        raise ValueError("modes must be non-empty")
    if len({m.label for m in modes}) != len(modes):
        raise ValueError("mode labels must be unique")

    shared_warnings: list[str] = []
    earnings_dates = earnings_dates or {}
    earnings_history = earnings_history or {}
    insider_transactions = insider_transactions or {}
    narrative_snapshots = narrative_snapshots or {}
    short_interest_history = short_interest_history or {}
    sector_etfs = sector_etfs or {}
    if sector_etfs:
        sector_etfs = {k: _normalize_index(v) for k, v in sector_etfs.items() if v is not None and not v.empty}

    # Shared regime classification — same SPY/VIX inputs across modes,
    # same gate config, so each Monday's regime label / entries_allowed
    # is mode-invariant.
    sector_cfg = config.get_sector_relative_scoring() if hasattr(config, "get_sector_relative_scoring") else {}
    sector_stats: Optional[dict] = None
    if sector_cfg.get("enabled", False):
        sector_stats = compute_sector_stats(
            fundamentals,
            min_cohort=int(sector_cfg.get("min_cohort", 5)),
        )

    rf_cfg = config.get_regime_filter() if hasattr(config, "get_regime_filter") else {}
    regime_enabled: bool = bool(rf_cfg.get("enabled", False))
    regime_mode: GateMode = rf_cfg.get("mode", "off") if regime_enabled else "off"
    regime_params = RegimeParams(
        sma_period=int(rf_cfg.get("sma_period", 200)),
        vix_low=float(rf_cfg.get("vix_low", 20.0)),
        vix_high=float(rf_cfg.get("vix_high", 25.0)),
    )

    price_data = {t: _normalize_index(df) for t, df in price_data.items() if df is not None and not df.empty}
    if not price_data:
        return {m.label: {"error": "No price data available"} for m in modes}
    if spy_df is not None and not spy_df.empty:
        spy_df = _normalize_index(spy_df)
    if vix_df is not None and not vix_df.empty:
        vix_df = _normalize_index(vix_df)

    start = pd.Timestamp(bt_cfg.start_date)
    if start.tz is not None:
        start = start.tz_localize(None)
    end = pd.Timestamp(bt_cfg.end_date)
    if end.tz is not None:
        end = end.tz_localize(None)

    schedule = pd.date_range(start=start, end=end, freq="W-MON").tolist()
    if not schedule:
        return {m.label: {"error": "Empty schedule"} for m in modes}

    # Lookahead check: run per-mode (different fundamental weights → different
    # PIT requirements). LookaheadGuardError from any mode is a hard fail.
    for m in modes:
        fundamental_weight = m.strategy.get("weights", {}).get("fundamental", 0)
        if fundamental_weight > 0.05:
            pit_coverage = 0.0
            if fundamentals_pit_loader is not None and price_data:
                covered = sum(1 for t in price_data if t.upper() in fundamentals_pit_loader.tickers)
                pit_coverage = covered / max(1, len(price_data))
            if fundamentals_pit_loader is not None and pit_coverage >= 0.5:
                shared_warnings.append(
                    f"[{m.label}] PIT fundamentals active: loader covers {pit_coverage*100:.0f}% of universe."
                )
            else:
                msg = (
                    f"[{m.label}] Strategy weights fundamentals at {fundamental_weight*100:.0f}%. "
                    f"yfinance fundamentals are current-snapshot — lookahead leak."
                )
                if not bt_cfg.accept_lookahead:
                    raise LookaheadGuardError(msg + " Pass accept_lookahead=True to override.")
                shared_warnings.append("LOOKAHEAD ACCEPTED: " + msg)

    # Per-mode state holders.
    mode_state: dict[str, dict] = {}
    for m in modes:
        mode_state[m.label] = {
            "portfolio": SimPortfolio(
                starting_cash=bt_cfg.starting_cash,
                max_position_pct=bt_cfg.max_position_pct,
                max_open_positions=bt_cfg.max_open_positions,
                compound=bt_cfg.compound,
                commission_per_trade=bt_cfg.commission_per_trade,
                regulatory_bps_on_sale=bt_cfg.regulatory_bps_on_sale,
                slippage_bps=bt_cfg.slippage_bps,
                vol_target_risk_pct=bt_cfg.vol_target_risk_pct,
            ),
            "equity_curve": [],
            "skipped_earnings": 0,
            "skipped_regime": 0,
            "warnings": list(shared_warnings),
        }

    regime_history: list[dict] = []
    # Strategy used for the analyzer chain. Analyzers don't depend on weights;
    # we discard the composite they compute and re-derive per mode from cache.
    primary_strategy = modes[0].strategy

    score_cache = ScoreCache()

    with Progress(
        SpinnerColumn(),
        TextColumn(f"[bold]{progress_label}[/bold]"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("{task.fields[when]}"),
        transient=True,
    ) as progress:
        task = progress.add_task("walking", total=len(schedule), when="")
        for as_of in schedule:
            progress.update(task, when=as_of.strftime("%Y-%m-%d"))

            # Per-mode exits.
            for m in modes:
                _process_exits_through(
                    mode_state[m.label]["portfolio"], price_data, as_of,
                    bt_cfg.max_staleness_days,
                )

            # Shared regime classification.
            regime_snap = classify_at(spy_df, vix_df, as_of, regime_params)
            regime_history.append({
                "date": as_of.strftime("%Y-%m-%d"),
                "label": regime_snap.label,
                "vix": regime_snap.vix_level,
                "spy_above_sma": regime_snap.spy_above_sma,
            })
            entries_allowed = gate_allows_entry(regime_snap.label, regime_mode)

            # Score ONCE — cache populated as a side effect.
            scored = _score_all_tickers_for_date(
                as_of, price_data, fundamentals, config, primary_strategy,
                workers=bt_cfg.workers,
                min_history_bars=bt_cfg.min_history_bars,
                spy_df=spy_df,
                sector_stats=sector_stats,
                earnings_history=earnings_history,
                insider_transactions=insider_transactions,
                narrative_snapshots=narrative_snapshots,
                fundamentals_pit_loader=fundamentals_pit_loader,
                short_interest_history=short_interest_history,
                sector_etfs=sector_etfs,
                score_cache=score_cache,
            )
            result_by_ticker = {t: r for t, r in scored}
            cached_today = score_cache.for_date(as_of)

            # Per-mode entries / mark-to-market.
            for m in modes:
                st = mode_state[m.label]
                portfolio = st["portfolio"]
                use_cs = bool(m.strategy.get("use_consensus_scaling", False))
                weights = m.strategy.get("weights", {}) or {}

                rescored: list[tuple[str, dict, float]] = []
                for ticker in result_by_ticker:
                    cached = cached_today.get(ticker)
                    if cached is None:
                        continue
                    composite, _diag = recompose_composite(
                        cached, weights,
                        enabled_sources=m.enabled_sources,
                        use_consensus_scaling=use_cs,
                    )
                    rescored.append((ticker, result_by_ticker[ticker], composite))

                rescored.sort(key=lambda x: (-x[2], x[0]))

                if not entries_allowed:
                    st["skipped_regime"] += sum(
                        1 for _, _, c in rescored
                        if not pd.isna(c) and c >= bt_cfg.min_score
                    )
                    rescored = []

                for ticker, result, composite in rescored:
                    if pd.isna(composite):
                        continue
                    # See single-mode gate above — reviewer B1.
                    if not result.get("score_valid", True):
                        continue
                    if composite < bt_cfg.min_score:
                        break
                    if not portfolio.can_open(ticker):
                        continue
                    df = price_data[ticker]
                    next_day = _next_trading_day_inclusive(df, as_of)
                    if next_day is None:
                        continue
                    if _is_in_earnings_blackout(ticker, next_day, earnings_dates, bt_cfg.earnings_blackout_days):
                        st["skipped_earnings"] += 1
                        continue
                    next_bar = df.loc[next_day]
                    entry_price = float(next_bar["Open"])
                    if entry_price <= 0:
                        continue
                    atr = result.get("_atr", 0)
                    if atr <= 0:
                        continue
                    stop_price = entry_price - atr * bt_cfg.atr_stop_mult
                    target_price = entry_price + atr * bt_cfg.atr_target_mult
                    max_exit_date = next_day + pd.Timedelta(days=bt_cfg.max_hold_days)
                    fund = fundamentals.get(ticker, {}) or {}
                    portfolio.open_position(
                        ticker=ticker,
                        entry_price=entry_price,
                        entry_date=next_day,
                        stop_price=stop_price,
                        target_price=target_price,
                        max_exit_date=max_exit_date,
                        score=composite,
                        sector=fund.get("sector", "Unknown"),
                    )

                mtm = {
                    t: _close_at_or_before(price_data[t], as_of, bt_cfg.max_staleness_days)
                    for t in portfolio.positions
                }
                st["equity_curve"].append({
                    "date": as_of.strftime("%Y-%m-%d"),
                    "equity": round(portfolio.equity({k: v for k, v in mtm.items() if v is not None}), 2),
                    "open_positions": len(portfolio.positions),
                    "cash": round(portfolio.cash, 2),
                })
            progress.advance(task)

    # End-of-walk per mode.
    results: dict[str, dict] = {}
    for m in modes:
        st = mode_state[m.label]
        portfolio = st["portfolio"]
        _process_exits_through(portfolio, price_data, end, bt_cfg.max_staleness_days)
        portfolio.force_close_all(
            last_day=end,
            price_lookup=lambda t, d, _pd=price_data: _close_at_or_before(
                _pd.get(t), d, bt_cfg.max_staleness_days
            ),
        )
        results[m.label] = _finalize_result(
            portfolio=portfolio,
            equity_curve=st["equity_curve"],
            regime_history=list(regime_history),
            warnings=list(st["warnings"]),
            start=start, end=end,
            bt_cfg=bt_cfg,
            spy_df=spy_df, vix_df=vix_df,
            sector_stats=sector_stats, sector_cfg=sector_cfg,
            regime_enabled=regime_enabled,
            regime_mode=regime_mode,
            regime_params=regime_params,
            skipped_earnings=st["skipped_earnings"],
            skipped_regime=st["skipped_regime"],
        )
    return results
