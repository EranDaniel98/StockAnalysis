"""Minimum Viable Trading Proof (MVTP) report (review item #7).

Reads a backtest result JSON (produced by ``scripts/run_minimal_baseline.py``
or any other strategy's sweep output), checks it against the acceptance
gates from the external review, and emits a single-page markdown report.

Acceptance gates (must all pass for a green light to live capital):

  * OOS Sharpe ratio in [0.7, 1.5]
    (above 2 on retail long-only US = suspect, below 0.7 = no edge)
  * Alpha vs SPY (deployment-matched) in [+2%, +8%] annualized
  * OOS max drawdown >= -20%
  * OOS trade count >= 200 (loose floor; the review's preferred 200
    sample protects the Sharpe CI)
  * Walk-forward passes_min_fold_gate = True (every fold > 0,
    mean >= threshold)
  * Sharpe with top-5 trades removed drops by <= 0.4 (not implemented
    yet — flagged 'manual' until the engine emits per-trade pnl rank)
  * Survivorship guard not bypassed (refuse_survivor_only_window must
    have been True)
  * Pipeline version is post-silent-50-fix (>=2026-05-15)

Usage:
    uv run python -m scripts.produce_mvtp_report \\
        --input data/baseline/minimal_baseline.json \\
        --output reports/mvtp_minimal_baseline.md

Output is markdown; commit it next to the strategy config so the
trade-readiness decision is reviewable.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from textwrap import dedent
from typing import Any


# ----- Acceptance thresholds (review item #7) ---------------------------


SHARPE_LOWER = 0.7
SHARPE_UPPER = 1.5
ALPHA_LOWER_ANNUAL = 2.0       # percentage points
ALPHA_UPPER_ANNUAL = 8.0
MAX_DD_FLOOR = -20.0           # percentage; values below this fail
MIN_OOS_TRADES = 200
MIN_PIPELINE_DATE = date(2026, 5, 15)
WALK_FORWARD_MIN_FOLDS_PASS = True


def _check(label: str, ok: bool, detail: str) -> dict:
    return {"label": label, "pass": bool(ok), "detail": detail}


def _annualize_alpha(alpha_pct: float, years: float) -> float | None:
    if alpha_pct is None or years is None or years <= 0:
        return None
    return alpha_pct / years


def _safe_get(obj: dict | None, *path, default=None):
    """Lookup that returns ``default`` on any missing/None segment."""
    cur: Any = obj
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


def _evaluate(result: dict) -> list[dict]:
    """Run every acceptance gate. Returns a list of {label, pass, detail}."""
    checks: list[dict] = []
    window_years = float(_safe_get(result, "window", "years") or 0)

    oos = result.get("out_of_sample") or {}
    oos_summary = oos.get("summary") or {}
    oos_equity = oos.get("equity_stats") or {}

    # --- Sharpe ---
    sharpe = _safe_get(oos_equity, "ann_sharpe")
    checks.append(_check(
        "OOS Sharpe within [0.7, 1.5]",
        sharpe is not None and SHARPE_LOWER <= sharpe <= SHARPE_UPPER,
        f"Sharpe = {sharpe!r}. Below {SHARPE_LOWER} = no edge; above "
        f"{SHARPE_UPPER} = suspect (likely leakage on retail long-only US).",
    ))

    # --- Alpha vs SPY (annualized) ---
    alpha_matched = _safe_get(oos_summary, "alpha_vs_spy_matched_pct")
    alpha_annual = _annualize_alpha(alpha_matched, window_years)
    checks.append(_check(
        "Alpha vs SPY (matched, annualized) within [+2%, +8%]",
        alpha_annual is not None and ALPHA_LOWER_ANNUAL <= alpha_annual <= ALPHA_UPPER_ANNUAL,
        f"OOS alpha = {alpha_matched!r}%, annualized = "
        f"{round(alpha_annual,2) if alpha_annual is not None else None}%/yr "
        f"over {window_years}y. Alpha > 8%/yr on retail long-only US is "
        f"a red flag for survivorship / lookahead.",
    ))

    # --- Drawdown ---
    max_dd = _safe_get(oos_equity, "max_drawdown_pct")
    checks.append(_check(
        f"OOS max drawdown >= {MAX_DD_FLOOR}%",
        max_dd is not None and max_dd >= MAX_DD_FLOOR,
        f"OOS max DD = {max_dd!r}%.",
    ))

    # --- Trade count ---
    oos_trades = _safe_get(oos_summary, "n_trades") or 0
    checks.append(_check(
        f"OOS trade count >= {MIN_OOS_TRADES}",
        oos_trades >= MIN_OOS_TRADES,
        f"OOS trades = {oos_trades}. Below {MIN_OOS_TRADES} = Sharpe CI is "
        f"wide; consider extending the window or running on a denser universe.",
    ))

    # --- Walk-forward ---
    wf = result.get("walk_forward") or {}
    wf_passes = bool(wf.get("passes_min_fold_gate"))
    wf_reason = wf.get("gate_reason") or "all folds OK"
    checks.append(_check(
        "Walk-forward CV passes (all folds > 0 + mean >= threshold)",
        wf_passes is True,
        (
            f"folds={wf.get('n_folds')}, "
            f"mean Sharpe={wf.get('mean_sharpe')}, "
            f"min Sharpe={wf.get('min_sharpe')}, "
            f"reason: {wf_reason}"
        ),
    ))

    # --- Pipeline freshness ---
    pipeline = result.get("pipeline_version") or "unknown"
    # The pipeline tag is shaped "YYYY-MM-DD-name". Parse the date prefix.
    pipeline_date = None
    try:
        if isinstance(pipeline, str) and len(pipeline) >= 10:
            pipeline_date = date.fromisoformat(pipeline[:10])
    except ValueError:
        pipeline_date = None
    checks.append(_check(
        f"Pipeline version >= {MIN_PIPELINE_DATE.isoformat()}",
        pipeline_date is not None and pipeline_date >= MIN_PIPELINE_DATE,
        f"pipeline_version={pipeline!r}; required post-silent-50-fix "
        f"({MIN_PIPELINE_DATE.isoformat()}).",
    ))

    # --- Survivorship guard ---
    dq = result.get("data_quality") or {}
    sb = (dq.get("survivorship_bias") or {})
    severity = sb.get("severity") or "unknown"
    checks.append(_check(
        "Survivorship-bias guard active (severity != bypassed)",
        severity in {"uncorrected", "haircut_estimated"},
        f"survivorship_bias.severity={severity!r}. 'haircut_estimated' is "
        f"the strongest non-PIT signal; 'bypassed' would mean the operator "
        f"opted out of the guard.",
    ))

    # --- Manual review reminders (not auto-checked) ---
    checks.append({
        "label": "MANUAL: top-5 trades removed drops Sharpe by <= 0.4",
        "pass": None,
        "detail": (
            "Eyeball the trades list — if removing the 5 largest winners "
            "tanks Sharpe, your edge is concentrated. Auto-check pending."
        ),
    })
    checks.append({
        "label": "MANUAL: Sharpe stability across ±10% on min_score / atr_stop",
        "pass": None,
        "detail": (
            "Run two extra sweeps with min_score ±10% and atr_stop ±10%; "
            "spread must be < 0.5 Sharpe. Auto-check pending."
        ),
    })
    checks.append({
        "label": "MANUAL: bear-regime trades (n, win rate, mean return)",
        "pass": None,
        "detail": "See regimes block in the JSON; review qualitatively.",
    })

    return checks


def _render(result: dict, checks: list[dict]) -> str:
    """Single-page markdown report."""
    auto_checks = [c for c in checks if c["pass"] is not None]
    manual_checks = [c for c in checks if c["pass"] is None]
    n_pass = sum(1 for c in auto_checks if c["pass"])
    verdict_emoji = "PASS" if n_pass == len(auto_checks) else "FAIL"

    universe = result.get("universe", "unknown")
    strategy = result.get("strategy", "unknown")
    window = result.get("window") or {}
    starting = result.get("starting_cash", 0)
    n_trades_full = result.get("n_trades", 0)

    oos = result.get("out_of_sample") or {}
    oos_summary = oos.get("summary") or {}
    oos_equity = oos.get("equity_stats") or {}
    wf = result.get("walk_forward") or {}

    lines: list[str] = []
    lines.append(f"# MVTP Report — {strategy}")
    lines.append("")
    lines.append(f"**Verdict (auto-gates only): {verdict_emoji}**  "
                 f"({n_pass}/{len(auto_checks)} auto-gates passed)")
    lines.append("")
    lines.append("> A PASS here means the auto-gates passed. Manual gates "
                 "below still need eyeballing before risking capital.")
    lines.append("")
    lines.append("## Run metadata")
    lines.append("")
    lines.append(f"- **Strategy:** `{strategy}`")
    lines.append(f"- **Universe:** `{universe}`")
    lines.append(f"- **Window:** {window.get('start')} → {window.get('end')} "
                 f"({window.get('years')}y)")
    lines.append(f"- **Starting capital:** ${starting:,.0f}")
    lines.append(f"- **Pipeline version:** `{result.get('pipeline_version')}`")
    lines.append(f"- **PIT fundamentals:** "
                 f"`{result.get('pit_fundamentals')}`")
    lines.append(f"- **Trades (full window):** {n_trades_full}")
    lines.append("")

    lines.append("## OOS headline numbers")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| OOS Sharpe | {oos_equity.get('ann_sharpe')} |")
    lines.append(f"| OOS Sortino | {oos_equity.get('ann_sortino')} |")
    lines.append(f"| OOS total return | {oos_summary.get('total_return_pct')}% |")
    lines.append(f"| SPY return (matched) | {oos_summary.get('spy_deployment_matched_pct')}% |")
    lines.append(f"| Alpha vs SPY (matched) | {oos_summary.get('alpha_vs_spy_matched_pct')}% |")
    lines.append(f"| OOS max drawdown | {oos_equity.get('max_drawdown_pct')}% |")
    lines.append(f"| OOS Calmar | {oos_equity.get('calmar')} |")
    lines.append(f"| OOS win rate | {oos_summary.get('win_rate_pct')}% |")
    lines.append(f"| OOS trades | {oos_summary.get('n_trades')} |")
    lines.append("")

    lines.append("## Walk-forward CV (review #5)")
    lines.append("")
    if wf:
        lines.append(f"- Folds: {wf.get('n_folds')}, mean Sharpe = "
                     f"{wf.get('mean_sharpe')}, min = {wf.get('min_sharpe')}, "
                     f"max = {wf.get('max_sharpe')}")
        lines.append(f"- Threshold (mean Sharpe): "
                     f"{wf.get('min_mean_sharpe_threshold')}")
        lines.append(f"- **Gate:** "
                     f"{'PASS' if wf.get('passes_min_fold_gate') else 'FAIL'} "
                     f"— {wf.get('gate_reason') or 'all folds OK'}")
        lines.append("")
        lines.append("| Fold | Range | Trades | Status | Sharpe | Return % | Max DD % |")
        lines.append("|---|---|---|---|---|---|---|")
        for f in wf.get("folds", []):
            lines.append(
                f"| {f['fold_index']} | {f['start_date']}→{f['end_date']} "
                f"| {f['n_trades']} | {f['status']} | "
                f"{f['ann_sharpe']} | {f['total_return_pct']} | "
                f"{f['max_drawdown_pct']} |"
            )
    else:
        lines.append("_No walk-forward report (walk_forward_folds=0 in config?)_")
    lines.append("")

    lines.append("## Acceptance gates (review item #7)")
    lines.append("")
    lines.append("| # | Gate | Result | Detail |")
    lines.append("|---|---|---|---|")
    for i, c in enumerate(auto_checks, 1):
        mark = "PASS" if c["pass"] else "FAIL"
        lines.append(f"| {i} | {c['label']} | **{mark}** | {c['detail']} |")
    lines.append("")
    lines.append("### Manual gates (review qualitatively)")
    lines.append("")
    for c in manual_checks:
        lines.append(f"- [ ] **{c['label']}** — {c['detail']}")
    lines.append("")

    lines.append("## Operator gates (review #7, must all be checked)")
    lines.append("")
    lines.append(dedent("""\
        - [ ] Kill switch implemented + tested (`trading.trading_enabled`)
        - [ ] Max-daily-loss limit enforced (`trading.circuit_breakers.max_daily_loss_pct`)
        - [ ] Max-drawdown halt enforced (`trading.circuit_breakers.max_drawdown_halt_pct`)
        - [ ] Earnings blackout enforced (fail-loud)
        - [ ] Reconciliation orphan-alert wired
        - [ ] Stream-bus is_healthy monitored
        - [ ] score_valid=False refusal applies to entries AND exits
        - [ ] Bracket SL/TP atomically submitted at entry
        - [ ] Survivorship-bias guard active on universe
        - [ ] Walk-forward CV report present
        """).rstrip())

    lines.append("")
    lines.append("## Warnings emitted by the backtest")
    lines.append("")
    warnings = result.get("warnings") or []
    if warnings:
        for w in warnings:
            lines.append(f"- {w}")
    else:
        lines.append("_(none)_")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("If every auto-gate PASSes AND every manual + operator "
                 "checkbox is ticked, the strategy is cleared for the "
                 "**Phase 2 ($500 / $50 per position)** rung of the capital "
                 "safety ladder. Larger sizing requires Phase 3 evidence.")
    return "\n".join(lines)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--input", required=True,
                   help="Path to backtest JSON (from run_minimal_baseline.py)")
    p.add_argument("--output", required=True,
                   help="Path to write the markdown report")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    src = Path(args.input)
    if not src.exists():
        print(f"input not found: {src}", file=sys.stderr)
        return 1
    result = json.loads(src.read_text(encoding="utf-8"))
    checks = _evaluate(result)
    md = _render(result, checks)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(f"wrote {out}")

    # Also print the auto-gates verdict to stdout so a CI/cron caller
    # gets a non-zero exit on failure.
    auto = [c for c in checks if c["pass"] is not None]
    if not all(c["pass"] for c in auto):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
