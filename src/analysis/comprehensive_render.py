"""Markdown renderer for ``StockAnalysis`` objects.

Keeps the pure analysis logic (``comprehensive.py``) separate from
presentation. The renderer is opinionated: it never produces "you
might consider" — every section either prints a specific recommendation
or explicitly says "skip / no data".
"""

from __future__ import annotations

from collections import Counter

from src.analysis.comprehensive import (
    REBALANCE_TRADING_DAYS, STRATEGY_LABEL, StockAnalysis,
)


def _pct(v: float | None, places: int = 2) -> str:
    if v is None:
        return "—"
    return f"{v*100:+.{places}f}%"


def _money(v: float | None) -> str:
    if v is None:
        return "—"
    return f"${v:,.2f}"


def _big_money(v: float | None) -> str:
    """Format large dollar amounts with B/M suffix."""
    if v is None:
        return "—"
    if abs(v) >= 1e9:
        return f"${v/1e9:.2f}B"
    if abs(v) >= 1e6:
        return f"${v/1e6:.2f}M"
    return f"${v:,.2f}"


def _ratio(v: float | None, places: int = 2) -> str:
    if v is None:
        return "—"
    return f"{v:.{places}f}"


def render_one_stock(a: StockAnalysis) -> str:
    t = a.technicals
    f = a.fundamentals
    p = a.plan
    r = a.risk_flags

    lines: list[str] = []
    sector_str = f" — {f.sector}" if f.sector else ""
    lines.append(f"### #{a.portfolio_rank}. **{a.ticker}**{sector_str}")
    lines.append("")
    lines.append(f"_{a.rationale}_")
    lines.append("")

    # SNAPSHOT
    lines.append("**Snapshot**")
    snap_bits = [
        f"Price: **{_money(t.close)}**",
        f"Composite z: **{a.composite_z:+.2f}**",
    ]
    if a.analyst_target is not None and a.analyst_target > 0:
        upside = (a.analyst_target / t.close - 1) if t.close else None
        rec = f" — *{a.analyst_recommendation}*" if a.analyst_recommendation else ""
        snap_bits.append(
            f"Analyst tgt: {_money(a.analyst_target)} ({_pct(upside)}){rec}"
        )
    if a.beta is not None:
        snap_bits.append(f"β={a.beta:.2f}")
    lines.append(" | ".join(snap_bits))
    lines.append("")

    # FACTOR BREAKDOWN
    lines.append("**Factor breakdown**")
    lines.append("| Factor | Rank | Detail |")
    lines.append("|---|---|---|")
    mom_detail = (
        f"raw 12-1m return {_pct(a.momentum_raw)}"
        if a.momentum_raw is not None else "—"
    )
    lines.append(f"| Momentum | {a.momentum_rank if a.momentum_rank else '—'} | {mom_detail} |")
    qual_detail_bits = []
    if f.roe is not None:
        qual_detail_bits.append(f"ROE {f.roe*100:.1f}%")
    if f.operating_margin is not None:
        qual_detail_bits.append(f"OpMargin {f.operating_margin*100:.1f}%")
    if f.debt_to_equity is not None:
        qual_detail_bits.append(f"D/E {f.debt_to_equity:.2f}")
    lines.append(f"| Quality | {a.quality_rank if a.quality_rank else '—'} | {'; '.join(qual_detail_bits) if qual_detail_bits else '—'} |")
    val_detail_bits = []
    if f.eps_ttm is not None and t.close:
        val_detail_bits.append(f"earnings yield {(f.eps_ttm/t.close)*100:.2f}%")
    if f.revenue_ttm is not None:
        val_detail_bits.append(f"revenue TTM {_big_money(f.revenue_ttm)}")
    lines.append(f"| Value | {a.value_rank if a.value_rank else '—'} | {'; '.join(val_detail_bits) if val_detail_bits else '—'} |")
    lines.append("")

    # TECHNICALS
    lines.append("**Technical setup**")
    trend = "—"
    if t.above_200d is True and t.above_50d is True:
        trend = "uptrend confirmed (above 50d + 200d)"
    elif t.above_200d is True and t.above_50d is False:
        trend = "long-term up, short-term pullback (above 200d, below 50d)"
    elif t.above_200d is False and t.above_50d is True:
        trend = "potential trend change (above 50d but below 200d)"
    elif t.above_200d is False:
        trend = "downtrend (below 50d + 200d)"
    lines.append(f"- **Trend:** {trend}")
    if t.sma_200 is not None:
        dist_200 = (t.close / t.sma_200 - 1) if t.close else None
        lines.append(f"- **200-day SMA:** {_money(t.sma_200)} ({_pct(dist_200)})")
    if t.sma_50 is not None:
        dist_50 = (t.close / t.sma_50 - 1) if t.close else None
        lines.append(f"- **50-day SMA:** {_money(t.sma_50)} ({_pct(dist_50)})")
    if t.atr_20 is not None:
        atr_pct = t.atr_20 / t.close if t.close else 0
        lines.append(
            f"- **20-day ATR:** {_money(t.atr_20)} ({atr_pct*100:.1f}% of price) "
            f"— stop sized off this"
        )
    if t.high_52w is not None and t.low_52w is not None:
        lines.append(
            f"- **52-week range:** {_money(t.low_52w)} – {_money(t.high_52w)} "
            f"(currently {_pct(t.pct_from_52w_high)} from high, "
            f"{_pct(t.pct_from_52w_low)} from low)"
        )
    perf_bits = []
    if t.ret_1m is not None:
        perf_bits.append(f"1M {_pct(t.ret_1m)}")
    if t.ret_3m is not None:
        perf_bits.append(f"3M {_pct(t.ret_3m)}")
    if t.ret_12m is not None:
        perf_bits.append(f"12M {_pct(t.ret_12m)}")
    if perf_bits:
        lines.append(f"- **Returns:** {' | '.join(perf_bits)}")
    if t.avg_dollar_vol_20d is not None:
        lines.append(
            f"- **Liquidity:** {_big_money(t.avg_dollar_vol_20d)} avg daily $ volume"
        )
    lines.append("")

    # FUNDAMENTALS
    lines.append("**Fundamentals** (latest filing)")
    if f.filing_date:
        src = f.source or "edgar"
        lines.append(f"- **Latest filing:** {f.filing_date} ({src})")
    fund_rows = []
    if f.revenue_ttm is not None:
        rg = _pct(f.revenue_growth_yoy, 1) if f.revenue_growth_yoy is not None else "—"
        fund_rows.append(f"Revenue {_big_money(f.revenue_ttm)} ({rg} YoY)")
    if f.earnings_growth_yoy is not None:
        fund_rows.append(f"EPS growth {_pct(f.earnings_growth_yoy, 1)} YoY")
    if f.roe is not None:
        fund_rows.append(f"ROE {f.roe*100:.1f}%")
    if f.operating_margin is not None:
        fund_rows.append(f"OpMargin {f.operating_margin*100:.1f}%")
    if f.profit_margin is not None:
        fund_rows.append(f"NetMargin {f.profit_margin*100:.1f}%")
    if f.debt_to_equity is not None:
        fund_rows.append(f"D/E {f.debt_to_equity:.2f}")
    if f.current_ratio is not None:
        fund_rows.append(f"Current {f.current_ratio:.2f}")
    if fund_rows:
        lines.append("- " + " | ".join(fund_rows))
    lines.append("")

    # TRADING PLAN
    lines.append("**Trading plan**")
    lines.append("| Action | Price | Note |")
    lines.append("|---|---|---|")
    lines.append(
        f"| **ENTRY** | {_money(p.entry_price)} | "
        f"Market at next open. Position: {p.target_shares} sh "
        f"(~{_money(p.position_size_usd)}, {p.position_size_pct:.1f}% of equity) |"
    )
    lines.append(
        f"| **STOP LOSS** | {_money(p.stop_loss_price)} | "
        f"{p.stop_loss_pct:+.1f}% from entry — "
        f"2.5×ATR bounded to [5%, 12%] so low-vol names aren't "
        f"hair-triggered and high-vol names don't risk too much |"
    )
    lines.append(
        f"| **PROFIT TARGET** | {_money(p.target_price)} | "
        f"+{p.target_pct:.1f}% from entry (strategy median per-pick) |"
    )
    lines.append(
        f"| **TIME EXIT** | n/a | {p.time_exit_date} "
        f"(~{p.time_exit_trading_days} trading days) — next quarterly rebalance |"
    )
    lines.append(
        f"| **Risk/Reward** | {p.reward_to_risk:.2f}× | "
        f"risk {_money(p.risk_per_share)}/sh, reward {_money(p.target_price - p.entry_price)}/sh |"
    )
    lines.append("")

    # INSIDER ACTIVITY
    if a.insider and a.insider.signal != "no_data":
        ins = a.insider
        signal_emoji = {
            "bullish": "🟢", "bearish": "🔴", "neutral": "⚪",
        }.get(ins.signal, "⚪")
        lines.append(f"**Insider activity (last {ins.window_days} days)**")
        bits = []
        if ins.n_buys > 0:
            bits.append(f"{ins.n_buys} open-market buys ({_big_money(ins.buy_value_usd)})")
        if ins.n_sells > 0:
            bits.append(f"{ins.n_sells} sales ({_big_money(ins.sell_value_usd)})")
        if not bits:
            bits.append("no notable transactions")
        recency = f", most recent {ins.most_recent_date}" if ins.most_recent_date else ""
        lines.append(f"- {signal_emoji} **{ins.signal.upper()}** — "
                     f"net {_big_money(ins.net_value_usd)}; "
                     f"{'; '.join(bits)}{recency}")
        lines.append("")

    # EXPECTED OUTCOMES
    lines.append("**Expected outcome (63 trading days)**")
    lines.append(f"- Base case (median): **{a.expected_return_pct:+.1f}%** → "
                 f"target {_money(p.target_price)}")
    lines.append(f"- Bull case (75th pct): {a.bull_case_pct:+.1f}% → "
                 f"~{_money(p.entry_price * (1 + a.bull_case_pct/100))}")
    lines.append(f"- Bear case (25th pct): {a.bear_case_pct:+.1f}% → "
                 f"~{_money(p.entry_price * (1 + a.bear_case_pct/100))}")
    lines.append("")

    # RISK FLAGS
    if (r.earnings_within_blackout or r.low_liquidity
            or r.extended_above_200d or r.deeply_below_200d
            or r.other or r.sector_concentration_warning):
        lines.append("**Risk flags**")
        if r.earnings_within_blackout:
            lines.append(
                f"- ⚠️ **Earnings in {r.days_to_next_earnings} days** — "
                f"consider delaying entry until after the report"
            )
        elif r.days_to_next_earnings is not None and r.days_to_next_earnings <= 30:
            lines.append(
                f"- Earnings in {r.days_to_next_earnings} days "
                f"(outside blackout but worth tracking)"
            )
        if r.low_liquidity:
            lines.append("- ⚠️ Low liquidity (<$5M daily $ volume) — use limit orders")
        if r.extended_above_200d:
            lines.append("- ⚠️ Extended >30% above 200d SMA — pullback risk")
        if r.deeply_below_200d:
            lines.append("- ⚠️ More than -10% below 200d SMA — confirmed downtrend; honor stop")
        if r.sector_concentration_warning:
            lines.append(f"- ⚠️ {r.sector_concentration_warning}")
        for o in r.other:
            lines.append(f"- {o}")
        lines.append("")

    return "\n".join(lines)


