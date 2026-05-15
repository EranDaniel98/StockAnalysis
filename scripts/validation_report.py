"""Validation report — diff accumulated daily snapshots against the
minimal_baseline backtest baseline.

Run this at day 30+ of the paper-validation phase. Emits markdown:

  * Day-by-day equity / cum P&L / submitted-today
  * Rolling annualized Sharpe of the daily-return series
  * Comparison vs the backtest baseline (data/baseline/minimal_baseline.json)
  * The acceptance gate: live Sharpe within 0.4 of backtest Sharpe?

The gate is the operator's green-light for advancing to Phase 2 of the
capital safety ladder ($500 / $50 per position). Failure means either
the strategy is overfit, the backtest is contaminated, or the live
window is too short to draw conclusions — the report shows enough
context to tell which.

Usage:

    uv run python -m scripts.validation_report \\
        --baseline data/baseline/minimal_baseline.json \\
        --output reports/validation_<date>.md
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path

import numpy as np


# Convergence tolerance per the external review: live-paper Sharpe must
# be within this many points of the backtest Sharpe to clear the gate.
# 0.4 is generous given small-sample uncertainty on 22 daily obs.
SHARPE_CONVERGENCE_TOL = 0.4

# Minimum days of observation before the gate is meaningful. 22 = one
# trading month. Under this we report data but don't claim a verdict.
MIN_DAYS_FOR_GATE = 22


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--strategy", default="minimal_baseline",
        help="Validation strategy tag to load from data/validation.db",
    )
    p.add_argument(
        "--baseline", default="data/baseline/minimal_baseline.json",
        help="Path to the backtest JSON whose Sharpe we compare against",
    )
    p.add_argument(
        "--output", required=True,
        help="Markdown report destination",
    )
    p.add_argument(
        "--db-path", default=None,
        help="Override the validation DB location",
    )
    p.add_argument(
        "--sharpe-tol", type=float, default=SHARPE_CONVERGENCE_TOL,
        help=f"Sharpe convergence tolerance (default {SHARPE_CONVERGENCE_TOL})",
    )
    return p.parse_args()


def _compute_live_sharpe(snapshots: list[dict]) -> dict:
    """Compute live-paper Sharpe from the daily equity series.

    Daily granularity → annualizer is sqrt(252) (trading days per year).
    Returns dict with point estimate, std, n_days. Sharpe is None when
    fewer than 2 returns are available (or zero std).
    """
    if len(snapshots) < 2:
        return {
            "n_days": len(snapshots),
            "ann_sharpe": None,
            "mean_daily_pct": None,
            "std_daily_pct": None,
            "total_return_pct": 0.0,
        }

    equities = np.array(
        [float(s["account_equity"]) for s in snapshots], dtype=float,
    )
    daily_returns = equities[1:] / equities[:-1] - 1.0
    daily_returns = daily_returns[np.isfinite(daily_returns)]
    n_returns = len(daily_returns)
    if n_returns < 1:
        return {
            "n_days": len(snapshots),
            "ann_sharpe": None,
            "mean_daily_pct": None,
            "std_daily_pct": None,
            "total_return_pct": 0.0,
        }

    mean = float(daily_returns.mean())
    std = float(daily_returns.std(ddof=1)) if n_returns > 1 else 0.0
    ann_sharpe = (mean / std) * math.sqrt(252) if std > 0 else 0.0
    total_return = (equities[-1] / equities[0] - 1.0) * 100.0

    return {
        "n_days": len(snapshots),
        "n_returns": n_returns,
        "ann_sharpe": round(ann_sharpe, 2),
        "mean_daily_pct": round(mean * 100.0, 3),
        "std_daily_pct": round(std * 100.0, 3),
        "total_return_pct": round(total_return, 2),
    }


def _backtest_sharpe(baseline_path: Path) -> dict:
    """Pull OOS Sharpe + CI from the backtest baseline JSON."""
    if not baseline_path.exists():
        return {"available": False, "reason": f"baseline not found at {baseline_path}"}
    data = json.loads(baseline_path.read_text(encoding="utf-8"))
    oos = data.get("out_of_sample") or {}
    eq_stats = oos.get("equity_stats") or {}
    boot = data.get("bootstrap") or {}
    return {
        "available": True,
        "ann_sharpe": eq_stats.get("ann_sharpe"),
        "ann_sharpe_ci": boot.get("ann_sharpe_ci"),
        "total_return_pct": (oos.get("summary") or {}).get("total_return_pct"),
        "pipeline_version": data.get("pipeline_version"),
        "window": data.get("window"),
    }


def _evaluate_gate(live: dict, backtest: dict, tol: float) -> dict:
    """Decide PASS/FAIL/INSUFFICIENT for the convergence gate."""
    if live["n_days"] < MIN_DAYS_FOR_GATE:
        return {
            "verdict": "INSUFFICIENT",
            "reason": (
                f"Only {live['n_days']} daily snapshots; gate requires "
                f"{MIN_DAYS_FOR_GATE}+ for a meaningful comparison."
            ),
            "delta": None,
        }
    if not backtest.get("available"):
        return {
            "verdict": "INSUFFICIENT",
            "reason": (
                f"No backtest baseline to compare against: "
                f"{backtest.get('reason')}"
            ),
            "delta": None,
        }
    bt = backtest.get("ann_sharpe")
    live_s = live.get("ann_sharpe")
    if bt is None or live_s is None:
        return {
            "verdict": "INSUFFICIENT",
            "reason": "Sharpe missing on one side (live or backtest)",
            "delta": None,
        }
    # Round delta to 2 decimals before the threshold compare so float
    # precision can't slip a 0.40000000000000036 over a 0.4 boundary.
    # The report displays the rounded value anyway, so the gate matches
    # what the operator reads.
    delta = round(abs(live_s - bt), 2)
    if delta <= tol:
        return {
            "verdict": "PASS",
            "reason": (
                f"Live Sharpe {live_s} within {tol} of backtest {bt} "
                f"(delta={delta:.2f}). Ready for Phase 2 ($500 / $50 per "
                f"position) per the capital safety ladder."
            ),
            "delta": delta,
        }
    return {
        "verdict": "FAIL",
        "reason": (
            f"Live Sharpe {live_s} diverged from backtest {bt} by "
            f"{delta:.2f} > tolerance {tol}. Strategy may be overfit, "
            f"backtest contaminated, or window too short — investigate "
            f"before advancing capital."
        ),
        "delta": delta,
    }


def _render(strategy: str, snapshots: list[dict], live: dict,
            backtest: dict, gate: dict, tol: float) -> str:
    lines: list[str] = []
    lines.append(f"# Paper-Validation Report — {strategy}")
    lines.append("")
    lines.append(f"**Verdict: {gate['verdict']}**")
    lines.append("")
    lines.append(f"_{gate['reason']}_")
    lines.append("")

    lines.append("## Live vs backtest")
    lines.append("")
    lines.append("| Metric | Live (paper) | Backtest (minimal_baseline) | Δ |")
    lines.append("|---|---|---|---|")
    bt_s = backtest.get("ann_sharpe")
    ci = backtest.get("ann_sharpe_ci")
    ci_str = (
        f" [{ci[0]:.2f}, {ci[1]:.2f}]"
        if ci and len(ci) == 2 else ""
    )
    lines.append(
        f"| Ann Sharpe | {live.get('ann_sharpe')} | "
        f"{bt_s}{ci_str} | "
        f"{gate.get('delta')} (tol {tol}) |"
    )
    lines.append(
        f"| Total return | {live.get('total_return_pct')}% | "
        f"{backtest.get('total_return_pct')}% | — |"
    )
    lines.append(f"| Days observed | {live.get('n_days')} | (backtest window: "
                 f"{backtest.get('window', {}).get('years', '?')}y) | — |")
    lines.append("")

    lines.append("## Day-by-day snapshots")
    lines.append("")
    lines.append("| Date | Equity | Day %Δ | Cum %Δ | Positions | "
                 "Submitted | Refused (orphan/gate/score) |")
    lines.append("|---|---|---|---|---|---|---|")
    for s in snapshots:
        refused_str = (
            f"{s['refusals_orphan']}/{s['refusals_safety_gate']}/"
            f"{s['refusals_score_valid']}"
        )
        lines.append(
            f"| {s['snapshot_date']} | ${s['account_equity']:,.2f} | "
            f"{s['day_pnl_pct']:+.2f}% | {s['cum_pnl_pct']:+.2f}% | "
            f"{s['n_positions']} | {s['submitted_today']} | {refused_str} |"
        )
    lines.append("")

    lines.append("## Mechanics")
    lines.append("")
    lines.append(f"- **Mean daily return:** {live.get('mean_daily_pct')}%")
    lines.append(f"- **Daily volatility:** {live.get('std_daily_pct')}%")
    lines.append(f"- **Daily-return observations:** {live.get('n_returns', 0)}")
    lines.append(f"- **Annualizer:** sqrt(252) (daily-return convention)")
    lines.append(f"- **Backtest pipeline:** "
                 f"`{backtest.get('pipeline_version', 'unknown')}`")
    lines.append("")

    lines.append("## Next step")
    lines.append("")
    if gate["verdict"] == "PASS":
        lines.append(
            "- [ ] Advance to **Phase 2** of the capital safety ladder: "
            "$500 total, $50 per position max, 60-day observation window."
        )
        lines.append(
            "- [ ] Keep the daily snapshot cron running; re-run this report "
            "monthly to confirm convergence is sustained."
        )
    elif gate["verdict"] == "FAIL":
        lines.append(
            "- [ ] **Do NOT advance capital.** Investigate divergence: "
            "compare per-trade outcomes against backtest expectations, "
            "check for missing earnings dates or stale fundamentals."
        )
        lines.append(
            "- [ ] Consider extending the observation window 30 more days "
            "before declaring the strategy unfit — small sample noise can "
            "produce false fails."
        )
    else:
        lines.append(
            f"- [ ] Continue daily snapshots until {MIN_DAYS_FOR_GATE} "
            f"observations are accumulated."
        )
        lines.append("- [ ] Re-run this report at that point.")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    args = _parse_args()

    from src.validation.store import ValidationStore

    db_path = Path(args.db_path) if args.db_path else None
    with ValidationStore(db_path=db_path) as store:
        snapshots = store.list_snapshots(args.strategy)

    if not snapshots:
        print(
            f"validation_report: no snapshots for strategy "
            f"{args.strategy!r} in the DB. Run validation_daily first.",
            file=sys.stderr,
        )
        return 1

    live = _compute_live_sharpe(snapshots)
    backtest = _backtest_sharpe(Path(args.baseline))
    gate = _evaluate_gate(live, backtest, args.sharpe_tol)
    md = _render(args.strategy, snapshots, live, backtest, gate, args.sharpe_tol)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(f"wrote {out}")
    # Non-zero exit on FAIL so a cron caller catches it.
    if gate["verdict"] == "FAIL":
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
