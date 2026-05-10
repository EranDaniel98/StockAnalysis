"""
Self-contained HTML backtest report (Tier 5.3).

Renders matplotlib charts as embedded base64 PNGs inside a single Jinja2
template, so the result is a one-file HTML report you can email or check
into a notebook directory.
"""

import base64
import logging
from io import BytesIO
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # non-interactive backend
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _fig_to_b64(fig) -> str:
    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=100)
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


def _chart_equity(equity_curve) -> str:
    if not equity_curve:
        return ""
    fig, ax = plt.subplots(figsize=(10, 4))
    dates = pd.to_datetime([e["date"] for e in equity_curve])
    eq = [e["equity"] for e in equity_curve]
    ax.plot(dates, eq, color="navy", linewidth=1.5)
    ax.fill_between(dates, eq, alpha=0.1, color="navy")
    ax.set_title("Equity Curve")
    ax.set_ylabel("Equity ($)")
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate()
    return _fig_to_b64(fig)


def _chart_drawdown(equity_curve) -> str:
    if not equity_curve:
        return ""
    fig, ax = plt.subplots(figsize=(10, 3))
    dates = pd.to_datetime([e["date"] for e in equity_curve])
    eq = np.array([e["equity"] for e in equity_curve], dtype=float)
    peak = np.maximum.accumulate(eq)
    dd = (eq / peak - 1) * 100
    ax.fill_between(dates, dd, 0, color="darkred", alpha=0.5)
    ax.plot(dates, dd, color="darkred", linewidth=0.8)
    ax.set_title("Drawdown (% from running peak)")
    ax.set_ylabel("Drawdown %")
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate()
    return _fig_to_b64(fig)


def _chart_monthly_heatmap(monthly) -> str:
    if not monthly:
        return ""
    years = sorted(monthly.keys())
    matrix = np.full((len(years), 12), np.nan)
    for i, y in enumerate(years):
        for m, v in monthly[y].items():
            matrix[i, m - 1] = v
    if np.all(np.isnan(matrix)):
        return ""
    bound = max(abs(np.nanmin(matrix)), abs(np.nanmax(matrix)), 1.0)
    fig, ax = plt.subplots(figsize=(10, max(2.0, len(years) * 0.7)))
    im = ax.imshow(matrix, aspect="auto", cmap="RdYlGn", vmin=-bound, vmax=bound)
    ax.set_xticks(range(12))
    ax.set_xticklabels(["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])
    ax.set_yticks(range(len(years)))
    ax.set_yticklabels(years)
    for i in range(len(years)):
        for m in range(12):
            v = matrix[i, m]
            if not np.isnan(v):
                ax.text(m, i, f"{v:+.1f}",
                        ha="center", va="center",
                        color="black" if abs(v) < bound * 0.5 else "white",
                        fontsize=8)
    plt.colorbar(im, ax=ax, label="Return %")
    ax.set_title("Monthly Returns (%)")
    return _fig_to_b64(fig)


def _chart_calibration(calibration) -> str:
    populated = [c for c in calibration if c.get("n", 0) > 0]
    if not populated:
        return ""
    labels = [c["bucket"] for c in populated]
    avg_ret = [c["avg_return_pct"] for c in populated]
    counts = [c["n"] for c in populated]
    fig, ax1 = plt.subplots(figsize=(8, 4))
    colors = ["#2e7d32" if r > 0 else "#c62828" for r in avg_ret]
    bars = ax1.bar(labels, avg_ret, color=colors, alpha=0.85)
    ax1.axhline(0, color="black", lw=0.5)
    ax1.set_title("OOS Avg Return by Score Bucket")
    ax1.set_ylabel("Avg return %")
    ax1.grid(True, alpha=0.3, axis="y")
    for bar, count, ret in zip(bars, counts, avg_ret):
        h = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width() / 2, h,
                 f"n={count}\n{ret:+.2f}%",
                 ha="center", va="bottom" if h >= 0 else "top", fontsize=9)
    return _fig_to_b64(fig)


def _chart_mfe_mae(trades) -> str:
    if not trades:
        return ""
    mfes = [t.get("mfe_pct", 0) for t in trades]
    maes = [t.get("mae_pct", 0) for t in trades]
    pnls = [t.get("pnl_pct", 0) for t in trades]
    fig, ax = plt.subplots(figsize=(8, 6))
    colors = ["#2e7d32" if p > 0 else "#c62828" for p in pnls]
    ax.scatter(maes, mfes, c=colors, alpha=0.5, s=30)
    ax.axhline(0, color="black", lw=0.5)
    ax.axvline(0, color="black", lw=0.5)
    ax.set_xlabel("MAE % (max adverse excursion)")
    ax.set_ylabel("MFE % (max favorable excursion)")
    ax.set_title("MFE vs MAE per trade (green=winner, red=loser)")
    ax.grid(True, alpha=0.3)
    return _fig_to_b64(fig)


def _chart_r_distribution(r_dist) -> str:
    if not r_dist:
        return ""
    labels = list(r_dist.keys())
    counts = list(r_dist.values())
    if sum(counts) == 0:
        return ""
    palette = {"<-2R": "#b71c1c", "-2 to -1R": "#ef5350",
               "-1 to 0R": "#ffa726", "0 to 1R": "#aed581",
               "1 to 2R": "#66bb6a", "2 to 3R": "#43a047", ">=3R": "#1b5e20"}
    colors = [palette.get(l, "#888") for l in labels]
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(labels, counts, color=colors)
    ax.set_title("R-Multiple Distribution")
    ax.set_ylabel("Trade count")
    plt.xticks(rotation=30, ha="right")
    return _fig_to_b64(fig)


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Backtest Report — {{ strategy }}</title>
<style>
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
       max-width: 1100px; margin: 2rem auto; padding: 0 1rem; color: #2c3e50;
       line-height: 1.5; }
