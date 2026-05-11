"""
Alphalens IC diagnostic.

Runs the full scoring engine over a universe + window, builds a (date, ticker)
score panel, computes forward returns from the same price data, and feeds the
panel through alphalens-reloaded to get:

  - Information Coefficient (IC) per forward-return horizon
  - IC time-series (is the signal stable or fading?)
  - Quantile-bucket cumulative returns
  - Turnover diagnostics

IC > 0.03 is the rough bar for "real signal" in cross-sectional equity factors
(Grinold's law of active management: IC * sqrt(breadth) = IR).

This is THE gate diagnostic. Run it before any further capital commitment.
"""

import logging
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import numpy as np
import pandas as pd
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

logger = logging.getLogger(__name__)


def build_score_panel(
    price_data: dict[str, pd.DataFrame],
    fundamentals: dict[str, dict],
    earnings_history: dict[str, pd.DataFrame],
    config,
    strategy: dict,
    start: pd.Timestamp,
    end: pd.Timestamp,
    rebalance_weekday: int = 0,
    workers: int = 8,
    min_history_bars: int = 260,
) -> pd.DataFrame:
    """
    Run the scoring engine at every rebalance date across the window.

    Returns a long-form DataFrame:
        columns: [date, ticker, composite_score, technical, fundamental, ...]
    Suitable for pivoting into alphalens' (date, asset) -> factor format.
    """
    from src.backtest.engine import _score_ticker, _normalize_index

    price_data = {t: _normalize_index(df) for t, df in price_data.items() if df is not None and not df.empty}
    if not price_data:
        return pd.DataFrame()

    start = pd.Timestamp(start)
    if start.tz is not None:
        start = start.tz_localize(None)
    end = pd.Timestamp(end)
    if end.tz is not None:
        end = end.tz_localize(None)

    schedule = pd.date_range(start=start, end=end, freq=f"W-{['MON','TUE','WED','THU','FRI'][rebalance_weekday]}").tolist()
    if not schedule:
        return pd.DataFrame()

    rows: list[dict] = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold]Panel build[/bold]"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("{task.fields[when]}"),
        transient=True,
    ) as progress:
        task = progress.add_task("scoring", total=len(schedule), when="")
        for as_of in schedule:
            progress.update(task, when=as_of.strftime("%Y-%m-%d"))
            scored_for_day: dict[str, dict] = {}
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futures = {}
                for ticker, df in price_data.items():
                    df_slice = df.loc[df.index < as_of]
                    if len(df_slice) < min_history_bars:
                        continue
                    fund = fundamentals.get(ticker, {}) or {}
                    eh = earnings_history.get(ticker)
                    futures[ex.submit(
                        _score_ticker, ticker, df_slice, fund, config, strategy, eh, as_of,
                    )] = ticker
                for fut in as_completed(futures):
                    ticker = futures[fut]
                    try:
                        r = fut.result()
                    except Exception:
                        r = None
                    if r is not None and "composite_score" in r:
                        scored_for_day[ticker] = r
            for ticker, r in scored_for_day.items():
                row = {
                    "date": as_of,
                    "ticker": ticker,
                    "composite": r["composite_score"],
                }
                row.update(r.get("sub_scores", {}))
                rows.append(row)
            progress.advance(task)

    return pd.DataFrame(rows)


