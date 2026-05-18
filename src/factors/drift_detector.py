"""Daily-picks drift detector.

Compares today's picks JSON against the trailing N days. Flags when
universe size, factor coverage, sector mix, or composite z
distribution shifts beyond a threshold — the early-warning signal
for a data outage, ingestion bug, or upstream API change BEFORE the
paper-trader fires on bad data.

Checks (each gets ``ok`` / ``warn`` / ``fail`` status):

1. **universe_size_drift** — today's eligible name count vs trailing
   mean. Fails at -20% from baseline.
2. **factor_coverage_drift** — n names per factor (momentum, quality,
   value, pead) vs baseline. Same -20% threshold.
3. **sector_concentration** — share of any single sector in today's
   picks. Fails at >50% (sector cap should have caught this; if we
   see it, the cap broke).
4. **composite_z_top** — top pick's composite z-score vs trailing
   mean. Warns at ±2σ from baseline.
5. **hysteresis_carry_rate** — % of today's picks present in
   yesterday's. Warns if <10% (hysteresis is off or yesterday's
   picks didn't load) or >95% (selection is frozen).

The detector is read-only: it consumes JSON files written by
``scripts/daily_factor_picks.py`` and produces a structured report.
A separate CLI (``scripts/check_picks_drift.py``) prints it and exits
non-zero on ``fail`` so cron / paper trade flows can short-circuit.
"""

from __future__ import annotations

import json
import logging
import math
import statistics
from collections import Counter
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# Status precedence for overall: fail > warn > ok.
_STATUS_ORDER = {"ok": 0, "warn": 1, "fail": 2}


@dataclass(frozen=True)
class DriftCheck:
    """One drift check's outcome."""

    name: str
    status: str            # "ok" | "warn" | "fail"
    value: float | str     # what we observed today
    baseline: Optional[float]  # rolling mean or None when undefined
    threshold: str         # human-readable threshold description
    message: str           # one-line explanation


@dataclass(frozen=True)
class DriftReport:
    today_path: str
    history_paths: list[str]
    overall_status: str
    checks: list[DriftCheck]