h1 { color: #1a3a52; border-bottom: 2px solid #1a3a52; padding-bottom: 0.5rem; }
h2 { color: #1a3a52; border-bottom: 1px solid #ccc; padding-bottom: 0.3rem;
     margin-top: 2rem; }
.summary { background: #f5f7fa; padding: 1rem 1.2rem; border-radius: 6px;
           border-left: 4px solid #1a3a52; }
.metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
           gap: 0.8rem; margin: 1rem 0; }
.metric { padding: 0.7rem; background: white; border: 1px solid #e0e0e0;
          border-radius: 4px; }
.metric-label { font-size: 0.78rem; color: #666; text-transform: uppercase;
                letter-spacing: 0.04em; }
.metric-value { font-size: 1.4rem; font-weight: 600; }
.positive { color: #2e7d32; }
.negative { color: #c62828; }
img { max-width: 100%; display: block; margin: 1rem 0;
      border: 1px solid #ddd; border-radius: 4px; }
.recommendation { background: #e8f5e9; border-left: 4px solid #2e7d32;
                  padding: 1rem 1.2rem; border-radius: 4px; }
.verdict { background: #fffde7; border-left: 4px solid #f9a825;
           padding: 1rem 1.2rem; border-radius: 4px; font-family: monospace; }
.warn { background: #fff3e0; border-left: 4px solid #fb8c00;
        padding: 0.7rem 1rem; border-radius: 4px; margin: 0.5rem 0;
        font-size: 0.9rem; }
.muted { color: #888; font-size: 0.85rem; margin-top: 2rem;
         text-align: center; }
</style>
</head>
<body>

<h1>Backtest Report</h1>

<div class="summary">
  <strong>Strategy:</strong> {{ strategy }}<br>
  <strong>Universe:</strong> {{ universe }}<br>
  <strong>Window:</strong> {{ window }}<br>
  <strong>OOS split at:</strong> {{ split_date }}
</div>

<h2>Headline</h2>
<div class="metrics">
  <div class="metric"><div class="metric-label">Full Return</div>
    <div class="metric-value {{ full_class }}">{{ full_return }}</div></div>
  <div class="metric"><div class="metric-label">OOS Return</div>
    <div class="metric-value {{ oos_class }}">{{ oos_return }}</div></div>
  <div class="metric"><div class="metric-label">OOS Sharpe</div>
    <div class="metric-value">{{ oos_sharpe }}</div></div>
  <div class="metric"><div class="metric-label">Max Drawdown</div>
    <div class="metric-value negative">{{ max_dd }}</div></div>
  <div class="metric"><div class="metric-label">Win Rate</div>
    <div class="metric-value">{{ win_rate }}</div></div>
  <div class="metric"><div class="metric-label">Trades</div>
    <div class="metric-value">{{ trades }}</div></div>
  <div class="metric"><div class="metric-label">Alpha vs SPY (matched)</div>
    <div class="metric-value {{ alpha_class }}">{{ alpha }}</div></div>
  <div class="metric"><div class="metric-label">Time Underwater</div>
    <div class="metric-value">{{ time_underwater }}</div></div>
</div>

{% if equity_chart %}<h2>Equity Curve</h2>
<img src="data:image/png;base64,{{ equity_chart }}">{% endif %}

{% if dd_chart %}<h2>Drawdown</h2>
<img src="data:image/png;base64,{{ dd_chart }}">{% endif %}

{% if monthly_chart %}<h2>Monthly Returns</h2>
<img src="data:image/png;base64,{{ monthly_chart }}">{% endif %}

{% if calibration_chart %}<h2>OOS Score-Bucket Calibration</h2>
<img src="data:image/png;base64,{{ calibration_chart }}">{% endif %}

{% if mfe_mae_chart %}<h2>MFE vs MAE</h2>
<img src="data:image/png;base64,{{ mfe_mae_chart }}">
<p class="muted">Each dot is one trade. Greens are winners, reds are losers.
The vertical spread shows how much price moved in your favor before exit;
horizontal spread shows how deep underwater each trade went.</p>{% endif %}

{% if r_chart %}<h2>R-Multiple Distribution</h2>
<img src="data:image/png;base64,{{ r_chart }}">{% endif %}

<h2>Verdict (OOS)</h2>
<div class="verdict">{{ verdict }}</div>

{% if recommendation %}
<h2>Live-Trader Recommendation</h2>
<div class="recommendation">
  Suggested live <code>min_score</code>:
  <strong>{{ recommendation.min_score }}</strong><br>
  Based on OOS bucket <strong>{{ recommendation.bucket }}</strong>:
  n={{ recommendation.n_trades }},
  win rate {{ "%.1f"|format(recommendation.win_rate_pct) }}%,
  avg return {{ "%+.2f"|format(recommendation.avg_return_pct) }}%.
</div>
{% endif %}

{% if warnings %}<h2>Warnings</h2>
{% for w in warnings %}<div class="warn">{{ w }}</div>{% endfor %}{% endif %}

<p class="muted">Generated by stock-scanner backtest harness</p>
</body>
</html>
"""


def render_html_report(result: dict, strategy_name: str, universe_label: str,
                        output_path: str) -> Path:
    """Render the backtest result as a self-contained HTML file. Returns the path."""
    from jinja2 import Template

    full = result["full"]["summary"]
    oos = result["out_of_sample"]["summary"]
    full_eq = result["full"]["equity_stats"]
    oos_eq = result["out_of_sample"]["equity_stats"]

    template = Template(HTML_TEMPLATE)
    rendered = template.render(
        strategy=strategy_name,
        universe=universe_label,
        window=f"{full['start_date']} to {full['end_date']}",
        split_date=result.get("split_date", "?"),
        full_return=f"{full['total_return_pct']:+.2f}%",
        full_class="positive" if full["total_return_pct"] > 0 else "negative",
        oos_return=f"{oos['total_return_pct']:+.2f}%",
        oos_class="positive" if oos["total_return_pct"] > 0 else "negative",
        oos_sharpe=f"{oos_eq['ann_sharpe']:+.2f}",
        max_dd=f"{full_eq['max_drawdown_pct']:.2f}%",
        win_rate=f"{full['win_rate_pct']:.1f}%",
        trades=full["n_trades"],
        alpha=f"{full.get('alpha_vs_spy_matched_pct', 0):+.2f}%",
        alpha_class="positive" if full.get("alpha_vs_spy_matched_pct", 0) > 0 else "negative",
        time_underwater=f"{full_eq['time_in_dd_pct']:.0f}%",
        equity_chart=_chart_equity(result.get("equity_curve", [])),
        dd_chart=_chart_drawdown(result.get("equity_curve", [])),
        monthly_chart=_chart_monthly_heatmap(result.get("monthly_returns", {})),
        calibration_chart=_chart_calibration(result["out_of_sample"]["calibration"]),
        mfe_mae_chart=_chart_mfe_mae(result.get("trades", [])),
        r_chart=_chart_r_distribution(result.get("excursion", {}).get("r_distribution", {})),
        verdict=result.get("verdict_oos", ""),
        recommendation=result.get("live_recommendation"),
        warnings=result.get("warnings", []),
    )

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(rendered)
    return out
