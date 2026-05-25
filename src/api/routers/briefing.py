"""/api/dashboard/briefing -- morning briefing summary.

Aggregates three independent signals into one banner card:
  1. Pre-trade drift gate verdict (refuse rebalance on FAIL).
  2. Factor coverage per pick (which factors degraded today).
  3. Position alerts -- which held positions hit a stop or target.

Read-only: pulls today's picks JSON, the latest portfolio_analysis
JSON, and Alpaca paper positions. Never writes.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from src.api.schemas.briefing import (
    ActionCounts,
    BriefingResponse,
    DriftCheckOut,
    FactorCoverage,
    PositionAlert,
    TopPick,
)
from src.execution.alpaca import AlpacaClient, AlpacaClientError
from src.factors.drift_detector import compute_drift_report

logger = logging.getLogger(__name__)
router = APIRouter()


PICKS_DIR = Path("data/daily_picks")
REPORTS_DIR = Path("reports")

# Maps the per-factor rank column in today's picks JSON to the factor
# name we render in the FE. Keep in sync with
# src.factors.drift_detector._factor_coverage().
_FACTOR_RANK_COL = {
    "momentum": "mom_rank",
    "quality": "qual_rank",
    "value": "val_rank",
    "pead": "pead_rank",
}

# Per-factor coverage tiers used by the FE coverage bar.
_COVERAGE_FAIL_BELOW = 0.70
_COVERAGE_WARN_BELOW = 0.85

# Position-monitor thresholds -- match scripts/position_monitor.py::_classify.
_NEAR_STOP_MULT = 1.02       # current <= stop * 1.02
_NEAR_TARGET_MULT = 0.98     # current >= target * 0.98
_FALLBACK_STOP_PCT = 0.08    # 8% below avg entry when no strategy plan exists
_FALLBACK_TARGET_PCT = 0.10  # 10% above

# Fractional-share residue from partial fills can leave positions worth
# pennies (0.7 sh of DNN at $3.28 = $2.30). Don't alert on those -- they
# can't be flattened meaningfully and just add noise to the card.
_MIN_ALERT_MARKET_VALUE = 10.0

# Number of picks projected into BriefingResponse.top_picks. Five is
# the morning-briefing markdown's headline depth; the rest live on /factors.
_TOP_PICKS_FOR_DASHBOARD = 5


def _is_missing(v) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and v != v:  # NaN
        return True
    return False


def _today_picks_path(picks_date: Optional[date]) -> Path:
    d = picks_date or datetime.now(timezone.utc).date()
    return PICKS_DIR / f"{d.isoformat()}.json"


def _latest_portfolio_analysis() -> Optional[Path]:
    """Find the freshest reports/portfolio_analysis_*.json so position
    alerts can resolve strategy-derived stop/target levels. Returns None
    if no such file exists (alerts then fall back to 8% bands)."""
    if not REPORTS_DIR.exists():
        return None
    candidates = sorted(REPORTS_DIR.glob("portfolio_analysis_*.json"))
    return candidates[-1] if candidates else None


def _factor_coverage_status(pct: float) -> str:
    if pct < _COVERAGE_FAIL_BELOW:
        return "fail"
    if pct < _COVERAGE_WARN_BELOW:
        return "warn"
    return "ok"


def _build_factor_coverage(picks: list[dict]) -> list[FactorCoverage]:
    """Count non-null per-factor ranks across today's picks."""
    n = len(picks)
    if n == 0:
        return []
    out: list[FactorCoverage] = []
    for factor, col in _FACTOR_RANK_COL.items():
        covered = sum(
            1 for p in picks
            if isinstance(p, dict) and not _is_missing(p.get(col))
        )
        pct = covered / n if n > 0 else 0.0
        out.append(FactorCoverage(
            factor=factor,
            covered=covered,
            total=n,
            pct=pct,
            status=_factor_coverage_status(pct),
        ))
    return out


def _classify_position(
    current: float, stop: float, target: float,
) -> Optional[str]:
    """Returns one of STOP_HIT / TARGET_HIT / NEAR_STOP / NEAR_TARGET, or
    None when the position is mid-range (no alert)."""
    if current <= stop:
        return "STOP_HIT"
    if current >= target:
        return "TARGET_HIT"
    if current <= stop * _NEAR_STOP_MULT:
        return "NEAR_STOP"
    if current >= target * _NEAR_TARGET_MULT:
        return "NEAR_TARGET"
    return None


