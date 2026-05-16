"""Strategy comparison harness: run N strategies against the SAME
frozen snapshot, render a comparison report.

The keystone audit step. Until this lands the audit chain couldn't
cleanly tell which numbers were noise and which were strategy
differences — yfinance drift swamped the signal
(project_yfinance_nondeterminism). With a frozen snapshot, the ONLY
difference between two runs is the strategy's weights/thresholds.

Output: a markdown comparison report and a JSON twin that downstream
tooling can chart.

What's compared per strategy
----------------------------
  * OOS Sharpe + bootstrap 95% CI
  * Full-window Sharpe + total return
  * Alpha vs SPY (matched-deployment, OOS)
  * Alpha vs equal-weight universe (computed from the snapshot)
  * Max drawdown OOS
  * Trade count + win rate + avg hold + turnover
  * Top-5-trades-removed Sharpe drop
  * Walk-forward fold-by-fold Sharpe + return
  * Yearly breakdown of trade returns

Equal-weight benchmark
----------------------
Computed in-process from snapshot prices. The benchmark is "buy every
ticker in the snapshot's universe at window start in equal weight,
hold to window end, no rebalance" — a passive baseline. Real
implementations would rebalance monthly; the static version is the
defensible lower bound.

Usage
-----
    uv run python -m scripts.compare_strategies \\
        --snapshot-id <id> \\
        --strategies minimal_baseline,minimal_baseline_v2,minimal_baseline_v3 \\
        --years 2 \\
        --output reports/strategy_comparison_2022_2024.md
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


logger = logging.getLogger("compare_strategies")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Compare strategies on frozen snapshot data.",
    )
    p.add_argument("--snapshot-id", required=True)
    p.add_argument(
        "--strategies", required=True,
        help="Comma-separated strategy names from config/strategies.yaml. "
             "Example: minimal_baseline,minimal_baseline_v2,minimal_baseline_v3",
    )
    p.add_argument("--years", type=float, default=2.0)
    p.add_argument("--starting-cash", type=float, default=10_000.0)
    p.add_argument(
        "--pit-fundamentals", action="store_true",
        help="Pass --pit-fundamentals to each child run.",
    )
    p.add_argument(
        "--regime-mode", default="off",
        choices=("off", "skip_bear", "skip_bear_and_chop"),
    )
    p.add_argument(
        "--end-date",
        help="ISO end date for the backtest window. Defaults to the "
             "snapshot's window_end.",
    )
    p.add_argument("--output", required=True,
                   help="Markdown report path.")
    p.add_argument(
        "--results-dir", default="data/baseline",
        help="Where per-strategy result JSONs are written.",
    )
    p.add_argument(
        "--skip-run", action="store_true",
        help="Skip running the strategies; just read existing result "
             "JSONs from --results-dir matching the snapshot-id.",
    )
    p.add_argument(
        "--include-trades", action="store_true",
        help="Ask each child run to embed its raw trades list in the "
             "slim JSON. Required for post-hoc sector / hold-time / "
             "bubble-period analyses.",
    )
    return p.parse_args()


def _run_strategy(
    strategy: str, snapshot_id: str, years: float, starting_cash: float,
    pit_fundamentals: bool, regime_mode: str, end_date: Optional[str],
    results_dir: Path, include_trades: bool = False,
) -> Path:
    out = results_dir / f"compare_{strategy}_{snapshot_id}.json"
    err = out.with_suffix(".err")
    cmd = [
        "uv", "run", "python", "-m", "scripts.run_minimal_baseline",
        "--snapshot-id", snapshot_id,
        "--strategy", strategy,
        "--years", str(years),
        "--starting-cash", str(starting_cash),
        "--regime-mode", regime_mode,
        "--output", str(out),
    ]
    if pit_fundamentals:
        cmd.append("--pit-fundamentals")
    if end_date:
        cmd.extend(["--end-date", end_date])
    if include_trades:
        cmd.append("--include-trades")
    logger.info("Running %s -> %s ...", strategy, out)
    with err.open("wb") as ef:
        rc = subprocess.call(cmd, stdout=ef, stderr=subprocess.STDOUT)
    if rc != 0:
        raise RuntimeError(
            f"strategy {strategy} failed with rc={rc}; see {err}"
        )
    return out


def _equal_weight_benchmark(
    snapshot_id: str, start: pd.Timestamp, end: pd.Timestamp,
) -> dict:
    """Buy-every-ticker-in-equal-weight passive benchmark.

    Read the snapshot's price file, build an equity curve assuming
    we put 1/N into each ticker at `start` and hold to `end`. Returns
    total return %, annualized Sharpe (weekly resampled).
    """
    from src.storage.snapshot import load_snapshot
    snap = load_snapshot(snapshot_id)
    if not snap.price_data:
        return {"error": "snapshot has no prices"}

    closes: dict[str, pd.Series] = {}
    for t, df in snap.price_data.items():
        if df is None or df.empty or "Close" not in df.columns:
            continue
        s = df["Close"].sort_index()
        # Window slice
        s = s.loc[(s.index >= start) & (s.index <= end)]
        if len(s) < 2:
            continue
        closes[t] = s

    if not closes:
        return {"error": "no usable tickers in window"}

    wide = pd.concat(closes, axis=1).sort_index().ffill().dropna(how="all")
    # Normalize each ticker to start at 1.0
    first = wide.iloc[0].copy()
    first[first == 0] = np.nan
    normalized = wide.divide(first, axis=1).dropna(axis=1, how="any")
    if normalized.empty:
        return {"error": "all tickers normalized away"}
    eq_curve = normalized.mean(axis=1)
    total_return_pct = float((eq_curve.iloc[-1] / eq_curve.iloc[0] - 1.0) * 100)
    weekly = eq_curve.resample("W").last().dropna()
    weekly_returns = weekly.pct_change().dropna()
    if len(weekly_returns) < 3 or weekly_returns.std() == 0:
        ann_sharpe = None
    else:
        days_elapsed = (eq_curve.index[-1] - eq_curve.index[0]).days or 1
        years_elapsed = days_elapsed / 365.25
        periods_per_year = (
            len(weekly_returns) / years_elapsed
            if years_elapsed > 0 else 52.0
        )
        ann_sharpe = float(
            (weekly_returns.mean() / weekly_returns.std(ddof=1))
            * np.sqrt(periods_per_year)
        )
    return {
        "n_tickers": int(normalized.shape[1]),
        "total_return_pct": round(total_return_pct, 2),
        "ann_sharpe": round(ann_sharpe, 2) if ann_sharpe is not None else None,
        "window_start": str(start.date()),
        "window_end": str(end.date()),
    }


def _yearly_breakdown(result: dict) -> list[dict]:
    """Group trades by exit year and tally count + return."""
    trades = result.get("trades") or []
    # When the slim writer dropped trades (older runs) — try the
    # "full.trades" or "out_of_sample.trades" path if present.
    if not trades:
        for path in (("full", "trades"), ("out_of_sample", "trades")):
            cur = result
            for k in path:
                cur = (cur or {}).get(k) if isinstance(cur, dict) else None
            if isinstance(cur, list) and cur:
                trades = cur
                break
    by_year: dict[int, dict] = {}
    for t in trades:
        ed = t.get("exit_date") or t.get("entry_date")
        if not ed:
            continue
        year = pd.Timestamp(ed).year
        b = by_year.setdefault(
            year, {"year": year, "n_trades": 0, "total_pnl": 0.0,
                   "wins": 0, "losses": 0, "sum_return_pct": 0.0},
        )
        b["n_trades"] += 1
        b["total_pnl"] += float(t.get("pnl") or 0.0)
        b["sum_return_pct"] += float(t.get("pnl_pct") or 0.0)
        if (t.get("pnl") or 0.0) > 0:
            b["wins"] += 1
        else:
            b["losses"] += 1
    out = []
    for year in sorted(by_year.keys()):
        b = by_year[year]
        out.append({
            "year": b["year"],
            "n_trades": b["n_trades"],
            "total_pnl": round(b["total_pnl"], 2),
            "win_rate_pct": round(
                (b["wins"] / b["n_trades"] * 100) if b["n_trades"] else 0, 1,
            ),
            "avg_return_pct": round(
                (b["sum_return_pct"] / b["n_trades"]) if b["n_trades"] else 0, 2,
            ),
        })
    return out


def _pull(result: dict, *keys, default=None):
    cur = result
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


def _strategy_summary(result: dict) -> dict:
    return {
        "strategy": result.get("strategy"),
        "snapshot_id": result.get("snapshot_id"),
        "git_sha": result.get("git_sha"),
        "regime_mode": result.get("regime_mode"),
        "window": result.get("window"),
        "full": {
            "n_trades": _pull(result, "full", "summary", "n_trades"),
            "total_return_pct": _pull(result, "full", "summary", "total_return_pct"),
            "alpha_vs_spy_matched_pct": _pull(result, "full", "summary", "alpha_vs_spy_matched_pct"),
            "spy_return_pct": _pull(result, "full", "summary", "spy_return_pct"),
            "ann_sharpe": _pull(result, "full", "equity_stats", "ann_sharpe"),
            "max_drawdown_pct": _pull(result, "full", "equity_stats", "max_drawdown_pct"),
            "win_rate_pct": _pull(result, "full", "summary", "win_rate_pct"),
            "avg_hold_days": _pull(result, "full", "summary", "avg_hold_days"),
        },
        "oos": {
            "n_trades": _pull(result, "out_of_sample", "summary", "n_trades"),
            "total_return_pct": _pull(result, "out_of_sample", "summary", "total_return_pct"),
            "alpha_vs_spy_matched_pct": _pull(result, "out_of_sample", "summary", "alpha_vs_spy_matched_pct"),
            "ann_sharpe": _pull(result, "out_of_sample", "equity_stats", "ann_sharpe"),
            "max_drawdown_pct": _pull(result, "out_of_sample", "equity_stats", "max_drawdown_pct"),
            "win_rate_pct": _pull(result, "out_of_sample", "summary", "win_rate_pct"),
        },
        "walk_forward": {
            "mean_sharpe": _pull(result, "walk_forward", "mean_sharpe"),
            "min_sharpe": _pull(result, "walk_forward", "min_sharpe"),
            "max_sharpe": _pull(result, "walk_forward", "max_sharpe"),
            "passes_gate": _pull(result, "walk_forward", "passes_min_fold_gate"),
            "folds": [
                {
                    "i": f.get("fold_index"),
                    "n_trades": f.get("n_trades"),
                    "ann_sharpe": f.get("ann_sharpe"),
                    "total_return_pct": f.get("total_return_pct"),
                    "max_drawdown_pct": f.get("max_drawdown_pct"),
                }
                for f in (_pull(result, "walk_forward", "folds") or [])
            ],
        },
        "bootstrap": {
            "label": result.get("bootstrap_label"),
            "ann_sharpe_ci": _pull(result, "bootstrap", "ann_sharpe_ci"),
        },
        "concentration": {
            "applicable": _pull(result, "concentration_sensitivity", "applicable"),
            "pct": _pull(result, "concentration_sensitivity", "concentration_pct"),
            "headline_sharpe": _pull(result, "concentration_sensitivity", "headline_ann_sharpe"),
            "stripped_sharpe": _pull(result, "concentration_sensitivity", "stripped_ann_sharpe"),
            "sharpe_drop": _pull(result, "concentration_sensitivity", "sharpe_drop"),
        },
        "regimes_trade_buckets": result.get("regimes"),
        "yearly": _yearly_breakdown(result),
        "data_quality": result.get("data_quality"),
    }


def _fmt_num(v, kind: str = "f") -> str:
    if v is None:
        return "n/a"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if kind == "pct":
        return f"{f:+.2f}%"
    if kind == "sharpe":
        return f"{f:+.2f}"
    if kind == "int":
        return str(int(f))
    return f"{f:.2f}"


def _fmt_ci(ci) -> str:
    if not ci or not isinstance(ci, (list, tuple)) or len(ci) != 2:
        return "n/a"
    return f"[{ci[0]:.2f}, {ci[1]:.2f}]"


def _render_markdown(
    *,
    summaries: list[dict],
    eq_weight: dict,
    snapshot_id: str,
    window_start: pd.Timestamp,
    window_end: pd.Timestamp,
    universe: str,
    ran_at: str,
    git_sha: Optional[str],
) -> str:
    lines: list[str] = [
        f"# Strategy Comparison — Frozen Snapshot {snapshot_id}",
        "",
        f"Generated {ran_at}.",
        "",
        f"- Snapshot: `{snapshot_id}`",
        f"- Universe: `{universe}`",
        f"- Window: {window_start.date()} → {window_end.date()}",
        f"- Code revision: `{git_sha}`" if git_sha else "",
        "",
        "All strategies below ran against the SAME frozen Parquet "
        "snapshot. Any difference in metrics is attributable to the "
        "strategy's weights/thresholds, NOT to data drift "
        "(`project_yfinance_nondeterminism` is mitigated by the freeze).",
        "",
        "## Headline OOS metrics",
        "",
        "| Strategy | OOS Sharpe | OOS Sharpe CI | OOS α vs SPY | OOS Max DD | OOS trades | OOS win rate |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in summaries:
        ci_label = s["bootstrap"].get("label") or "?"
        ci = s["bootstrap"].get("ann_sharpe_ci")
        lines.append(
            f"| {s['strategy']} | "
            f"{_fmt_num(s['oos']['ann_sharpe'], 'sharpe')} | "
            f"{_fmt_ci(ci)} ({ci_label}) | "
            f"{_fmt_num(s['oos']['alpha_vs_spy_matched_pct'], 'pct')} | "
            f"{_fmt_num(s['oos']['max_drawdown_pct'], 'pct')} | "
            f"{_fmt_num(s['oos']['n_trades'], 'int')} | "
            f"{_fmt_num(s['oos']['win_rate_pct'], 'pct')} |"
        )

    lines.append("")
    lines.append("## Full-window metrics")
    lines.append("")
    lines.append("| Strategy | Full Sharpe | Full return | α vs SPY | Max DD | Trades | Avg hold (d) |")
    lines.append("|---|---|---|---|---|---|---|")
    for s in summaries:
        lines.append(
            f"| {s['strategy']} | "
            f"{_fmt_num(s['full']['ann_sharpe'], 'sharpe')} | "
            f"{_fmt_num(s['full']['total_return_pct'], 'pct')} | "
            f"{_fmt_num(s['full']['alpha_vs_spy_matched_pct'], 'pct')} | "
            f"{_fmt_num(s['full']['max_drawdown_pct'], 'pct')} | "
            f"{_fmt_num(s['full']['n_trades'], 'int')} | "
            f"{_fmt_num(s['full']['avg_hold_days'])} |"
        )

    lines.append("")
    lines.append("## Walk-forward folds (Sharpe)")
    lines.append("")
    # Pivot folds into columns
    fold_count = max((len(s["walk_forward"]["folds"]) for s in summaries), default=0)
    header = ["Strategy"] + [f"fold {i}" for i in range(fold_count)] + ["mean", "min", "passed"]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(["---"] * len(header)) + "|")
    for s in summaries:
        row = [s["strategy"]]
        folds = {f["i"]: f for f in s["walk_forward"]["folds"]}
        for i in range(fold_count):
            f = folds.get(i)
            row.append(_fmt_num(f["ann_sharpe"], "sharpe") if f else "n/a")
        row.append(_fmt_num(s["walk_forward"]["mean_sharpe"], "sharpe"))
        row.append(_fmt_num(s["walk_forward"]["min_sharpe"], "sharpe"))
        row.append("PASS" if s["walk_forward"]["passes_gate"] else "FAIL")
        lines.append("| " + " | ".join(row) + " |")

    lines.append("")
    lines.append("## Walk-forward folds (return %)")
    lines.append("")
    lines.append("| " + " | ".join(header[:-3] + ["min DD across folds"]) + " |")
    lines.append("|" + "|".join(["---"] * (len(header) - 2)) + "|")
    for s in summaries:
        row = [s["strategy"]]
        folds = {f["i"]: f for f in s["walk_forward"]["folds"]}
        min_dd = None
        for i in range(fold_count):
            f = folds.get(i)
            row.append(_fmt_num(f["total_return_pct"], "pct") if f else "n/a")
            if f and f["max_drawdown_pct"] is not None:
                v = float(f["max_drawdown_pct"])
                min_dd = v if min_dd is None or v < min_dd else min_dd
        row.append(_fmt_num(min_dd, "pct"))
        lines.append("| " + " | ".join(row) + " |")

    lines.append("")
    lines.append("## Concentration sensitivity (top-5 winners removed)")
    lines.append("")
    lines.append("| Strategy | Headline Sharpe | Stripped Sharpe | Sharpe drop | Top-5 % of P&L | Verdict (drop ≤ 0.4) |")
    lines.append("|---|---|---|---|---|---|")
    for s in summaries:
        c = s["concentration"]
        verdict = "PASS" if (c.get("sharpe_drop") is not None
                             and float(c["sharpe_drop"]) <= 0.4) else "FAIL"
        lines.append(
            f"| {s['strategy']} | "
            f"{_fmt_num(c['headline_sharpe'], 'sharpe')} | "
            f"{_fmt_num(c['stripped_sharpe'], 'sharpe')} | "
            f"{_fmt_num(c['sharpe_drop'], 'sharpe')} | "
            f"{_fmt_num(c['pct'])}% | {verdict} |"
        )

    lines.append("")
    lines.append("## Benchmarks")
    lines.append("")
    if "error" in eq_weight:
        lines.append(f"- Equal-weight universe: ERROR — {eq_weight['error']}")
    else:
        lines.append(
            f"- **Equal-weight universe (buy-and-hold all {eq_weight['n_tickers']} "
            f"tickers in the snapshot at window start, no rebalance)**: "
            f"total return {eq_weight['total_return_pct']:+.2f}%, "
            f"ann Sharpe {eq_weight['ann_sharpe']}"
        )
    if summaries:
        spy = summaries[0]["full"]["spy_return_pct"]
        if spy is not None:
            lines.append(f"- **SPY total return (matched window)**: {spy:+.2f}%")

    lines.append("")
    lines.append("## Yearly breakdown (trades by exit year)")
    lines.append("")
    # Build a wide table: year × strategy
    years = sorted({y["year"] for s in summaries for y in s["yearly"]})
    if years:
        header = ["Year"] + [s["strategy"] for s in summaries]
        lines.append("| " + " | ".join(header) + " |")
        lines.append("|" + "|".join(["---"] * len(header)) + "|")
        for y in years:
            row = [str(y)]
            for s in summaries:
                yb = next((yy for yy in s["yearly"] if yy["year"] == y), None)
                if yb is None:
                    row.append("—")
                else:
                    row.append(
                        f"n={yb['n_trades']} win={yb['win_rate_pct']}% "
                        f"avg={yb['avg_return_pct']:+.2f}% "
                        f"P&L=${yb['total_pnl']:.0f}"
                    )
            lines.append("| " + " | ".join(row) + " |")
    else:
        lines.append("(no trades grouped by year — slim JSON may have dropped trades)")

    lines.append("")
    lines.append("## Data quality")
    lines.append("")
    for s in summaries:
        dq = s["data_quality"] or {}
        sb = dq.get("survivorship_bias") if isinstance(dq, dict) else None
        sev = (sb or {}).get("severity") if isinstance(sb, dict) else None
        pv = dq.get("pipeline_version") if isinstance(dq, dict) else None
        lines.append(
            f"- {s['strategy']}: pipeline `{pv}`, survivorship `{sev}`"
        )

    lines.append("")
    lines.append("## Provenance per strategy")
    lines.append("")
    lines.append("| Strategy | snapshot_id | git_sha | regime |")
    lines.append("|---|---|---|---|")
    for s in summaries:
        lines.append(
            f"| {s['strategy']} | `{s['snapshot_id']}` | `{s['git_sha']}` | "
            f"{s['regime_mode']} |"
        )

    return "\n".join([L for L in lines if L is not None])


def main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]
    results_dir = Path(args.results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)

    paths: dict[str, Path] = {}
    for s in strategies:
        if args.skip_run:
            p = results_dir / f"compare_{s}_{args.snapshot_id}.json"
            if not p.exists():
                logger.error("--skip-run set but %s missing", p)
                return 4
            paths[s] = p
        else:
            paths[s] = _run_strategy(
                strategy=s, snapshot_id=args.snapshot_id,
                years=args.years, starting_cash=args.starting_cash,
                pit_fundamentals=args.pit_fundamentals,
                regime_mode=args.regime_mode, end_date=args.end_date,
                results_dir=results_dir,
                include_trades=args.include_trades,
            )

    summaries: list[dict] = []
    for s in strategies:
        result = json.loads(paths[s].read_text(encoding="utf-8"))
        summaries.append(_strategy_summary(result))

    # Window comes from the first result
    first = summaries[0]
    win = first.get("window") or {}
    start = pd.Timestamp(win.get("start"))
    end = pd.Timestamp(win.get("end"))
    universe = json.loads(paths[strategies[0]].read_text(encoding="utf-8")).get("universe", "?")

    logger.info("Computing equal-weight benchmark...")
    eq_weight = _equal_weight_benchmark(args.snapshot_id, start, end)

    md = _render_markdown(
        summaries=summaries, eq_weight=eq_weight,
        snapshot_id=args.snapshot_id,
        window_start=start, window_end=end,
        universe=universe,
        ran_at=datetime.now(timezone.utc).isoformat(),
        git_sha=first.get("git_sha"),
    )
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    out.with_suffix(".json").write_text(
        json.dumps(
            {
                "snapshot_id": args.snapshot_id,
                "universe": universe,
                "window": {"start": str(start.date()), "end": str(end.date())},
                "summaries": summaries,
                "equal_weight_benchmark": eq_weight,
            },
            indent=2, default=str,
        ),
        encoding="utf-8",
    )
    logger.info("Wrote %s + %s", out, out.with_suffix(".json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
