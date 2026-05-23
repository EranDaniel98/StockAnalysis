"""IC-report endpoints.

Surfaces ``reports/analyzer_ic_*.json`` — the alphalens-style IC sweeps
written by ``scripts.analyzer_ic_report``. These are the artifacts the
memory notes (analyzer_ic_2022_2024, ic_regime_vix_2022_2024) refer to;
the legacy /api/diagnostics endpoint runs an on-demand 5-engine version
which we've otherwise demoted.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter()

REPORTS_DIR = Path("reports")
_GLOB = "analyzer_ic_*.json"


class IcCellMetrics(BaseModel):
    """One (factor, horizon) cell — the alphalens raw stats."""
    ic_mean: float
    ic_std: float
    ic_ir: float
    t_stat: float
    p_value: float
    n_periods: int
    top_minus_bottom_pct: float


class IcFactorRow(BaseModel):
    factor: str
    n_observations: int
    by_horizon: dict[str, IcCellMetrics] = Field(default_factory=dict)


class IcReportSummary(BaseModel):
    slug: str = Field(description="Filename minus .json — URL slug.")
    universe: str
    strategy: str
    window_start: Optional[date] = None
    window_end: Optional[date] = None
    periods: list[int] = Field(default_factory=list)
    quantiles: int
    bonferroni_k: int = Field(
        description=(
            "Number of independent tests for multiple-comparison correction. "
            "Adjusted significance = raw p * bonferroni_k."
        ),
    )
    panel_rows: int = Field(
        description="Rows in the (date, ticker) panel underlying this report.",
    )
    n_factors: int
    horizons: list[str] = Field(
        default_factory=list,
        description="Per-horizon labels actually present in the report.",
    )
    regime_split: Optional[str] = Field(
        default=None,
        description="Split key when this is a regime-conditional report (e.g. 'vix').",
    )
    regimes: list[str] = Field(
        default_factory=list,
        description="Regime bucket names when regime_split is set.",
    )
    ran_at: datetime


class IcReportDetail(IcReportSummary):
    per_factor: list[IcFactorRow] = Field(
        default_factory=list,
        description="Unconditional per-factor rows. Empty on regime reports.",
    )
    per_regime: dict[str, list[IcFactorRow]] = Field(
        default_factory=dict,
        description="factor rows keyed by regime bucket; empty on unconditional reports.",
    )


# ----------------------------- helpers ------------------------------


def _safe_float(v) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(f) or math.isinf(f):
        return 0.0
    return f


def _safe_int(v) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _parse_iso_date(v) -> Optional[date]:
    if not isinstance(v, str):
        return None
    try:
        return date.fromisoformat(v[:10])
    except ValueError:
        return None


def _parse_iso_datetime(v) -> datetime:
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _parse_cell(raw: dict) -> IcCellMetrics:
    """Per-cell parse with NaN tolerance — alphalens emits NaN p-values
    when n_periods is too small, and Pydantic would reject those."""
    return IcCellMetrics(
        ic_mean=_safe_float(raw.get("ic_mean")),
        ic_std=_safe_float(raw.get("ic_std")),
        ic_ir=_safe_float(raw.get("ic_ir")),
        t_stat=_safe_float(raw.get("t_stat")),
        p_value=_safe_float(raw.get("p_value")),
        n_periods=_safe_int(raw.get("n_periods")),
        top_minus_bottom_pct=_safe_float(raw.get("top_minus_bottom_pct")),
    )


def _parse_factor_row(raw: dict) -> Optional[IcFactorRow]:
    if not isinstance(raw, dict) or "factor" not in raw:
        return None
    by_horizon_raw = raw.get("by_horizon") or {}
    by_horizon: dict[str, IcCellMetrics] = {}
    if isinstance(by_horizon_raw, dict):
        for h_label, cell in by_horizon_raw.items():
            if isinstance(cell, dict):
                by_horizon[str(h_label)] = _parse_cell(cell)
    return IcFactorRow(
        factor=str(raw.get("factor")),
        n_observations=_safe_int(raw.get("n_observations")),
        by_horizon=by_horizon,
    )


def _collect_horizons(factor_rows: list[IcFactorRow]) -> list[str]:
    """Union of horizon labels seen across rows, sorted by the trailing
    integer so '5D' < '11D' < '23D' < '44D'."""
    seen: set[str] = set()
    for row in factor_rows:
        seen.update(row.by_horizon.keys())

    def _key(label: str) -> tuple[int, str]:
        digits = "".join(c for c in label if c.isdigit())
        try:
            return (int(digits), label) if digits else (10**9, label)
        except ValueError:
            return (10**9, label)

    return sorted(seen, key=_key)


def _build_summary(payload: dict, slug: str) -> IcReportSummary:
    window = payload.get("window") or {}
    per_factor = payload.get("per_factor") or []
    per_regime = payload.get("per_regime") or {}
    factor_rows: list[IcFactorRow] = []
    regime_names: list[str] = []
    if isinstance(per_factor, list) and per_factor:
        for r in per_factor:
            row = _parse_factor_row(r)
            if row is not None:
                factor_rows.append(row)
    if isinstance(per_regime, dict) and per_regime:
        regime_names = list(per_regime.keys())
        # For the summary's horizons/n_factors counts on regime reports,
        # collapse across regimes — they share the same factor list.
        first_regime = next(iter(per_regime.values()), [])
        if isinstance(first_regime, list):
            for r in first_regime:
                row = _parse_factor_row(r)
                if row is not None and not any(
                    f.factor == row.factor for f in factor_rows
                ):
                    factor_rows.append(row)
    horizons = _collect_horizons(factor_rows)
    periods_raw = payload.get("periods") or []
    periods: list[int] = []
    if isinstance(periods_raw, list):
        for p in periods_raw:
            i = _safe_int(p)
            if i:
                periods.append(i)
    return IcReportSummary(
        slug=slug,
        universe=str(payload.get("universe") or "unknown"),
        strategy=str(payload.get("strategy") or "unknown"),
        window_start=_parse_iso_date(window.get("start")),
        window_end=_parse_iso_date(window.get("end")),
        periods=periods,
        quantiles=_safe_int(payload.get("quantiles")) or 5,
        bonferroni_k=_safe_int(payload.get("bonferroni_k")) or 1,
        panel_rows=_safe_int(payload.get("panel_rows")),
        n_factors=len(factor_rows),
        horizons=horizons,
        regime_split=(
            str(payload["regime_split"])
            if payload.get("regime_split") else None
        ),
        regimes=regime_names,
        ran_at=_parse_iso_datetime(payload.get("ran_at")),
    )


# ----------------------------- endpoints ------------------------------


@router.get("", response_model=list[IcReportSummary])
async def list_ic_reports(
    limit: int = Query(default=50, ge=1, le=200),
) -> list[IcReportSummary]:
    """Compact list of every analyzer_ic_*.json on disk, newest first.

    Each row tells the FE which dimensions a report covers — factors,
    horizons, regime split — so the list view can group/filter without
    loading the full payload.
    """
    out: list[IcReportSummary] = []
    if not REPORTS_DIR.exists():
        return out
    for path in REPORTS_DIR.glob(_GLOB):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Bad IC report %s: %s", path, e)
            continue
        if not isinstance(payload, dict):
            continue
        try:
            out.append(_build_summary(payload, slug=path.stem))
        except Exception as e:  # noqa: BLE001
            logger.warning("Summary parse failed for %s: %s", path, e)
    out.sort(key=lambda r: r.ran_at, reverse=True)
    return out[:limit]


@router.get("/{slug}", response_model=IcReportDetail)
async def get_ic_report(slug: str) -> IcReportDetail:
    """Full per-factor (and per-regime, when present) breakdown."""
    path = REPORTS_DIR / f"{slug}.json"
    if not path.exists() or not path.name.startswith("analyzer_ic_"):
        raise HTTPException(status_code=404, detail=f"No IC report: {slug}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to read {path.name}: {e}",
        )

    summary = _build_summary(payload, slug=slug)

    per_factor: list[IcFactorRow] = []
    per_regime: dict[str, list[IcFactorRow]] = {}
    raw_pf = payload.get("per_factor") or []
    if isinstance(raw_pf, list):
        for r in raw_pf:
            row = _parse_factor_row(r)
            if row is not None:
                per_factor.append(row)
    raw_pr = payload.get("per_regime") or {}
    if isinstance(raw_pr, dict):
        for regime_name, rows in raw_pr.items():
            if not isinstance(rows, list):
                continue
            parsed: list[IcFactorRow] = []
            for r in rows:
                row = _parse_factor_row(r)
                if row is not None:
                    parsed.append(row)
            per_regime[str(regime_name)] = parsed

    return IcReportDetail(
        **summary.model_dump(),
        per_factor=per_factor,
        per_regime=per_regime,
    )
