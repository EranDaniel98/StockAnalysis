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
) -> dict:
    """
    Walk-forward backtest. Returns dict with:
      summary, calibration, trades, exit_reasons, equity_curve, warnings
    """
    warnings: list[str] = []

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
    )

    equity_curve: list[dict] = []

    fundamental_weight = strategy.get("weights", {}).get("fundamental", 0)
    if fundamental_weight > 0.10:
        warnings.append(
            f"Strategy weights fundamentals at {fundamental_weight*100:.0f}%. yfinance "
            f"fundamentals are point-in-time-NOW, not historical — backtest results are "
            f"likely optimistic. Treat fundamental-heavy results with skepticism."
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
    from src.backtest.metrics import calibration_table, exit_reason_breakdown, summary_stats, verdict
    cal = calibration_table(portfolio.closed_trades)
    exits = exit_reason_breakdown(portfolio.closed_trades)
    spy_ret = _spy_buy_hold_return(spy_df, start, end)
    stats = summary_stats(
        portfolio.closed_trades,
        starting_cash=bt_cfg.starting_cash,
        ending_equity=portfolio.cash,  # all positions force-closed by here
        start_date=start,
        end_date=end,
        spy_return_pct=spy_ret,
    )
    return {
        "summary": stats,
        "calibration": cal,
        "trades": [t.to_dict() for t in portfolio.closed_trades],
        "exit_reasons": exits,
        "equity_curve": equity_curve,
        "verdict": verdict(cal),
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