def _build_position_alerts(
    positions: list[dict], analysis_plans: dict[str, dict],
) -> list[PositionAlert]:
    """For each held position, derive (stop, target) -- prefer the
    strategy-recommended levels from the latest portfolio_analysis JSON,
    fall back to fixed-percentage bands -- and classify. Only positions
    that actually triggered (stop/target/near-stop/near-target) appear
    in the result."""
    alerts: list[PositionAlert] = []
    for p in positions:
        t = p["ticker"]
        current = float(p.get("current_price") or 0.0)
        avg_entry = float(p.get("avg_price") or 0.0)
        shares_raw = float(p.get("shares") or 0)
        if current <= 0 or avg_entry <= 0:
            continue
        # Short positions need inverted stop/target semantics (stop ABOVE
        # entry, target BELOW). The portfolio_analysis JSON only stores
        # long-direction levels today, so any alert on a short would
        # misclassify. Skip them rather than emit a wrong signal.
        if shares_raw < 0:
            continue
        if abs(shares_raw) * current < _MIN_ALERT_MARKET_VALUE:
            continue
        plan = analysis_plans.get(t)
        if plan and plan.get("stop_loss") and plan.get("target"):
            stop = float(plan["stop_loss"])
            target = float(plan["target"])
            source = "strategy"
        else:
            stop = avg_entry * (1 - _FALLBACK_STOP_PCT)
            target = avg_entry * (1 + _FALLBACK_TARGET_PCT)
            source = "fallback_8pct"
        status = _classify_position(current, stop, target)
        if status is None:
            continue
        pl_pct = ((current / avg_entry) - 1.0) * 100 if avg_entry > 0 else 0.0
        alerts.append(PositionAlert(
            ticker=t, status=status,
            current_price=round(current, 4),
            avg_entry=round(avg_entry, 4),
            stop=round(stop, 4), target=round(target, 4),
            shares=round(shares_raw, 4),
            pl_pct=round(pl_pct, 2),
            source=source,
        ))
    # Sort: STOP_HIT first (most urgent), then TARGET_HIT, then NEAR_STOP,
    # then NEAR_TARGET; within each bucket worst loss first.
    rank = {"STOP_HIT": 0, "NEAR_STOP": 1, "TARGET_HIT": 2, "NEAR_TARGET": 3}
    alerts.sort(key=lambda a: (rank.get(a.status, 99), a.pl_pct))
    return alerts


def _drift_message(report) -> str:
    """One-line summary of the worst drift check, for the FE chip."""
    if report.overall_status == "ok":
        return f"All {len(report.checks)} drift checks passed"
    worst = next(
        (c for c in report.checks if c.status == report.overall_status), None,
    )
    return worst.message if worst else f"Drift {report.overall_status}"


def _urgent_action_phrase(n_stops: int, n_targets: int) -> str:
    """Pluralized 'N stop(s) and M target(s)' clause -- empty string when
    there are no urgent items so the caller can skip it cleanly."""
    parts: list[str] = []
    if n_stops:
        parts.append(f"{n_stops} stop{'s' if n_stops != 1 else ''}")
    if n_targets:
        parts.append(
            f"{n_targets} target{'s' if n_targets != 1 else ''} hit"
        )
    return " and ".join(parts)


def _recommendation(
    gate_status: str, n_stops: int, n_targets: int,
) -> str:
    if gate_status == "no_picks":
        return (
            "No picks generated for today. Run "
            "`scripts.daily_factor_picks` or check the pipeline."
        )
    urgent = _urgent_action_phrase(n_stops, n_targets)
    if gate_status == "fail":
        if urgent:
            return f"DO NOT REBALANCE -- drift gate FAIL. Handle {urgent} only."
        return "DO NOT REBALANCE -- drift gate FAIL. No urgent position actions."
    if gate_status == "warn":
        return "PROCEED WITH CAUTION -- drift WARN. Review checks before executing."
    if urgent:
        return f"PROCEED with rebalance. First handle {urgent}."
    return "PROCEED with rebalance. Pre-trade gate clean."


async def _fetch_positions() -> list[dict]:
    """Alpaca client is sync; offload to a thread. Treat connection errors
    as a soft failure -- briefing still loads with empty alerts so the
    drift gate is still visible."""
    try:
        client = AlpacaClient()
    except AlpacaClientError as e:
        logger.warning("Alpaca client unavailable for briefing: %s", e)
        return []
    try:
        return await asyncio.to_thread(client.get_positions)
    except Exception as e:  # noqa: BLE001
        logger.warning("Alpaca get_positions failed: %s", e)
        return []


