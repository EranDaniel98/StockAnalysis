"""Factor-backtest endpoints.

Reads the on-disk artifacts written by ``scripts.run_factor_backtest`` and
the various A/B sweep scripts:

  - ``data/factors/sweep/*.json``   — parameter sweep results
  - ``reports/ab_*.json``           — hysteresis / regime / etc. A/B tests

These are the actual research artifacts behind the factor strategy edge
claim. The legacy DB-backed /api/backtests serves the older 5-engine
runs and stays untouched.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter()

SWEEP_DIR = Path("data/factors/sweep")
REPORTS_DIR = Path("reports")

BacktestKind = Literal["sweep", "ab"]


class FactorBacktestSummary(BaseModel):
    """Compact row for the list view. Each field is best-effort — the
    sweep JSON contains them all but A/B files vary; missing fields
    surface as null rather than failing the request."""
    slug: str = Field(description="Filename minus .json — usable as a URL segment.")
    kind: BacktestKind
    strategy: str
    snapshot_id: Optional[str] = None
    window_start: Optional[date] = None
    window_end: Optional[date] = None
    universe_label: Optional[str] = None
    n_tickers: Optional[int] = None

    # Parameters that disambiguate variants in the sweep grid.
    top_decile: Optional[float] = None
    rebalance_days: Optional[int] = None
    regime_filter_enabled: Optional[bool] = None

    # Headline metrics.
    n_trades: Optional[int] = None
    n_rebalances: Optional[int] = None
    total_return_pct: Optional[float] = None
    cagr_pct: Optional[float] = None
    ann_sharpe: Optional[float] = None
    max_drawdown_pct: Optional[float] = None

    # SPY benchmark + alpha.
    spy_total_return_pct: Optional[float] = None
    spy_ann_sharpe: Optional[float] = None
    alpha_vs_spy_pct: Optional[float] = None

    # Walk-forward gate.
    wf_passed: Optional[bool] = None
    wf_mean_sharpe: Optional[float] = None
    wf_min_sharpe: Optional[float] = None
    n_folds: Optional[int] = None

    created_at: datetime = Field(
        description="File mtime as UTC datetime. When the run was last written.",
    )


class WalkForwardFold(BaseModel):
    fold: int
    n_days: Optional[int] = None
    return_pct: Optional[float] = None
    sharpe: Optional[float] = None


class FactorBacktestDetail(FactorBacktestSummary):
    """Detail view extends the summary with the curve + folds + a sample
    of trades. Full payload (raw JSON) is also exposed for power users."""
    walk_forward_folds: list[WalkForwardFold] = Field(default_factory=list)
    equity_curve: list[tuple[str, float]] = Field(
        default_factory=list,
        description="(date_iso, equity) pairs over the run window.",
    )
    spy_equity_curve: list[tuple[str, float]] = Field(
        default_factory=list,
        description=(
            "Synthetic SPY equity over the same dates, normalized to the "
            "strategy's starting cash so the FE can overlay on one axis."
        ),
    )
    rebalance_log: list[dict] = Field(
        default_factory=list,
        description="Per-rebalance summary (size, tickers, turnover).",
    )
    trades_sample: list[dict] = Field(default_factory=list)
    parameters: dict = Field(default_factory=dict)


# ----------------------------- helpers ------------------------------


def _safe_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _safe_int(v) -> Optional[int]:
    f = _safe_float(v)
    if f is None:
        return None
    try:
        return int(f)
    except (TypeError, ValueError):
        return None


def _parse_iso_date(v) -> Optional[date]:
    if not isinstance(v, str):
        return None
    try:
        return date.fromisoformat(v[:10])
    except ValueError:
        return None


def _file_mtime(p: Path) -> datetime:
    try:
        return datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return datetime.now(timezone.utc)


def _summarize_from_payload(
    payload: dict, *, slug: str, kind: BacktestKind, mtime: datetime,
) -> FactorBacktestSummary:
    """Project the on-disk JSON into the wire summary. Tolerates any
    individual field missing; A/B files have slightly different shapes."""
    manifest = payload.get("snapshot_manifest") or {}
    params = payload.get("parameters") or {}
    metrics = payload.get("metrics") or {}
    spy = payload.get("benchmark_spy") or {}
    wf = payload.get("walk_forward") or {}
    folds = wf.get("folds") or []

    return FactorBacktestSummary(
        slug=slug,
        kind=kind,
        strategy=str(payload.get("strategy") or "unknown"),
        snapshot_id=payload.get("snapshot_id"),
        window_start=_parse_iso_date(manifest.get("window_start")),
        window_end=_parse_iso_date(manifest.get("window_end")),
        universe_label=manifest.get("universe_label"),
        n_tickers=_safe_int(manifest.get("n_tickers_with_prices")),
        top_decile=_safe_float(params.get("top_decile")),
        rebalance_days=_safe_int(params.get("rebalance_days")),
        regime_filter_enabled=(
            bool(params["regime_filter_enabled"])
            if "regime_filter_enabled" in params else None
        ),
        n_trades=_safe_int(metrics.get("n_trades")),
        n_rebalances=_safe_int(metrics.get("n_rebalances")),
        total_return_pct=_safe_float(metrics.get("total_return_pct")),
        cagr_pct=_safe_float(metrics.get("cagr_pct")),
        ann_sharpe=_safe_float(metrics.get("ann_sharpe")),
        max_drawdown_pct=_safe_float(metrics.get("max_drawdown_pct")),
        spy_total_return_pct=_safe_float(spy.get("total_return_pct")),
        spy_ann_sharpe=_safe_float(spy.get("ann_sharpe")),
        alpha_vs_spy_pct=_safe_float(payload.get("alpha_vs_spy_pct")),
        wf_passed=bool(wf["passed"]) if "passed" in wf else None,
        wf_mean_sharpe=_safe_float(wf.get("mean_sharpe")),
        wf_min_sharpe=_safe_float(wf.get("min_sharpe")),
        n_folds=len(folds) if folds else None,
        created_at=mtime,
    )


def _scan_dir(
    directory: Path, kind: BacktestKind, prefix: Optional[str] = None,
) -> list[FactorBacktestSummary]:
    """Walk one source directory, parse each .json, build summary rows.
    Files that fail to parse are skipped with a warning rather than 500ing
    the listing endpoint."""
    out: list[FactorBacktestSummary] = []
    if not directory.exists():
        return out
    pattern = f"{prefix}*.json" if prefix else "*.json"
    for path in directory.glob(pattern):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Skipping bad backtest JSON %s: %s", path, e)
            continue
        if not isinstance(payload, dict):
            continue
        # Only include rows that look like factor-backtest output.
        # Required shape: top-level "strategy" + "metrics" dict.
        if "strategy" not in payload or "metrics" not in payload:
            continue
        slug = path.stem
        try:
            out.append(_summarize_from_payload(
                payload, slug=slug, kind=kind, mtime=_file_mtime(path),
            ))
        except Exception as e:  # noqa: BLE001 — defensive: log + skip
            logger.warning("Summary build failed for %s: %s", path, e)
    return out


def _resolve_slug(slug: str) -> Optional[tuple[Path, BacktestKind]]:
    """Map a URL slug back to its (path, kind). Tries the sweep dir
    first, then the ab-test reports. Returns None if neither matches."""
    sweep_path = SWEEP_DIR / f"{slug}.json"
    if sweep_path.exists():
        return sweep_path, "sweep"
    ab_path = REPORTS_DIR / f"{slug}.json"
    if ab_path.exists() and slug.startswith("ab_"):
        return ab_path, "ab"
    return None


def _normalize_spy_curve(
    equity_curve: list, starting_cash: float,
    spy_total_return_pct: Optional[float],
) -> list[tuple[str, float]]:
    """Synthesize a SPY equity curve at the strategy's daily timestamps.

    The on-disk artifact only records SPY's total return (not its daily
    curve), so we cannot draw the true SPY path. Linear-interpolate from
    starting cash to ``starting_cash * (1 + spy_total_return)`` so the FE
    has a same-axis reference line. This is a rough but consistent
    'where SPY ended' marker rather than a true benchmark trajectory.
    """
    if not equity_curve or starting_cash <= 0 or spy_total_return_pct is None:
        return []
    end_value = starting_cash * (1 + spy_total_return_pct / 100.0)
    n = len(equity_curve)
    if n < 2:
        return []
    out: list[tuple[str, float]] = []
    for i, pt in enumerate(equity_curve):
        # equity_curve may be either the raw JSON list-of-lists or the
        # already-parsed list-of-tuples — accept both.
        if not (isinstance(pt, (list, tuple)) and len(pt) >= 1):
            continue
        date_str = str(pt[0])
        frac = i / (n - 1)
        out.append((date_str, starting_cash + frac * (end_value - starting_cash)))
    return out


# ----------------------------- endpoints ------------------------------


@router.get("", response_model=list[FactorBacktestSummary])
async def list_factor_backtests(
    kind: Optional[BacktestKind] = Query(
        default=None,
        description="Filter by source: sweep | ab. Default returns both.",
    ),
    limit: int = Query(default=200, ge=1, le=500),
) -> list[FactorBacktestSummary]:
    """Compact list of every factor-backtest artifact on disk.
    Sorted newest-first by file mtime so the freshest results lead."""
    rows: list[FactorBacktestSummary] = []
    if kind != "ab":
        rows.extend(_scan_dir(SWEEP_DIR, "sweep"))
    if kind != "sweep":
        rows.extend(_scan_dir(REPORTS_DIR, "ab", prefix="ab_"))
    rows.sort(key=lambda r: r.created_at, reverse=True)
    return rows[:limit]


@router.get("/{slug}", response_model=FactorBacktestDetail)
async def get_factor_backtest(slug: str) -> FactorBacktestDetail:
    """Full payload for one artifact. Returns 404 when the slug doesn't
    map to any sweep/ab file on disk."""
    resolved = _resolve_slug(slug)
    if resolved is None:
        raise HTTPException(status_code=404, detail=f"No backtest artifact: {slug}")
    path, kind = resolved
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read {path.name}: {e}",
        )

    summary = _summarize_from_payload(
        payload, slug=slug, kind=kind, mtime=_file_mtime(path),
    )
    wf = payload.get("walk_forward") or {}
    folds_raw = wf.get("folds") or []
    folds: list[WalkForwardFold] = []
    for f in folds_raw:
        if not isinstance(f, dict):
            continue
        folds.append(WalkForwardFold(
            fold=_safe_int(f.get("fold")) or len(folds),
            n_days=_safe_int(f.get("n_days")),
            return_pct=_safe_float(f.get("return_pct")),
            sharpe=_safe_float(f.get("sharpe")),
        ))

    equity_curve_raw = payload.get("equity_curve") or []
    equity_curve: list[tuple[str, float]] = []
    for pt in equity_curve_raw:
        if isinstance(pt, list) and len(pt) >= 2:
            d = str(pt[0])
            v = _safe_float(pt[1])
            if v is not None:
                equity_curve.append((d, v))

    starting_cash = _safe_float((payload.get("parameters") or {}).get("starting_cash")) or 0.0
    spy_curve = _normalize_spy_curve(
        equity_curve, starting_cash, summary.spy_total_return_pct,
    )

    return FactorBacktestDetail(
        **summary.model_dump(),
        walk_forward_folds=folds,
        equity_curve=equity_curve,
        spy_equity_curve=spy_curve,
        rebalance_log=payload.get("rebalance_log") or [],
        trades_sample=payload.get("trades_sample") or [],
        parameters=payload.get("parameters") or {},
    )
