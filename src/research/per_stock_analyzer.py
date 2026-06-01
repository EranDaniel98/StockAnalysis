"""Comprehensive per-stock analyzer.

Pulls together every data source we have — factor ranks, EDGAR
fundamentals, technicals, analyst targets, short interest — and
produces an actionable trading plan for one ticker:

  - WHY: factor breakdown that earned the pick
  - WHEN to BUY: entry price + earnings-blackout warning
  - WHEN to EXIT: time-stop date + price-target + ATR stop-loss
  - EXPECTED PRICE: target derived from backtest median per-pick
    return for this strategy

The analyzer is intentionally OPINIONATED — every section ends with
a numerical recommendation. Wishy-washy "you might consider"
language is the enemy of actionability.

Design notes
------------
- Lookahead-safe (only uses prices on/before as_of for technicals)
- Sync — designed for one-off report generation, not the hot path
- Returns a dict with all the numbers; renderer is a separate fn
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from src.factors.strategy_id import strategy_name

logger = logging.getLogger(__name__)


# Strategy label sourced from config/settings.yaml strategy.name.
STRATEGY_LABEL = strategy_name()
REBALANCE_TRADING_DAYS = 63          # quarterly
PER_PICK_TARGET_RETURN_PCT = 8.0     # median expected over hold window
PER_PICK_BULL_RETURN_PCT = 18.0      # 75th percentile rough estimate
PER_PICK_BEAR_RETURN_PCT = -6.0      # 25th percentile rough estimate
ATR_STOP_MULTIPLE = 2.5              # stop = entry - 2.5 * ATR(20)
MIN_STOP_PCT = 0.05                  # floor: don't stop tighter than 5%
MAX_STOP_PCT = 0.12                  # ceiling: don't stop wider than 12%
EARNINGS_BLACKOUT_DAYS = 5           # warn if earnings within N days


@dataclass
class TechnicalSnapshot:
    """Pure-price technicals at as_of."""
    close: float
    sma_20: float | None
    sma_50: float | None
    sma_200: float | None
    atr_20: float | None
    high_52w: float | None
    low_52w: float | None
    pct_from_52w_high: float | None
    pct_from_52w_low: float | None
    ret_1m: float | None
    ret_3m: float | None
    ret_12m: float | None
    avg_dollar_vol_20d: float | None
    above_200d: bool | None
    above_50d: bool | None


@dataclass
class FundamentalSnapshot:
    """Latest EDGAR figures for the ticker at as_of."""
    filing_date: str | None
    source: str | None
    revenue_ttm: float | None
    revenue_growth_yoy: float | None
    earnings_growth_yoy: float | None
    eps_diluted: float | None
    eps_ttm: float | None
    gross_margin: float | None
    operating_margin: float | None
    profit_margin: float | None
    roe: float | None
    roa: float | None
    debt_to_equity: float | None
    current_ratio: float | None
    sector: str | None
    industry: str | None


@dataclass
class TradingPlan:
    """The opinionated recommendation."""
    entry_price: float
    stop_loss_price: float
    stop_loss_pct: float
    target_price: float
    target_pct: float
    time_exit_date: str       # next quarterly rebalance ISO date
    time_exit_trading_days: int
    position_size_pct: float  # 1/N of equity
    position_size_usd: float
    target_shares: int
    risk_per_share: float
    reward_to_risk: float     # (target - entry) / (entry - stop)


@dataclass
class RiskFlags:
    """Things to look at before pressing buy."""
    earnings_within_blackout: bool
    days_to_next_earnings: int | None
    low_liquidity: bool             # < $5M avg daily dollar volume
    extended_above_200d: bool       # > 30% above 200-SMA (overbought)
    deeply_below_200d: bool         # < -10% below 200-SMA (catching falling knife)
    sector_concentration_warning: str | None  # filled at portfolio level
    other: list[str] = field(default_factory=list)


@dataclass
class InsiderActivity:
    """Form 4 summary for the last N days."""
    window_days: int
    n_buys: int
    n_sells: int
    buy_value_usd: float
    sell_value_usd: float
    net_value_usd: float
    most_recent_date: str | None
    signal: str  # "bullish" | "bearish" | "neutral" | "no_data"


@dataclass
class StockAnalysis:
    """Full per-stock analysis bundle."""
    ticker: str
    as_of: str
    portfolio_rank: int
    composite_z: float
    momentum_rank: int | None
    quality_rank: int | None
    value_rank: int | None
    momentum_raw: float | None
    technicals: TechnicalSnapshot
    fundamentals: FundamentalSnapshot
    plan: TradingPlan
    risk_flags: RiskFlags
    expected_return_pct: float
    bull_case_pct: float
    bear_case_pct: float
    analyst_target: float | None = None
    analyst_recommendation: str | None = None
    short_pct_float: float | None = None
    beta: float | None = None
    insider: InsiderActivity | None = None
    rationale: str = ""


def _trailing_n_close(prices: pd.DataFrame, as_of: pd.Timestamp, offset: int) -> float | None:
    if prices is None or prices.empty:
        return None
    eligible = prices[prices.index <= as_of]
    if len(eligible) <= offset:
        return None
    v = eligible["Close"].iloc[-(offset + 1)]
    return None if pd.isna(v) else float(v)


def _sma(prices: pd.DataFrame, as_of: pd.Timestamp, window: int) -> float | None:
    if prices is None or prices.empty:
        return None
    eligible = prices[prices.index <= as_of]
    if len(eligible) < window:
        return None
    s = eligible["Close"].iloc[-window:].mean()
    return None if pd.isna(s) else float(s)


def _atr(prices: pd.DataFrame, as_of: pd.Timestamp, window: int = 20) -> float | None:
    if prices is None or prices.empty:
        return None
    cols = {c for c in prices.columns}
    if not {"High", "Low", "Close"}.issubset(cols):
        return None
    eligible = prices[prices.index <= as_of]
    if len(eligible) < window + 1:
        return None
    h = eligible["High"].iloc[-(window + 1):]
    l = eligible["Low"].iloc[-(window + 1):]
    c_prev = eligible["Close"].iloc[-(window + 1):].shift(1)
    tr = pd.concat([
        h - l,
        (h - c_prev).abs(),
        (l - c_prev).abs(),
    ], axis=1).max(axis=1)
    atr = tr.iloc[1:].mean()
    return None if pd.isna(atr) else float(atr)


def _52w(prices: pd.DataFrame, as_of: pd.Timestamp) -> tuple[float | None, float | None]:
    eligible = prices[prices.index <= as_of].iloc[-252:]
    if eligible.empty:
        return None, None
    hi = float(eligible["High"].max()) if "High" in eligible.columns else float(eligible["Close"].max())
    lo = float(eligible["Low"].min()) if "Low" in eligible.columns else float(eligible["Close"].min())
    return hi, lo


def _avg_dollar_volume(prices: pd.DataFrame, as_of: pd.Timestamp, window: int = 20) -> float | None:
    if prices is None or prices.empty or "Volume" not in prices.columns:
        return None
    eligible = prices[prices.index <= as_of]
    if len(eligible) < window:
        return None
    last = eligible.iloc[-window:]
    dv = (last["Close"] * last["Volume"]).mean()
    return None if pd.isna(dv) else float(dv)


def compute_technicals(
    prices: pd.DataFrame, as_of: pd.Timestamp,
) -> TechnicalSnapshot:
    close = _trailing_n_close(prices, as_of, 0)
    sma_20 = _sma(prices, as_of, 20)
    sma_50 = _sma(prices, as_of, 50)
    sma_200 = _sma(prices, as_of, 200)
    atr_20 = _atr(prices, as_of, 20)
    hi52, lo52 = _52w(prices, as_of)
    pct_from_high = None
    pct_from_low = None
    if close is not None and hi52 and lo52:
        pct_from_high = (close - hi52) / hi52
        pct_from_low = (close - lo52) / lo52
    ret_1m_close = _trailing_n_close(prices, as_of, 21)
    ret_3m_close = _trailing_n_close(prices, as_of, 63)
    ret_12m_close = _trailing_n_close(prices, as_of, 252)
    def _ret(prev: float | None) -> float | None:
        if prev is None or close is None or prev == 0:
            return None
        return close / prev - 1.0
    return TechnicalSnapshot(
        close=close or 0.0,
        sma_20=sma_20,
        sma_50=sma_50,
        sma_200=sma_200,
        atr_20=atr_20,
        high_52w=hi52,
        low_52w=lo52,
        pct_from_52w_high=pct_from_high,
        pct_from_52w_low=pct_from_low,
        ret_1m=_ret(ret_1m_close),
        ret_3m=_ret(ret_3m_close),
        ret_12m=_ret(ret_12m_close),
        avg_dollar_vol_20d=_avg_dollar_volume(prices, as_of),
        above_200d=(close > sma_200) if (close and sma_200) else None,
        above_50d=(close > sma_50) if (close and sma_50) else None,
    )


def compute_fundamentals(
    loader, ticker: str, as_of: pd.Timestamp,
) -> FundamentalSnapshot:
    as_of_dt = as_of.to_pydatetime()
    if as_of_dt.tzinfo is None:
        as_of_dt = as_of_dt.replace(tzinfo=timezone.utc)
    snap = loader.lookup(ticker, as_of_dt)
    if snap is None:
        return FundamentalSnapshot(
            filing_date=None, source=None, revenue_ttm=None,
            revenue_growth_yoy=None, earnings_growth_yoy=None,
            eps_diluted=None, eps_ttm=None,
            gross_margin=None, operating_margin=None, profit_margin=None,
            roe=None, roa=None, debt_to_equity=None,
            current_ratio=None, sector=None, industry=None,
        )
    eps_ttm = loader.compute_eps_ttm(ticker, as_of_dt)
    return FundamentalSnapshot(
        filing_date=str(snap.valid_from.date()) if snap.valid_from else None,
        source=snap.source,
        revenue_ttm=snap.revenue,
        revenue_growth_yoy=snap.revenue_growth_yoy,
        earnings_growth_yoy=snap.earnings_growth_yoy,
        eps_diluted=snap.eps_diluted,
        eps_ttm=eps_ttm,
        gross_margin=snap.gross_margin,
        operating_margin=snap.operating_margin,
        profit_margin=snap.profit_margin,
        roe=snap.roe,
        roa=snap.roa,
        debt_to_equity=snap.debt_to_equity,
        current_ratio=snap.current_ratio,
        sector=getattr(snap, "sector", None),
        industry=getattr(snap, "industry", None),
    )


def compute_trading_plan(
    *, close: float, atr_20: float | None, equity_usd: float,
    n_positions: int, as_of: pd.Timestamp,
) -> TradingPlan:
    """Build the actionable trade levels.

    Stop: entry - 2.5*ATR(20). If ATR unavailable, fall back to -8%.
    Target: entry * (1 + 8%) for the median 63-day hold.
    Time exit: 63 trading days from as_of (~next quarterly rebalance).
    """
    entry = close
    if atr_20 is not None and atr_20 > 0:
        atr_stop_pct = ATR_STOP_MULTIPLE * atr_20 / entry
    else:
        atr_stop_pct = 0.08
    # Bound the stop in [MIN, MAX] so low-vol names don't get hair-trigger
    # stops and high-vol names don't risk a third of the position.
    bounded_stop_pct = max(MIN_STOP_PCT, min(MAX_STOP_PCT, atr_stop_pct))
    stop_pct = -bounded_stop_pct
    stop_loss = entry * (1 + stop_pct)
    target = entry * (1.0 + PER_PICK_TARGET_RETURN_PCT / 100.0)
    target_pct = PER_PICK_TARGET_RETURN_PCT / 100.0
    time_exit = as_of + pd.tseries.offsets.BDay(REBALANCE_TRADING_DAYS)
    pos_size_pct = 1.0 / max(1, n_positions)
    pos_size_usd = equity_usd * pos_size_pct
    target_shares = int(pos_size_usd // max(0.01, entry))
    risk_per_share = entry - stop_loss
    reward = target - entry
    rr = reward / max(0.0001, risk_per_share)
    return TradingPlan(
        entry_price=round(entry, 2),
        stop_loss_price=round(stop_loss, 2),
        stop_loss_pct=round(stop_pct * 100, 2),
        target_price=round(target, 2),
        target_pct=round(target_pct * 100, 2),
        time_exit_date=time_exit.strftime("%Y-%m-%d"),
        time_exit_trading_days=REBALANCE_TRADING_DAYS,
        position_size_pct=round(pos_size_pct * 100, 2),
        position_size_usd=round(pos_size_usd, 2),
        target_shares=target_shares,
        risk_per_share=round(risk_per_share, 2),
        reward_to_risk=round(rr, 2),
    )


def compute_insider_activity(
    transactions: list[dict],
    window_days: int = 90,
    market_cap_usd: float | None = None,
) -> InsiderActivity:
    """Summarize Form 4 activity for one ticker.

    Transaction codes (SEC):
      - P: open-market purchase (BULLISH — exec putting own money in)
      - A: grant / award (neutral — comp, not conviction)
      - S: open-market sale (mixed — could be tax / diversification)
      - M: option exercise (neutral)
      - F: tax withholding on RSU vest (neutral)

    Only P + S signal real conviction. We sum dollar values and emit
    a bull/bear/neutral verdict, scaled by market cap so routine
    megacap exec sales (which are noise) don't flag bearish.

    Signal thresholds:
      - bullish: buys > 2x sells AND buys ≥ 0.005% of mkt cap
        (i.e., a meaningful insider purchase, not a $1K test)
      - bearish: sells > 2x buys AND sells ≥ 0.05% of mkt cap
        (5x the buy threshold — sells are noisier than buys)
      - neutral: anything else with transactions

    When mkt_cap is None, fall back to absolute dollar thresholds
    ($100K buy / $500K sell).
    """
    if not transactions:
        return InsiderActivity(
            window_days=window_days, n_buys=0, n_sells=0,
            buy_value_usd=0.0, sell_value_usd=0.0, net_value_usd=0.0,
            most_recent_date=None, signal="no_data",
        )

    n_buys = 0
    n_sells = 0
    buy_value = 0.0
    sell_value = 0.0
    most_recent = None
    for t in transactions:
        code = (t.get("transaction_code") or "").upper()
        val = float(t.get("value_usd") or 0.0)
        dt = t.get("transaction_date") or t.get("filing_date")
        if dt is not None:
            d_str = dt.isoformat() if hasattr(dt, "isoformat") else str(dt)
            if most_recent is None or d_str > most_recent:
                most_recent = d_str
        if code == "P":
            n_buys += 1
            buy_value += val
        elif code == "S":
            n_sells += 1
            sell_value += val

    net = buy_value - sell_value

    # Calibrate thresholds by market cap when available.
    if market_cap_usd and market_cap_usd > 0:
        buy_threshold = market_cap_usd * 0.00005  # 0.005% of mkt cap
        sell_threshold = market_cap_usd * 0.0005   # 0.05% of mkt cap
    else:
        buy_threshold = 100_000.0
        sell_threshold = 500_000.0

    if buy_value == 0 and sell_value == 0:
        signal = "no_data"
    elif buy_value > sell_value * 2 and buy_value >= buy_threshold:
        signal = "bullish"
    elif sell_value > buy_value * 2 and sell_value >= sell_threshold:
        signal = "bearish"
    else:
        signal = "neutral"

    return InsiderActivity(
        window_days=window_days,
        n_buys=n_buys, n_sells=n_sells,
        buy_value_usd=buy_value, sell_value_usd=sell_value,
        net_value_usd=net,
        most_recent_date=most_recent,
        signal=signal,
    )


def compute_risk_flags(
    *, tech: TechnicalSnapshot,
    days_to_next_earnings: int | None,
    short_pct_float: float | None,
) -> RiskFlags:
    flags = RiskFlags(
        earnings_within_blackout=(
            days_to_next_earnings is not None
            and 0 <= days_to_next_earnings <= EARNINGS_BLACKOUT_DAYS
        ),
        days_to_next_earnings=days_to_next_earnings,
        low_liquidity=(
            tech.avg_dollar_vol_20d is not None
            and tech.avg_dollar_vol_20d < 5_000_000
        ),
        extended_above_200d=(
            tech.sma_200 is not None and tech.close is not None
            and (tech.close / tech.sma_200 - 1) > 0.30
        ),
        deeply_below_200d=(
            tech.sma_200 is not None and tech.close is not None
            and (tech.close / tech.sma_200 - 1) < -0.10
        ),
        sector_concentration_warning=None,
    )
    if short_pct_float is not None and short_pct_float > 0.10:
        flags.other.append(
            f"short_interest_high ({short_pct_float*100:.1f}% of float)"
        )
    if tech.atr_20 is None:
        flags.other.append("atr_unavailable_using_fixed_8pct_stop")
    return flags


def build_rationale(
    *, ticker: str, composite_z: float,
    mom_rank: int | None, qual_rank: int | None, val_rank: int | None,
    fund: FundamentalSnapshot, tech: TechnicalSnapshot,
) -> str:
    """A short, opinionated explanation of why this name made the cut."""
    bits: list[str] = []
    bits.append(f"{ticker} sits at composite z={composite_z:+.2f}.")

    # Which factor(s) carried the rank?
    factor_calls = []
    if mom_rank is not None and mom_rank <= 60:
        ret_str = f", {tech.ret_12m*100:+.0f}% past year" if tech.ret_12m else ""
        factor_calls.append(f"strong momentum (rank #{mom_rank}{ret_str})")
    if qual_rank is not None and qual_rank <= 60:
        margin_str = (f", op-margin {fund.operating_margin*100:.0f}%"
                      if fund.operating_margin else "")
        factor_calls.append(f"high quality (rank #{qual_rank}{margin_str})")
    if val_rank is not None and val_rank <= 60:
        ey = (fund.eps_ttm / tech.close) if (fund.eps_ttm and tech.close) else None
        ey_str = f", earnings yield {ey*100:.1f}%" if ey else ""
        factor_calls.append(f"cheap valuation (rank #{val_rank}{ey_str})")
    if factor_calls:
        bits.append("Top by " + " + ".join(factor_calls) + ".")
    else:
        bits.append("Picked on cross-factor consistency rather than "
                    "any single factor extreme.")

    if tech.above_200d is True:
        bits.append("Price is above the 200-day SMA (confirmed uptrend).")
    elif tech.above_200d is False:
        bits.append("Price is BELOW the 200-day SMA — countertrend pick, "
                    "respect the stop.")
    return " ".join(bits)


def compute_correlation_matrix(
    prices: dict[str, pd.DataFrame],
    tickers: list[str],
    as_of: pd.Timestamp,
    window_days: int = 60,
) -> tuple[pd.DataFrame, dict]:
    """Pairwise daily-return correlations over the trailing ``window_days``.

    Returns (corr_df, summary) where summary is:
      - mean_off_diagonal: average pairwise correlation (excluding diag)
      - effective_n: 1/mean_off_diagonal (rough "independent positions")
      - top_pairs:  list of (ticker_a, ticker_b, corr) — highest 5
      - bottom_pairs: lowest 5 (best diversifiers)
    """
    as_of_ts = pd.Timestamp(as_of)
    # Build a returns matrix
    rets: dict[str, pd.Series] = {}
    for t in tickers:
        df = prices.get(t)
        if df is None or df.empty or "Close" not in df.columns:
            continue
        eligible = df[df.index <= as_of_ts].iloc[-(window_days + 1):]
        if len(eligible) < window_days // 2:
            continue
        rets[t] = eligible["Close"].pct_change().dropna()
    if len(rets) < 2:
        return pd.DataFrame(), {
            "mean_off_diagonal": None, "effective_n": None,
            "top_pairs": [], "bottom_pairs": [],
        }

    rets_df = pd.DataFrame(rets).dropna(how="all")
    corr = rets_df.corr()

    # Off-diagonal stats
    n = len(corr)
    tri = corr.where(~np.eye(n, dtype=bool))
    flat = tri.stack().dropna()
    mean_off = float(flat.mean())
    # Effective N for an equal-weight portfolio under uniform correlation:
    # N_eff = N / (1 + (N-1) * rho). Reduces to N when rho=0, to 1 when
    # rho=1. The intuition: high pairwise correlation collapses the
    # portfolio toward a single bet.
    if mean_off >= 0.99:
        effective_n = 1.0
    elif mean_off <= 0:
        effective_n = float(n)
    else:
        effective_n = float(n) / (1.0 + (n - 1) * mean_off)

    # Top/bottom pairs (one per pair, not duplicates)
    pair_records: list[tuple[str, str, float]] = []
    cols = list(corr.columns)
    for i in range(n):
        for j in range(i + 1, n):
            pair_records.append((cols[i], cols[j], float(corr.iat[i, j])))
    pair_records.sort(key=lambda x: x[2], reverse=True)
    top_pairs = pair_records[:5]
    bottom_pairs = pair_records[-5:][::-1]  # most negative first

    return corr, {
        "mean_off_diagonal": round(mean_off, 3),
        "effective_n": round(effective_n, 1),
        "top_pairs": top_pairs,
        "bottom_pairs": bottom_pairs,
        "n_tickers": n,
        "window_days": window_days,
    }


def estimate_per_pick_returns(
    backtest_trade_log: list[dict] | None = None,
) -> tuple[float, float, float]:
    """Return (median, 75th-pctile, 25th-pctile) per-pick return %.

    If a trade log is provided, derive from observed outcomes. Else
    fall back to literature priors: median +8%, bull +18%, bear -6%.
    """
    if not backtest_trade_log:
        return PER_PICK_TARGET_RETURN_PCT, PER_PICK_BULL_RETURN_PCT, PER_PICK_BEAR_RETURN_PCT
    # Round-trip the log into per-name returns. The log has 'side' and
    # 'shares' so we can match buys to subsequent sells.
    by_ticker: dict[str, list[dict]] = {}
    for t in backtest_trade_log:
        by_ticker.setdefault(t["ticker"], []).append(t)
    rets: list[float] = []
    for tk, events in by_ticker.items():
        events = sorted(events, key=lambda e: e["date"])
        position = 0
        avg_cost = 0.0
        for e in events:
            qty = e.get("shares", 0)
            px = e.get("price", 0)
            if "buy" in e["side"]:
                new_pos = position + qty
                if new_pos > 0:
                    avg_cost = (avg_cost * position + px * qty) / new_pos
                position = new_pos
            elif "sell" in e["side"] and position > 0 and avg_cost > 0:
                ret = (px - avg_cost) / avg_cost
                rets.append(ret)
                position = max(0, position - qty)
                if position == 0:
                    avg_cost = 0.0
    if not rets:
        return PER_PICK_TARGET_RETURN_PCT, PER_PICK_BULL_RETURN_PCT, PER_PICK_BEAR_RETURN_PCT
    arr = np.array(rets) * 100
    return (
        float(np.median(arr)),
        float(np.percentile(arr, 75)),
        float(np.percentile(arr, 25)),
    )


def analyze_ticker(
    *,
    ticker: str,
    prices: pd.DataFrame,
    loader,
    as_of: pd.Timestamp,
    composite_rank: int,
    composite_z: float,
    mom_rank: int | None,
    qual_rank: int | None,
    val_rank: int | None,
    mom_raw: float | None,
    equity_usd: float,
    n_positions: int,
    expected_returns: tuple[float, float, float],
    days_to_next_earnings: int | None = None,
    yf_info: dict | None = None,
    insider_txs: list[dict] | None = None,
) -> StockAnalysis:
    tech = compute_technicals(prices, as_of)
    fund = compute_fundamentals(loader, ticker, as_of)
    plan = compute_trading_plan(
        close=tech.close, atr_20=tech.atr_20,
        equity_usd=equity_usd, n_positions=n_positions, as_of=as_of,
    )
    short_pct = None
    analyst_tgt = None
    analyst_rec = None
    beta = None
    if yf_info:
        short_pct = yf_info.get("shortPercentOfFloat")
        analyst_tgt = yf_info.get("targetMeanPrice")
        analyst_rec = yf_info.get("recommendationKey")
        beta = yf_info.get("beta")
        # If we don't have sector from EDGAR, take it from yfinance.
        if not fund.sector:
            fund.sector = yf_info.get("sector")
            fund.industry = yf_info.get("industry")
    risk = compute_risk_flags(
        tech=tech,
        days_to_next_earnings=days_to_next_earnings,
        short_pct_float=short_pct,
    )
    mkt_cap = None
    if yf_info:
        mkt_cap = yf_info.get("marketCap")
    insider = compute_insider_activity(
        insider_txs or [], window_days=90, market_cap_usd=mkt_cap,
    )
    rationale = build_rationale(
        ticker=ticker, composite_z=composite_z,
        mom_rank=mom_rank, qual_rank=qual_rank, val_rank=val_rank,
        fund=fund, tech=tech,
    )
    return StockAnalysis(
        ticker=ticker,
        as_of=as_of.date().isoformat(),
        portfolio_rank=composite_rank,
        composite_z=composite_z,
        momentum_rank=mom_rank,
        quality_rank=qual_rank,
        value_rank=val_rank,
        momentum_raw=mom_raw,
        technicals=tech,
        fundamentals=fund,
        plan=plan,
        risk_flags=risk,
        expected_return_pct=expected_returns[0],
        bull_case_pct=expected_returns[1],
        bear_case_pct=expected_returns[2],
        analyst_target=analyst_tgt,
        analyst_recommendation=analyst_rec,
        short_pct_float=short_pct,
        beta=beta,
        insider=insider,
        rationale=rationale,
    )