async def _fetch_account() -> Optional[dict]:
    """Same fail-soft pattern as _fetch_positions. Returns None when
    Alpaca is unreachable so the dashboard renders without the equity
    tile rather than 500ing."""
    try:
        client = AlpacaClient()
    except AlpacaClientError as e:
        logger.warning("Alpaca client unavailable for account: %s", e)
        return None
    try:
        return await asyncio.to_thread(client.get_account)
    except Exception as e:  # noqa: BLE001
        logger.warning("Alpaca get_account failed: %s", e)
        return None


def _build_top_picks(picks: list[dict], limit: int) -> list[TopPick]:
    """Project the first ``limit`` picks into the compact dashboard shape.
    Assumes the picks JSON is already sorted by ``rank``."""
    out: list[TopPick] = []
    for p in picks[:limit]:
        if not isinstance(p, dict):
            continue
        rank = p.get("rank") or p.get("_eff_rank")
        if rank is None:
            continue
        out.append(TopPick(
            rank=int(rank),
            ticker=str(p.get("ticker") or ""),
            z_score=_coerce_float(p.get("z_score")),
            sector=p.get("sector"),
            mom_rank=_coerce_int(p.get("mom_rank")),
            qual_rank=_coerce_int(p.get("qual_rank")),
            val_rank=_coerce_int(p.get("val_rank")),
            pead_rank=_coerce_int(p.get("pead_rank")),
        ))
    return out


def _coerce_float(v) -> Optional[float]:
    """JSON-NaN survives json.loads as float('nan'); Pydantic rejects it
    on a float field. Both NaN and None get mapped to None for the wire."""
    if v is None:
        return None
    if isinstance(v, float) and v != v:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _coerce_int(v) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, float) and v != v:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _build_action_counts(
    picks: list[dict], positions: list[dict],
) -> ActionCounts:
    """Set-diff today's picks against current paper holdings. Matches
    the NEW BUY / KEEP / EXIT splits in the morning_briefing markdown.

    Returns both counts and sorted ticker lists so the FE can render
    per-pick badges (held? carried over?) without re-fetching positions.
    """
    pick_set = {
        (p.get("ticker") or "").upper()
        for p in picks if isinstance(p, dict)
    }
    pick_set.discard("")
    pos_set = {
        (p.get("ticker") or "").upper()
        for p in positions if isinstance(p, dict)
    }
    pos_set.discard("")
    new_buys = sorted(pick_set - pos_set)
    keeps = sorted(pick_set & pos_set)
    exits = sorted(pos_set - pick_set)
    return ActionCounts(
        n_new_buys=len(new_buys),
        n_keep=len(keeps),
        n_exit=len(exits),
        new_buy_tickers=new_buys,
        keep_tickers=keeps,
        exit_tickers=exits,
    )


def _sum_unrealized_pl(positions: list[dict]) -> float:
    """Sum unrealized P&L across held positions. AlpacaClient.get_positions
    serializes the field as ``unrealized_pnl`` (with the 'n') in
    src/execution/alpaca.py — not ``unrealized_pl``."""
    total = 0.0
    for p in positions:
        if not isinstance(p, dict):
            continue
        v = p.get("unrealized_pnl")
        if v is None:
            continue
        try:
            total += float(v)
        except (TypeError, ValueError):
            continue
    return total


def _picks_mtime(path: Path) -> Optional[datetime]:
    """File-system mtime as a UTC datetime. Surfacing this lets the FE
    show 'picks generated 3h ago' without an extra round-trip to a
    pipeline-status endpoint."""
    try:
        ts = path.stat().st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc)