def render_portfolio_summary(
    analyses: list[StockAnalysis],
    equity_usd: float,
    as_of: str,
) -> str:
    lines: list[str] = []
    lines.append(f"# Portfolio Analysis — {as_of}")
    lines.append("")
    lines.append(f"**Strategy:** `{STRATEGY_LABEL}` "
                 f"(composite m+q+v, top 5%, quarterly rebalance)")
    lines.append(f"**Portfolio equity:** {_money(equity_usd)} | "
                 f"**Positions:** {len(analyses)} equal-weight "
                 f"({100.0/max(1,len(analyses)):.1f}% each)")
    lines.append(f"**Next rebalance:** ~"
                 f"{analyses[0].plan.time_exit_date if analyses else '—'} "
                 f"({REBALANCE_TRADING_DAYS} trading days)")
    lines.append("")

    # Portfolio-level expected outcome
    avg_target = sum(a.plan.target_pct for a in analyses) / max(1, len(analyses))
    avg_stop = sum(a.plan.stop_loss_pct for a in analyses) / max(1, len(analyses))
    avg_rr = sum(a.plan.reward_to_risk for a in analyses) / max(1, len(analyses))
    portfolio_target_usd = sum(
        a.plan.position_size_usd * (1 + a.plan.target_pct / 100)
        for a in analyses
    )
    portfolio_target_pnl = portfolio_target_usd - sum(
        a.plan.position_size_usd for a in analyses
    )
    lines.append("## Portfolio-level expectations")
    lines.append("")
    lines.append(f"- Average position target return: **{avg_target:+.1f}%** "
                 f"over {REBALANCE_TRADING_DAYS} trading days")
    lines.append(f"- Average position stop: {avg_stop:+.1f}% "
                 f"(reward/risk ratio: {avg_rr:.2f}×)")
    lines.append(f"- Portfolio target equity at exit: {_money(portfolio_target_usd)} "
                 f"(P&L {_money(portfolio_target_pnl)})")
    lines.append("")
    lines.append("**Honest caveats:**")
    lines.append("- The +8% per-pick median is the strategy's BACKTESTED 63-day "
                 "median across two 2-year windows. Real-world drift is real.")
    lines.append("- Equal-weight allocation reduces single-name blow-up risk but "
                 "trails a market-cap SPY in megacap-led regimes.")
    lines.append("- Backtest avg cross-window alpha is +2.77%/yr vs SPY — not the "
                 "5-8% headline you might want, but defensible and walk-forward-clean.")
    lines.append("")

    # Sector breakdown
    sector_counts = Counter(
        a.fundamentals.sector or "Unknown" for a in analyses
    )
    lines.append("## Sector breakdown")
    lines.append("")
    lines.append("| Sector | Count | % of portfolio |")
    lines.append("|---|---|---|")
    n = len(analyses)
    for sec, cnt in sector_counts.most_common():
        pct = 100 * cnt / max(1, n)
        flag = " ⚠️" if pct > 30 else ""
        lines.append(f"| {sec} | {cnt} | {pct:.1f}%{flag} |")
    lines.append("")
    if any(pct > 30 for pct in (100*c/max(1,n) for c in sector_counts.values())):
        lines.append("⚠️ **Sector concentration warning.** One sector exceeds 30% "
                     "of the portfolio — single-sector drawdowns will hit "
                     "harder than the broad market.")
        lines.append("")

    # Risk flag summary
    earnings_blackout = [a.ticker for a in analyses
                        if a.risk_flags.earnings_within_blackout]
    upcoming_earnings = [
        (a.ticker, a.risk_flags.days_to_next_earnings)
        for a in analyses
        if a.risk_flags.days_to_next_earnings is not None
        and a.risk_flags.days_to_next_earnings <= 14
        and not a.risk_flags.earnings_within_blackout
    ]
    low_liq = [a.ticker for a in analyses if a.risk_flags.low_liquidity]
    extended = [a.ticker for a in analyses if a.risk_flags.extended_above_200d]
    declining = [a.ticker for a in analyses if a.risk_flags.deeply_below_200d]

    if earnings_blackout or upcoming_earnings or low_liq or extended or declining:
        lines.append("## Portfolio-wide risk summary")
        lines.append("")
        if earnings_blackout:
            lines.append(f"- ⚠️ **Earnings blackout** (≤5 days): "
                         f"{', '.join(earnings_blackout)}")
        if upcoming_earnings:
            ue = ', '.join(f"{t}({d}d)" for t, d in upcoming_earnings)
            lines.append(f"- Earnings within 14 days: {ue}")
        if low_liq:
            lines.append(f"- Low liquidity (<$5M/day): {', '.join(low_liq)}")
        if extended:
            lines.append(f"- >30% above 200d SMA (overbought): {', '.join(extended)}")
        if declining:
            lines.append(f"- <-10% below 200d SMA (downtrend): {', '.join(declining)}")
        lines.append("")

    return "\n".join(lines)


def render_full_report(
    analyses: list[StockAnalysis],
    equity_usd: float,
    as_of: str,
) -> str:
    parts = [render_portfolio_summary(analyses, equity_usd, as_of)]
    parts.append("---")
    parts.append("")
    parts.append("## Per-stock analysis")
    parts.append("")
    parts.append(
        "Each pick below has: factor breakdown that earned it the "
        "spot, technical setup, fundamentals from the latest EDGAR "
        "filing, a specific trading plan with entry/stop/target, "
        "and risk flags. Stops are sized off 20-day ATR (2.5×) so "
        "they breathe with the stock's normal volatility instead of "
        "tripping on noise."
    )
    parts.append("")
    for a in analyses:
        parts.append(render_one_stock(a))
        parts.append("---")
        parts.append("")
    return "\n".join(parts)