def _load_pick_file(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read pick file %s: %s", path, exc)
        return None


def _collect_history(
    history_dir: Path, today_stem: str, days: int,
) -> list[tuple[Path, dict]]:
    """Find the up-to-``days`` most recent JSON files strictly before today."""
    if not history_dir.exists():
        return []
    candidates = sorted(
        f for f in history_dir.glob("*.json")
        if f.stem < today_stem
    )
    candidates = candidates[-days:]
    loaded: list[tuple[Path, dict]] = []
    for f in candidates:
        data = _load_pick_file(f)
        if data is not None:
            loaded.append((f, data))
    return loaded


def _check_universe_size(
    today: dict, history: list[dict],
) -> DriftCheck:
    today_n = int(today.get("universe_size", 0) or 0)
    historical = [int(h.get("universe_size", 0) or 0) for h in history]
    historical = [n for n in historical if n > 0]
    if not historical:
        return DriftCheck(
            name="universe_size_drift", status="ok",
            value=today_n, baseline=None,
            threshold="-20% from rolling mean",
            message=f"No history to compare ({today_n} today; first run?)",
        )
    baseline = statistics.mean(historical)
    pct_change = (today_n - baseline) / baseline if baseline > 0 else 0.0
    if pct_change <= -0.20:
        status = "fail"
        msg = (
            f"Universe shrank {pct_change * 100:+.1f}% vs trailing mean "
            f"({today_n} vs {baseline:.0f})"
        )
    elif pct_change <= -0.10:
        status = "warn"
        msg = (
            f"Universe down {pct_change * 100:+.1f}% vs trailing mean "
            f"({today_n} vs {baseline:.0f})"
        )
    else:
        status = "ok"
        msg = (
            f"Universe {today_n} vs trailing mean {baseline:.0f} "
            f"({pct_change * 100:+.1f}%)"
        )
    return DriftCheck(
        name="universe_size_drift", status=status,
        value=today_n, baseline=round(baseline, 1),
        threshold="-20% fail, -10% warn",
        message=msg,
    )


def _is_missing(v) -> bool:
    """True for None and float-NaN. Pandas writes NaN literals into JSON
    which decode as float('nan'), not None — both must be treated as
    "missing" for coverage."""
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    return False


def _factor_coverage(picks: list[dict], factor: str) -> int:
    """Count how many of today's picks have a numeric rank for ``factor``.

    Returns the count of picks where the per-factor rank column is
    non-null/non-NaN. Coverage drops are the canary for an EDGAR
    ingest break or a yfinance schema change.
    """
    name_map = {
        "momentum": "mom_rank",
        "quality": "qual_rank",
        "value": "val_rank",
        "pead": "pead_rank",
    }
    col = name_map.get(factor, f"{factor}_rank")
    return sum(
        1 for p in picks
        if isinstance(p, dict) and not _is_missing(p.get(col))
    )


def _check_factor_coverage(
    today: dict, history: list[dict],
) -> list[DriftCheck]:
    """One check per factor declared in today's run."""
    factors = today.get("factors", []) or []
    out: list[DriftCheck] = []
    today_picks = today.get("picks", []) or []
    n_today = len(today_picks)
    for f in factors:
        today_cov = _factor_coverage(today_picks, f)
        baselines = [
            _factor_coverage(h.get("picks", []) or [], f)
            for h in history
            if f in (h.get("factors", []) or [])
        ]
        if not baselines:
            out.append(DriftCheck(
                name=f"factor_coverage_{f}",
                status="ok", value=today_cov, baseline=None,
                threshold="-20% fail, -10% warn",
                message=f"No history for {f}",
            ))
            continue
        baseline = statistics.mean(baselines)
        pct_change = (
            (today_cov - baseline) / baseline if baseline > 0 else 0.0
        )
        if today_cov == 0 and baseline > 0:
            status = "fail"
            msg = (
                f"{f} coverage collapsed to 0 (baseline {baseline:.1f})"
            )
        elif pct_change <= -0.20:
            status = "fail"
            msg = (
                f"{f} coverage {today_cov}/{n_today} vs baseline "
                f"{baseline:.1f} ({pct_change * 100:+.1f}%)"
            )
        elif pct_change <= -0.10:
            status = "warn"
            msg = (
                f"{f} coverage {today_cov}/{n_today} vs baseline "
                f"{baseline:.1f} ({pct_change * 100:+.1f}%)"
            )
        else:
            status = "ok"
            msg = (
                f"{f} coverage {today_cov}/{n_today} (baseline "
                f"{baseline:.1f})"
            )
        out.append(DriftCheck(
            name=f"factor_coverage_{f}",
            status=status, value=today_cov, baseline=round(baseline, 1),
            threshold="-20% fail, -10% warn",
            message=msg,
        ))
    return out


def _check_sector_concentration(today: dict) -> DriftCheck:
    """A single sector taking >50% of picks should be caught by the
    sector cap. If we see it here, the cap is broken or was disabled."""
    picks = today.get("picks", []) or []
    if not picks:
        return DriftCheck(
            name="sector_concentration", status="warn",
            value=0, baseline=None,
            threshold=">50% any sector = fail",
            message="No picks to evaluate",
        )
    sectors = Counter(
        (p.get("sector") or "Unknown")
        for p in picks if isinstance(p, dict)
    )
    top_sector, top_n = sectors.most_common(1)[0]
    share = top_n / len(picks)
    if share > 0.50:
        status = "fail"
        msg = (
            f"Sector cap broken: {top_sector} = {top_n}/{len(picks)} "
            f"({share * 100:.1f}%)"
        )
    elif share > 0.40:
        status = "warn"
        msg = (
            f"Heavy {top_sector} tilt: {top_n}/{len(picks)} "
            f"({share * 100:.1f}%)"
        )
    elif top_sector == "Unknown" and share > 0.20:
        status = "warn"
        msg = (
            f"{share * 100:.1f}% of picks bucket as 'Unknown' — sector "
            "lookup may be misfiring"
        )
    else:
        status = "ok"
        msg = (
            f"Top sector {top_sector} {top_n}/{len(picks)} "
            f"({share * 100:.1f}%)"
        )
    return DriftCheck(
        name="sector_concentration", status=status,
        value=f"{top_sector}:{share * 100:.0f}%", baseline=None,
        threshold=">50% fail, >40% warn",
        message=msg,
    )


def _check_composite_z_top(
    today: dict, history: list[dict],
) -> DriftCheck:
    today_picks = today.get("picks", []) or []
    if not today_picks:
        return DriftCheck(
            name="composite_z_top", status="warn",
            value=0.0, baseline=None,
            threshold=">2sigma from rolling mean",
            message="No picks today",
        )
    today_z = float(today_picks[0].get("z_score", 0.0) or 0.0)
    z_history: list[float] = []
    for h in history:
        hp = h.get("picks", []) or []
        if hp and isinstance(hp[0], dict):
            v = hp[0].get("z_score")
            if v is not None:
                z_history.append(float(v))
    if len(z_history) < 3:
        return DriftCheck(
            name="composite_z_top", status="ok",
            value=round(today_z, 3), baseline=None,
            threshold=">2sigma from rolling mean",
            message=f"Insufficient history ({len(z_history)} prior runs)",
        )
    mu = statistics.mean(z_history)
    sigma = statistics.pstdev(z_history) if len(z_history) >= 2 else 0.0
    if sigma > 0:
        z_dev = (today_z - mu) / sigma
    else:
        z_dev = 0.0
    if abs(z_dev) > 3:
        status = "fail"
        msg = (
            f"Top z_score {today_z:.2f} is {z_dev:+.1f}sigma from "
            f"rolling mean {mu:.2f}"
        )
    elif abs(z_dev) > 2:
        status = "warn"
        msg = (
            f"Top z_score {today_z:.2f} is {z_dev:+.1f}sigma from "
            f"rolling mean {mu:.2f}"
        )
    else:
        status = "ok"
        msg = (
            f"Top z_score {today_z:.2f} (rolling mean {mu:.2f} "
            f"sigma {sigma:.2f})"
        )
    return DriftCheck(
        name="composite_z_top", status=status,
        value=round(today_z, 3),
        baseline=round(mu, 3) if z_history else None,
        threshold=">2sigma warn, >3sigma fail",
        message=msg,
    )


def _check_hysteresis_carry(
    today: dict, history: list[dict],
) -> DriftCheck:
    if not history:
        return DriftCheck(
            name="hysteresis_carry_rate", status="ok",
            value=0.0, baseline=None,
            threshold="<10% warn, >95% warn",
            message="No prior file to compare",
        )
    today_set = {
        p.get("ticker") for p in today.get("picks", []) or []
        if isinstance(p, dict)
    }
    today_set.discard(None)
    yesterday = history[-1]
    yesterday_set = {
        p.get("ticker") for p in yesterday.get("picks", []) or []
        if isinstance(p, dict)
    }
    yesterday_set.discard(None)
    if not today_set or not yesterday_set:
        return DriftCheck(
            name="hysteresis_carry_rate", status="ok",
            value=0.0, baseline=None,
            threshold="<10% warn, >95% warn",
            message="Empty pick set on one side",
        )
    overlap = today_set & yesterday_set
    rate = len(overlap) / len(today_set)
    if rate < 0.10:
        status = "warn"
        msg = (
            f"Carry rate {rate * 100:.1f}% — hysteresis may be off or "
            "yesterday's picks didn't load"
        )
    elif rate > 0.95:
        status = "warn"
        msg = (
            f"Carry rate {rate * 100:.1f}% — selection effectively "
            "frozen, signals may not be updating"
        )
    else:
        status = "ok"
        msg = f"Carry rate {rate * 100:.1f}% ({len(overlap)}/{len(today_set)})"
    return DriftCheck(
        name="hysteresis_carry_rate", status=status,
        value=round(rate, 3), baseline=None,
        threshold="<10% warn, >95% warn",
        message=msg,
    )


def compute_drift_report(
    today_path: Path,
    history_dir: Path,
    *,
    days: int = 30,
) -> DriftReport:
    """Build the full drift report for ``today_path`` vs trailing ``days``."""
    today_path = Path(today_path)
    history_dir = Path(history_dir)

    today_data = _load_pick_file(today_path)
    if today_data is None:
        return DriftReport(
            today_path=str(today_path),
            history_paths=[],
            overall_status="fail",
            checks=[DriftCheck(
                name="load_today", status="fail",
                value=str(today_path), baseline=None,
                threshold="readable JSON",
                message=f"Could not load {today_path}",
            )],
        )

    today_stem = today_path.stem
    history = _collect_history(history_dir, today_stem, days)
    history_data = [d for _, d in history]
    history_paths = [str(p) for p, _ in history]

    checks: list[DriftCheck] = []
    checks.append(_check_universe_size(today_data, history_data))
    checks.extend(_check_factor_coverage(today_data, history_data))
    checks.append(_check_sector_concentration(today_data))
    checks.append(_check_composite_z_top(today_data, history_data))
    checks.append(_check_hysteresis_carry(today_data, history_data))

    overall = max(
        (c.status for c in checks),
        key=lambda s: _STATUS_ORDER.get(s, 0),
        default="ok",
    )

    return DriftReport(
        today_path=str(today_path),
        history_paths=history_paths,
        overall_status=overall,
        checks=checks,
    )


def format_markdown(report: DriftReport) -> str:
    """Render the drift report as markdown."""
    lines: list[str] = []
    badge = {
        "ok": "OK", "warn": "WARN", "fail": "FAIL",
    }[report.overall_status]
    lines.append(f"# Picks Drift Report — [{badge}]")
    lines.append("")
    lines.append(f"**Today:** `{report.today_path}`")
    lines.append(f"**History:** {len(report.history_paths)} prior file(s)")
    lines.append("")
    lines.append("| Check | Status | Value | Baseline | Message |")
    lines.append("|---|---|---|---|---|")
    for c in report.checks:
        b = "" if c.baseline is None else f"{c.baseline}"
        lines.append(
            f"| {c.name} | {c.status.upper()} | {c.value} | {b} | {c.message} |"
        )
    return "\n".join(lines)


__all__ = [
    "DriftCheck",
    "DriftReport",
    "compute_drift_report",
    "format_markdown",
]
