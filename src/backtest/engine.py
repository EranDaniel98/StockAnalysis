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

from src.analysis import technical, fundamental, patterns, statistical
from src.analysis.trend_detector import analyze_stock_trend
from src.scoring.engine import calculate_composite_score
from src.backtest.portfolio import SimPortfolio

logger = logging.getLogger(__name__)


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


class LookaheadGuardError(RuntimeError):
    """Raised when a strategy's fundamental weight would silently leak future knowledge."""


def fetch_earnings_dates(tickers: list[str], workers: int = 8) -> dict[str, list[pd.Timestamp]]:
    """
    Fetch historical + upcoming earnings dates for each ticker via yfinance.
    Returns {ticker: sorted list of tz-naive Timestamps}. Empty list on failure.
    Parallelized — each yfinance call is network-bound.
    """
    import yfinance as yf

    def _fetch_one(t):
        try:
            df = yf.Ticker(t).get_earnings_dates(limit=40)
            if df is None or df.empty:
                return t, []
            idx = df.index
            if isinstance(idx, pd.DatetimeIndex) and idx.tz is not None:
                idx = idx.tz_localize(None)
            return t, sorted(pd.to_datetime(idx).tolist())
        except Exception as e:
            logger.debug(f"Earnings fetch failed for {t}: {e}")
            return t, []

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


def _score_ticker(ticker: str, df_slice: pd.DataFrame, fund: dict, config, strategy: dict) -> Optional[dict]:
    """Run all 5 analyzers on a sliced df and return composite score result + ATR."""
    if df_slice is None or len(df_slice) < 50:
        return None
    try:
        tech = technical.analyze(df_slice, config)
        fnd = fundamental.analyze(fund, config)
        pat = patterns.analyze(df_slice, config)
        stat = statistical.analyze(df_slice, config)
        trnd = analyze_stock_trend(df_slice, fund, config)
        score_result = calculate_composite_score(tech, fnd, pat, stat, trnd, strategy)
        score_result["_atr"] = _atr(df_slice)
        score_result["_close"] = float(df_slice["Close"].iloc[-1])
        return score_result
    except Exception as e:
        logger.debug(f"Score error {ticker}: {e}")
        return None


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
    earnings_dates: Optional[dict[str, list[pd.Timestamp]]] = None,
) -> dict:
    """
    Walk-forward backtest. Returns dict with:
      summary, calibration, trades, exit_reasons, equity_curve, warnings
    """
    warnings: list[str] = []
    earnings_dates = earnings_dates or {}
    skipped_earnings = 0

    # Normalize all indices once
    price_data = {t: _normalize_index(df) for t, df in price_data.items() if df is not None and not df.empty}
    if not price_data:
        return {"error": "No price data available"}

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
    )

    equity_curve: list[dict] = []

    fundamental_weight = strategy.get("weights", {}).get("fundamental", 0)
    if fundamental_weight > 0.05:
        msg = (
            f"Strategy weights fundamentals at {fundamental_weight*100:.0f}%. "
            f"yfinance exposes only current fundamentals (not point-in-time historical), "
            f"so the score function reads 2026 financials at every historical Monday — "
            f"a hard look-ahead leak that produces fictitious alpha."
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

            # 2) For each ticker, slice df strictly BEFORE as_of (pre-open scan
            #    semantic — matches live `paper trade` running Sunday with Friday
            #    data) and score in parallel.
            scored: list[tuple[str, dict]] = []
            with ThreadPoolExecutor(max_workers=bt_cfg.workers) as ex:
                futures = {}
                for ticker, df in price_data.items():
                    df_slice = df.loc[df.index < as_of]
                    if len(df_slice) < bt_cfg.min_history_bars:
                        continue
                    fund = fundamentals.get(ticker, {}) or {}
                    futures[ex.submit(_score_ticker, ticker, df_slice, fund, config, strategy)] = ticker
                for fut in as_completed(futures):
                    ticker = futures[fut]
                    try:
                        result = fut.result()
                    except Exception as e:
                        logger.debug(f"Worker error {ticker}: {e}")
                        result = None
                    if result is not None:
                        scored.append((ticker, result))

            # 3) Rank by (composite_score desc, ticker asc). Deterministic
            #    tie-break ensures reproducible results across runs.
            scored.sort(key=lambda x: (-x[1]["composite_score"], x[0]))
            for ticker, result in scored:
                composite = result["composite_score"]
                if pd.isna(composite):
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

    # 6) Final metrics
    from src.backtest.metrics import (
        bootstrap_cis,
        calibration_table,
        cost_sensitivity_grid,
        deployment_matched_spy_return,
        equity_curve_stats,
        exit_reason_breakdown,
        summary_stats,
        verdict,
        verdict_with_stats,
    )
    spy_ret = _spy_buy_hold_return(spy_df, start, end)
    spy_match_ret = deployment_matched_spy_return(equity_curve, spy_df, start, end)
    exits = exit_reason_breakdown(portfolio.closed_trades)

    # Universal caveat: yfinance universe is current-snapshot — survivorship bias
    # is uncorrected. Delisted, bankrupt, and merged-away tickers are absent.
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

    # OOS split: last X of window is the held-out validation set.
    split_date = start + (end - start) * (1 - bt_cfg.oos_split_pct)
    is_trades = [t for t in portfolio.closed_trades if t.entry_date < split_date]
    oos_trades = [t for t in portfolio.closed_trades if t.entry_date >= split_date]
    is_equity = [e for e in equity_curve if pd.Timestamp(e["date"]) < split_date]
    oos_equity = [e for e in equity_curve if pd.Timestamp(e["date"]) >= split_date]

    def _compute_section(trades, equity_subset, section_start, section_end,
                         starting_capital, ending_equity):
        """
        Build a section's metrics. starting_capital is the equity at the
        section's start (= bt_cfg.starting_cash for Full and IS; = IS-end equity
        for OOS, so OOS measures returns on the capital actually deployed there).
        """
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
                total_costs=None,  # full-window costs only on the headline summary
            ),
            "equity_stats": equity_curve_stats(equity_subset),
            "calibration": calibration_table(trades),
        }

    # IS section starts at $starting_cash and ends at the equity-at-split.
    # OOS section starts at IS-end equity and ends at final cash. Without this,
    # OOS total return spuriously equals Full because both are anchored to
    # bt_cfg.starting_cash.
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

    # Verdict on OOS (the only trustworthy bucket)
    oos_verdict = verdict_with_stats(oos_section["calibration"])

    # Cost sensitivity (post-hoc on the trade list)
    sensitivity = cost_sensitivity_grid(
        portfolio.closed_trades,
        starting_cash=bt_cfg.starting_cash,
        fixed_commission=bt_cfg.commission_per_trade,
        fixed_reg_bps=bt_cfg.regulatory_bps_on_sale,
    )

    # Bootstrap CIs on OOS trades (or full if OOS too small)
    boot_target = oos_trades if len(oos_trades) >= 20 else portfolio.closed_trades
    boot_label = "OOS" if len(oos_trades) >= 20 else "full window"
    bootstrap = bootstrap_cis(
        boot_target,
        starting_cash=bt_cfg.starting_cash,
        n_resamples=bt_cfg.bootstrap_resamples,
    ) if bt_cfg.bootstrap_resamples > 0 else None

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
        "warnings": warnings,
    }


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