@router.get("", response_model=BriefingResponse)
async def get_briefing(
    picks_date: Optional[date] = Query(
        default=None,
        description="YYYY-MM-DD. Defaults to today's UTC date.",
    ),
) -> BriefingResponse:
    picks_path = _today_picks_path(picks_date)

    if not picks_path.exists():
        # Degraded mode: still surface position alerts so stops/targets
        # are visible even on a missed-pipeline day.
        positions, account = await asyncio.gather(
            _fetch_positions(), _fetch_account(),
        )
        analysis_path = _latest_portfolio_analysis()
        analysis_plans: dict[str, dict] = {}
        if analysis_path is not None:
            try:
                data = json.loads(analysis_path.read_text(encoding="utf-8"))
                analysis_plans = {
                    p["ticker"]: p for p in data.get("picks", [])
                }
            except (OSError, json.JSONDecodeError) as e:
                logger.warning("Bad analysis JSON %s: %s", analysis_path, e)
        alerts = _build_position_alerts(positions, analysis_plans)
        n_stops = sum(1 for a in alerts if a.status == "STOP_HIT")
        n_targets = sum(1 for a in alerts if a.status == "TARGET_HIT")
        n_near_stop = sum(1 for a in alerts if a.status == "NEAR_STOP")
        equity = float(account["equity"]) if account else None
        pl_usd = _sum_unrealized_pl(positions)
        pl_pct = (
            (pl_usd / equity * 100.0) if equity and equity > 0 else None
        )
        return BriefingResponse(
            picks_date=None,
            gate_status="no_picks",
            gate_message=f"No picks file at {picks_path.name}",
            recommendation=_recommendation("no_picks", n_stops, n_targets),
            drift_checks=[],
            factor_coverage=[],
            n_picks=0,
            position_alerts=alerts,
            n_stops_hit=n_stops,
            n_targets_hit=n_targets,
            n_near_stop=n_near_stop,
            n_positions=len(positions),
            top_picks=[],
            action_counts=None,
            paper_equity_usd=equity,
            unrealized_pl_usd=pl_usd if positions else None,
            unrealized_pl_pct=pl_pct,
            picks_generated_at=None,
            generated_at=datetime.now(timezone.utc),
        )

    try:
        payload = json.loads(picks_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read picks file {picks_path.name}: {e}",
        )

    picks = payload.get("picks") or []
    n_picks = len(picks)

    # Drift gate -- if compute_drift_report itself blows up (corrupted
    # history file, etc.) treat it as a hard fail rather than masking it.
    drift_report = await asyncio.to_thread(
        compute_drift_report, picks_path, PICKS_DIR, days=30,
    )
    drift_checks = [
        DriftCheckOut(name=c.name, status=c.status, message=c.message)
        for c in drift_report.checks
    ]
    gate_status = drift_report.overall_status
    gate_message = _drift_message(drift_report)

    factor_coverage = _build_factor_coverage(picks)

    # Position alerts -- prefer strategy-recommended levels from the
    # freshest portfolio_analysis JSON; fall back to 8% bands when missing.
    analysis_path = _latest_portfolio_analysis()
    analysis_plans = {}
    if analysis_path is not None:
        try:
            data = json.loads(analysis_path.read_text(encoding="utf-8"))
            analysis_plans = {p["ticker"]: p for p in data.get("picks", [])}
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Bad analysis JSON %s: %s", analysis_path, e)

    positions, account = await asyncio.gather(
        _fetch_positions(), _fetch_account(),
    )
    alerts = _build_position_alerts(positions, analysis_plans)
    n_stops = sum(1 for a in alerts if a.status == "STOP_HIT")
    n_targets = sum(1 for a in alerts if a.status == "TARGET_HIT")
    n_near_stop = sum(1 for a in alerts if a.status == "NEAR_STOP")

    top_picks = _build_top_picks(picks, _TOP_PICKS_FOR_DASHBOARD)
    action_counts = _build_action_counts(picks, positions)
    equity = float(account["equity"]) if account else None
    pl_usd = _sum_unrealized_pl(positions)
    pl_pct = (pl_usd / equity * 100.0) if equity and equity > 0 else None

    return BriefingResponse(
        picks_date=date.fromisoformat(payload["as_of"])
        if payload.get("as_of") else None,
        gate_status=gate_status,
        gate_message=gate_message,
        recommendation=_recommendation(gate_status, n_stops, n_targets),
        drift_checks=drift_checks,
        factor_coverage=factor_coverage,
        n_picks=n_picks,
        position_alerts=alerts,
        n_stops_hit=n_stops,
        n_targets_hit=n_targets,
        n_near_stop=n_near_stop,
        n_positions=len(positions),
        top_picks=top_picks,
        action_counts=action_counts,
        paper_equity_usd=equity,
        unrealized_pl_usd=pl_usd if positions else None,
        unrealized_pl_pct=pl_pct,
        picks_generated_at=_picks_mtime(picks_path),
        generated_at=datetime.now(timezone.utc),
    )
