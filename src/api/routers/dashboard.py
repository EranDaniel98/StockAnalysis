"""/api/dashboard — home-page aggregated view.

Aggregates the most-recent ``scan_run`` per strategy + the most-recent
A/B sweep performance from ``data/sweep_battery/`` so the home page can
answer "what should I trade today?" in one network round-trip.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_config, get_db_session
from src.api.schemas.dashboard import (
    DashboardPick,
    DashboardResponse,
    StrategyCard,
)
from src.config_loader import Config
from src.db.models import ScanRun

logger = logging.getLogger(__name__)
router = APIRouter()


SWEEP_BATTERY_ROOT = Path("data/sweep_battery")
KNOWN_UNIVERSES = ("russell_1000", "themes", "value_cohort", "watchlist")


def _num_or_none(v) -> Optional[float]:
    """Engine emits risk fields as either flat floats or nested
    ``{price, method, ...}`` dicts. Normalize both shapes for the
    dashboard table."""
    if isinstance(v, (int, float)) and v == v:  # NaN check
        return float(v)
    if isinstance(v, dict):
        for key in ("price", "current_price"):
            x = v.get(key)
            if isinstance(x, (int, float)) and x == x:
                return float(x)
    return None


def _pick_from_rec(rec: dict, strategy: str) -> DashboardPick:
    rm = rec.get("risk_management") or {}
    entry = _num_or_none(rm.get("entry_price")) or _num_or_none(
        rm.get("current_price")
    )
    return DashboardPick(
        ticker=str(rec.get("ticker", "")),
        name=str(rec.get("name", "")),
        sector=str(rec.get("sector", "Unknown")),
        action=rec.get("action", "HOLD"),
        composite_score=float(rec.get("composite_score", 50.0)),
        strategy=strategy,
        entry_price=entry,
        stop_loss=_num_or_none(rm.get("stop_loss")),
        take_profit=_num_or_none(rm.get("take_profit")),
    )


def _load_sweep_performance(strategy: str) -> tuple[
    Optional[float], Optional[float], Optional[float], Optional[str]
]:
    """Read the most-recent A/B sweep result for this strategy and return
    the off-mode (baseline) OOS Sharpe + win rate. Returns (None, None,
    None, None) if no sweep file exists.

    Scans the well-known universes in priority order (russell_1000 is the
    most informative; themes is fallback). The "off" row is the baseline
    — what the strategy produces without any insider weighting.
    """
    for universe in KNOWN_UNIVERSES:
        path = SWEEP_BATTERY_ROOT / f"sweep_{universe}_{strategy}_2y.json"
        if not path.exists():
            continue
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("failed to parse %s: %s", path, e)
            continue
        if not rows:
            continue
        off = next((r for r in rows if r.get("mode") == "off"), rows[0])
        return (
            off.get("oos_sharpe"),
            off.get("full_sharpe"),
            off.get("win_rate_pct"),
            universe,
        )
    return None, None, None, None


@router.get("", response_model=DashboardResponse)
async def get_dashboard(
    top_n_per_strategy: int = Query(default=3, ge=1, le=20),
    cross_strategy_top_n: int = Query(default=5, ge=1, le=20),
    db: AsyncSession = Depends(get_db_session),
    config: Config = Depends(get_config),
) -> DashboardResponse:
    """Aggregate per-strategy and cross-strategy picks.

    For each strategy declared in ``config/strategies.yaml``, finds the
    most-recent ``scan_run`` and pulls the top BUY/STRONG BUY rows.
    Cross-strategy ``top_picks`` are the union of all strategies'
    BUYs, deduplicated by ticker (the highest-scoring strategy wins on
    collision) and capped at ``cross_strategy_top_n``.
    """
    strategy_names = config.get_strategy_names()

    cards: list[StrategyCard] = []
    cross_pool: dict[str, DashboardPick] = {}

    for strategy in strategy_names:
        try:
            cfg_strategy = config.get_strategy(strategy)
        except KeyError:
            continue

        # Find the most recent scan_run for this strategy.
        stmt = (
            select(ScanRun)
            .where(ScanRun.strategy == strategy)
            .order_by(desc(ScanRun.scan_timestamp))
            .limit(1)
        )
        row = (await db.execute(stmt)).scalar_one_or_none()

        top_picks: list[DashboardPick] = []
        n_buys = 0
        last_scan_at = None
        last_run_id = None
        last_universe = None
        if row is not None:
            last_scan_at = row.scan_timestamp
            last_run_id = row.run_id
            recs = row.recommendations or []
            buys = [
                r for r in recs if r.get("action") in ("BUY", "STRONG BUY")
            ]
            buys.sort(key=lambda r: -float(r.get("composite_score", 0)))
            n_buys = len(buys)
            top_picks = [
                _pick_from_rec(r, strategy) for r in buys[:top_n_per_strategy]
            ]
            # Universe label here is the run_id (we re-purposed the column
            # in scan_runs). Inferring the actual universe from row
            # contents would be heuristic; skip for now.

            # Feed every BUY into the cross-strategy pool — dedup keeps
            # the highest-scoring strategy for each ticker.
            for buy in buys:
                pick = _pick_from_rec(buy, strategy)
                existing = cross_pool.get(pick.ticker)
                if existing is None or pick.composite_score > existing.composite_score:
                    cross_pool[pick.ticker] = pick

        oos, full, win, sweep_universe = _load_sweep_performance(strategy)

        cards.append(StrategyCard(
            strategy=strategy,
            description=str(cfg_strategy.get("description", "")),
            horizon=str(cfg_strategy.get("time_horizon", "")),
            last_scan_at=last_scan_at,
            last_scan_run_id=last_run_id,
            last_scan_universe=last_universe,
            n_buys=n_buys,
            top_picks=top_picks,
            oos_sharpe=oos,
            full_sharpe=full,
            win_rate_pct=win,
            sweep_universe=sweep_universe,
        ))

    cross_sorted = sorted(
        cross_pool.values(), key=lambda p: -p.composite_score
    )[:cross_strategy_top_n]

    return DashboardResponse(
        top_picks=cross_sorted,
        strategies=cards,
        generated_at=datetime.now(timezone.utc),
    )