def build_price_matrix(
    price_data: dict[str, pd.DataFrame],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    """
    Build a wide DataFrame of daily Close prices indexed by date, columns=tickers.
    Alphalens needs this for forward-return computation.
    """
    from src.backtest.engine import _normalize_index
    closes = {}
    for ticker, df in price_data.items():
        if df is None or df.empty:
            continue
        df = _normalize_index(df)
        closes[ticker] = df["Close"]
    if not closes:
        return pd.DataFrame()
    prices = pd.concat(closes, axis=1).sort_index()
    return prices.loc[start:end]


def run_alphalens(
    panel: pd.DataFrame,
    prices: pd.DataFrame,
    factor_column: str = "composite",
    periods: tuple = (1, 5, 21),
    quantiles: int = 5,
) -> dict:
    """
    Feed the panel into alphalens.utils.get_clean_factor_and_forward_returns,
    then compute IC + quantile spread.

    Returns dict with:
      ic_mean: dict {period: float}
      ic_std: dict {period: float}
      ic_ir: dict {period: float}  (information ratio = IC mean / IC std)
      quantile_returns: DataFrame
      top_minus_bottom_mean_pct: dict {period: float}
      n_observations: int
    """
    import alphalens as al
    _patch_alphalens_freq()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        factor = _build_factor_series(panel, factor_column, align_to_index=prices.index)
        clean = al.utils.get_clean_factor_and_forward_returns(
            factor=factor,
            prices=prices,
            quantiles=quantiles,
            periods=periods,
            max_loss=0.5,  # allow up to 50% dropped if forward returns missing
        )

        # IC per period
        ic = al.performance.factor_information_coefficient(clean)
        ic_mean = {f"{p}D": float(ic[f"{p}D"].mean()) for p in periods if f"{p}D" in ic.columns}
        ic_std = {f"{p}D": float(ic[f"{p}D"].std()) for p in periods if f"{p}D" in ic.columns}
        ic_ir = {k: (ic_mean[k] / ic_std[k] if ic_std[k] > 0 else 0.0) for k in ic_mean}

        # Quantile returns
        qr_mean, qr_std = al.performance.mean_return_by_quantile(clean)
        # Top-minus-bottom spread per period (top quantile = highest factor)
        top_minus_bottom = {}
        for p in periods:
            col = f"{p}D"
            if col in qr_mean.columns:
                top = qr_mean[col].iloc[-1]  # highest quantile
                bot = qr_mean[col].iloc[0]   # lowest quantile
                # Returns are in decimal form; convert to %
                top_minus_bottom[col] = float((top - bot) * 100)

        return {
            "ic_mean": ic_mean,
            "ic_std": ic_std,
            "ic_ir": ic_ir,
            "quantile_returns_pct": (qr_mean * 100).round(3).to_dict(),
            "top_minus_bottom_pct": top_minus_bottom,
            "n_observations": int(len(clean)),
            "periods": list(periods),
            "quantiles": quantiles,
        }


def render_html_report(
    panel: pd.DataFrame,
    prices: pd.DataFrame,
    output_path: str,
    factor_column: str = "composite",
    periods: tuple = (1, 5, 21),
    quantiles: int = 5,
) -> str:
    """Write a full alphalens tearsheet to HTML (matplotlib-rendered)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import alphalens as al
    from pathlib import Path
    import base64
    from io import BytesIO

    _patch_alphalens_freq()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        factor = _build_factor_series(panel, factor_column, align_to_index=prices.index)
        clean = al.utils.get_clean_factor_and_forward_returns(
            factor=factor, prices=prices, quantiles=quantiles, periods=periods,
            max_loss=0.5,
        )
        # Render full tear sheet to figures, capture as PNGs
        figs_b64: list[str] = []

        # IC plot
        ic = al.performance.factor_information_coefficient(clean)
        fig1, ax = plt.subplots(figsize=(10, 4))
        for col in ic.columns:
            ic[col].rolling(21).mean().plot(ax=ax, label=f"{col} (21d rolling mean)")
        ax.axhline(0, color="black", lw=0.5)
        ax.legend()
        ax.set_title(f"Information Coefficient over time ({factor_column})")
        ax.grid(True, alpha=0.3)
        figs_b64.append(_fig_to_b64(fig1))

        # Quantile returns
        qr_mean, _ = al.performance.mean_return_by_quantile(clean)
        fig2, ax = plt.subplots(figsize=(10, 4))
        (qr_mean * 100).plot(kind="bar", ax=ax)
        ax.set_title("Mean Forward Return by Quantile (%)")
        ax.set_xlabel("Quantile")
        ax.set_ylabel("Mean return %")
        ax.axhline(0, color="black", lw=0.5)
        ax.grid(True, alpha=0.3, axis="y")
        figs_b64.append(_fig_to_b64(fig2))

        # Cumulative top-minus-bottom
        # Reconstruct from quantile equity curves via mean returns
        period = f"{periods[0]}D"
        try:
            cum_returns_by_q = al.performance.cumulative_returns_by_quantile(
                clean, period=period, freq=pd.tseries.offsets.BDay()
            )
            fig3, ax = plt.subplots(figsize=(10, 4))
            (cum_returns_by_q * 100).plot(ax=ax)
            ax.set_title(f"Cumulative Returns by Quantile ({period})")
            ax.set_ylabel("Cumulative return %")
            ax.grid(True, alpha=0.3)
            figs_b64.append(_fig_to_b64(fig3))
        except Exception as e:
            logger.debug(f"Cumulative plot failed: {e}")

        # Stats summary
        stats = run_alphalens(panel, prices, factor_column=factor_column, periods=periods, quantiles=quantiles)

    html = ["<!DOCTYPE html><html><head><meta charset='utf-8'>",
            "<title>Alphalens IC Diagnostic</title>",
            "<style>body{font-family:sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;}"
            "table{border-collapse:collapse;margin:1rem 0;}"
            "td,th{border:1px solid #ddd;padding:0.4rem 0.6rem;}"
            "th{background:#f0f0f0;}img{max-width:100%;margin:1rem 0;border:1px solid #ddd;}</style>",
            "</head><body>",
            f"<h1>Alphalens IC Diagnostic — factor: {factor_column}</h1>",
            f"<p>Observations: {stats['n_observations']:,} | Quantiles: {stats['quantiles']} | Periods: {stats['periods']}</p>",
            "<h2>Information Coefficient</h2><table><tr><th>Horizon</th><th>IC mean</th><th>IC std</th><th>IC IR</th></tr>"]
    for h in stats["ic_mean"]:
        html.append(f"<tr><td>{h}</td><td>{stats['ic_mean'][h]:+.4f}</td>"
                    f"<td>{stats['ic_std'][h]:.4f}</td><td>{stats['ic_ir'][h]:+.3f}</td></tr>")
    html.append("</table>")
    html.append("<h2>Top-Minus-Bottom Quantile Spread</h2><table><tr><th>Horizon</th><th>Spread (%)</th></tr>")
    for h, v in stats["top_minus_bottom_pct"].items():
        html.append(f"<tr><td>{h}</td><td>{v:+.3f}%</td></tr>")
    html.append("</table>")
    for b64 in figs_b64:
        html.append(f"<img src='data:image/png;base64,{b64}'>")
    # Verdict
    best_ic = max(stats["ic_mean"].values()) if stats["ic_mean"] else 0
    if best_ic > 0.05:
        verdict = "STRONG signal (IC > 0.05). Worth scaling capital."
        color = "green"
    elif best_ic > 0.03:
        verdict = "MODEST signal (IC 0.03-0.05). Edge exists; needs care."
        color = "orange"
    elif best_ic > 0.01:
        verdict = "WEAK signal (IC 0.01-0.03). Probably not exploitable after costs."
        color = "red"
    else:
        verdict = "NO signal (IC < 0.01). Composite score is noise; redesign."
        color = "red"
    html.append(f"<h2 style='color:{color}'>Verdict: {verdict}</h2></body></html>")

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(html), encoding="utf-8")
    return str(out)


def _build_factor_series(
    panel: pd.DataFrame,
    factor_column: str,
    align_to_index: Optional[pd.Index] = None,
) -> pd.Series:
    """
    Build the factor MultiIndex Series for alphalens. Forward-fills weekly
    factor values across the price index so dates match the price matrix
    exactly (yfinance skips market holidays, so pd.bdate_range is wrong).
    """
    df = panel[["date", "ticker", factor_column]].copy()
    df["date"] = pd.to_datetime(df["date"])
    if df["date"].dt.tz is not None:
        df["date"] = df["date"].dt.tz_localize(None)

    wide = df.pivot(index="date", columns="ticker", values=factor_column)
    wide = wide.sort_index()

    if align_to_index is not None:
        target = pd.DatetimeIndex(align_to_index)
        if target.tz is not None:
            target = target.tz_localize(None)
        combined = wide.index.union(target).sort_values()
        wide = wide.reindex(combined).ffill(limit=6).reindex(target)
    else:
        business_days = pd.bdate_range(wide.index.min(), wide.index.max())
        wide = wide.reindex(business_days).ffill(limit=6)

    series = wide.stack(dropna=True)
    series.index.names = ["date", "asset"]
    series.name = "factor"
    return series.astype(float)


_ALPHALENS_PATCHED = False


def _patch_alphalens_freq() -> None:
    """
    Replace alphalens-reloaded's `compute_forward_returns` with a calendar-
    tolerant version. Two upstream bugs need fixing:

      1. `infer_trading_calendar` builds a `CustomBusinessDay` from observed
         dates that doesn't perfectly conform to real equity calendars
         (DST, half-days, missed holidays).
      2. `df.index.levels[0].freq = freq` then validates this offset and
         raises `ValueError` on any mismatch.

    The freq is only used to label columns (`'1D'`, `'5D'`, etc.). We force a
    plain `BDay()` calendar — labels stay correct, validator passes.
    """
    global _ALPHALENS_PATCHED
    if _ALPHALENS_PATCHED:
        return

    import alphalens.utils as al_utils
    from scipy.stats import mode
    from alphalens.utils import (
        NonMatchingTimezoneError,
        diff_custom_calendar_timedeltas,
        timedelta_to_string,
    )

    bday = pd.tseries.offsets.BDay()
    al_utils.infer_trading_calendar = lambda *_args, **_kw: bday

    def _safe_compute_forward_returns(
        factor, prices, periods=(1, 5, 10), filter_zscore=None, cumulative_returns=True
    ):
        factor_dateindex = factor.index.levels[0]
        if factor_dateindex.tz != prices.index.tz:
            raise NonMatchingTimezoneError(
                "Factor and prices timezone mismatch."
            )
        freq = factor_dateindex.freq or bday
        factor_dateindex = factor_dateindex.intersection(prices.index)
        if len(factor_dateindex) == 0:
            raise ValueError(
                "Factor and prices indices don't match: make sure they have "
                "the same convention in terms of datetimes and symbol-names"
            )

        prices = prices.filter(items=factor.index.levels[1])
        raw_values_dict = {}
        column_list = []

        for period in sorted(periods):
            returns = prices.pct_change(period) if cumulative_returns else prices.pct_change()
            forward_returns = returns.shift(-period).reindex(factor_dateindex)

            if filter_zscore is not None:
                mask = abs(forward_returns - forward_returns.mean()) > (
                    filter_zscore * forward_returns.std()
                )
                forward_returns[mask] = np.nan

            days_diffs = []
            period_len = None
            for i in range(30):
                if i >= len(forward_returns.index):
                    break
                p_idx = prices.index.get_loc(forward_returns.index[i])
                if p_idx is None or p_idx < 0 or (p_idx + period) >= len(prices.index):
                    continue
                start = prices.index[p_idx]
                end = prices.index[p_idx + period]
                period_len = diff_custom_calendar_timedeltas(start, end, freq)
                days_diffs.append(period_len.components.days)

            if period_len is None or not days_diffs:
                label = f"{period}D"
            else:
                delta_days = (
                    period_len.components.days - mode(days_diffs, keepdims=True).mode[0]
                )
                period_len -= pd.Timedelta(days=delta_days)
                label = timedelta_to_string(period_len)

            column_list.append(label)
            raw_values_dict[label] = np.concatenate(forward_returns.values)

        df = pd.DataFrame.from_dict(raw_values_dict)
        df.set_index(
            pd.MultiIndex.from_product(
                [factor_dateindex, prices.columns], names=["date", "asset"]
            ),
            inplace=True,
        )
        df = df.reindex(factor.index)
        df = df[column_list]
        df.index.set_names(["date", "asset"], inplace=True)
        return df

    al_utils.compute_forward_returns = _safe_compute_forward_returns
    _ALPHALENS_PATCHED = True


def _fig_to_b64(fig) -> str:
    import base64
    from io import BytesIO
    import matplotlib.pyplot as plt
    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=100)
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")
