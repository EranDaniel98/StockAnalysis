"""In-process tool registry for the research agent.

Each tool has three pieces:

  1. ``name`` and ``description`` — what Claude sees in the schema.
  2. ``input_schema`` — JSONSchema that Claude must match.
  3. an async ``run`` callable that takes parsed args + the request scope
     (config, db session) and returns a JSON-serializable result.

Why in-process and not a separate MCP server: the user is local-only,
the tools live in the same Python process as the API, and the MCP
network protocol adds latency + a moving target for the schema. We can
externalize later by re-exporting these tools through ``mcp`` — the
shape already matches.

Tools intentionally summarize their outputs aggressively. Anthropic's
input-token bill scales with what we return; raw scan dumps blow up
into 50K tokens trivially. Every tool truncates to the highest-signal
fields and points the orchestrator at row IDs it can fetch later.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

import pandas as pd
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config_loader import Config
from src.db.models import (
    BacktestRun,
    FactorSnapshot,
    PaperRecommendation,
    PaperTrade,
    ScanRun,
)

logger = logging.getLogger(__name__)


@dataclass
class ToolContext:
    """Per-call scope handed to every tool implementation.

    Lifetimes: ``config`` is the process-wide singleton (cheap to share),
    ``session`` is the per-request DB session. The agent loop creates a
    new ``session`` for each tool call so a long-running run doesn't sit
    on a transaction.
    """

    config: Config
    db_factory: Callable[[], "AsyncSession"]
    """Returns a fresh AsyncSession context-manager-ready object."""


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    run: Callable[[dict[str, Any], ToolContext], Awaitable[dict[str, Any]]]

    def to_anthropic(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


# ─── individual tool implementations ────────────────────────────────────────


async def _tool_scan_market(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """Run a market scan. Returns top-N picks with composite scores."""
    # Lazy import — src.api.* would otherwise pull create_app at module
    # import time, which closes a cycle when the research router imports
    # the orchestrator.
    from src.api.services.scan_runner import run_scan_sync

    strategy_name = args.get("strategy", "swing_trading")
    theme = args.get("theme")
    top = int(args.get("top") or 10)

    try:
        strategy = ctx.config.get_strategy(strategy_name)
    except KeyError:
        return {"error": f"unknown strategy '{strategy_name}'"}

    raw = await asyncio.to_thread(
        run_scan_sync, ctx.config, strategy, theme=theme, fresh=False
    )
    picks = raw[:top]
    return {
        "n_total_candidates": len(raw),
        "n_returned": len(picks),
        "strategy": strategy_name,
        "theme": theme,
        "picks": [
            {
                "ticker": p.get("ticker"),
                "action": p.get("action"),
                "composite_score": round(float(p.get("composite_score", 0)), 1),
                "sector": p.get("sector"),
                "confidence": p.get("confidence"),
                # First 2 reasoning lines only — keeps the response compact.
                "reasoning": (p.get("reasoning") or [])[:2],
            }
            for p in picks
        ],
    }


async def _tool_run_backtest(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """Walk-forward backtest. Returns headline metrics, not the trade log."""
    from src.api.schemas.backtest import BacktestRequest
    from src.api.services.backtest_runner import run_backtest_sync

    try:
        body = BacktestRequest(
            strategy=args.get("strategy", "swing_trading"),
            years=int(args.get("years", 3)),
            min_score=args.get("min_score"),
            universe=args.get("universe", "themes"),
        )
    except Exception as e:  # pydantic ValidationError → readable string
        return {"error": f"invalid args: {e}"}

    result = await asyncio.to_thread(run_backtest_sync, ctx.config, body)
    if "error" in result:
        return result

    summary = result.get("summary") or result.get("metrics") or {}
    return {
        "strategy": body.strategy,
        "window_start": result.get("window_start"),
        "window_end": result.get("window_end"),
        "universe": result.get("universe_label"),
        "n_trades": result.get("n_trades"),
        "metrics": {
            k: round(v, 4) if isinstance(v, (int, float)) else v
            for k, v in summary.items()
            if k
            in {
                "total_return_pct",
                "annualized_return_pct",
                "sharpe",
                "sortino",
                "max_drawdown_pct",
                "win_rate",
                "n_trades",
                "calmar",
            }
        },
    }


async def _tool_get_portfolio_status(
    args: dict[str, Any], ctx: ToolContext
) -> dict[str, Any]:
    """Live Alpaca paper account snapshot — account fields + open positions.

    Skips back to a DB read of closed trade history if Alpaca credentials
    are missing, so the agent stays useful in offline tests.
    """
    from src.execution.alpaca import AlpacaClient, AlpacaClientError

    try:
        client = await asyncio.to_thread(AlpacaClient)
        account = await asyncio.to_thread(client.get_account)
        positions = await asyncio.to_thread(client.get_positions)
    except AlpacaClientError as e:
        logger.info("portfolio_status: Alpaca unreachable (%s) — falling back to DB", e)
        return await _portfolio_status_db_fallback(ctx)

    return {
        "source": "alpaca",
        "account": {
            "equity": float(account.get("equity", 0)),
            "cash": float(account.get("cash", 0)),
            "buying_power": float(account.get("buying_power", 0)),
            "portfolio_value": float(account.get("portfolio_value", 0)),
            "status": account.get("status"),
        },
        "n_positions": len(positions),
        "positions": [
            {
                "ticker": p.get("ticker"),
                "shares": float(p.get("shares", 0)),
                "avg_price": float(p.get("avg_price", 0)),
                "market_value": float(p.get("market_value") or 0),
                "unrealized_pnl_pct": float(p.get("unrealized_pnl_pct") or 0),
            }
            for p in positions
        ],
    }


async def _portfolio_status_db_fallback(ctx: ToolContext) -> dict[str, Any]:
    """When Alpaca creds aren't set, report recent closed paper-trade
    history so the agent still has something to ground on."""
    async with ctx.db_factory() as db:
        stmt = select(PaperTrade).order_by(desc(PaperTrade.exit_at)).limit(20)
        rows = (await db.execute(stmt)).scalars().all()

    return {
        "source": "db_fallback",
        "n_recent_closed_trades": len(rows),
        "recent_closed_trades": [
            {
                "ticker": r.ticker,
                "qty": float(r.qty),
                "entry_price": float(r.entry_price),
                "exit_price": float(r.exit_price),
                "pnl_pct": float(r.pnl_pct),
                "entry_at": r.entry_at.isoformat(),
                "exit_at": r.exit_at.isoformat(),
                "composite_score": float(r.composite_score)
                if r.composite_score is not None
                else None,
            }
            for r in rows
        ],
    }


async def _tool_list_recommendations(
    args: dict[str, Any], ctx: ToolContext
) -> dict[str, Any]:
    """List recent paper-trade recommendations. ``submitted_only=True``
    narrows to ones that actually went to Alpaca."""
    limit = int(args.get("limit") or 20)
    ticker = args.get("ticker")
    submitted_only = bool(args.get("submitted_only", False))

    async with ctx.db_factory() as db:
        stmt = select(PaperRecommendation).order_by(
            desc(PaperRecommendation.scan_timestamp)
        )
        if ticker:
            stmt = stmt.where(PaperRecommendation.ticker == ticker.upper())
        if submitted_only:
            stmt = stmt.where(PaperRecommendation.submitted == 1)
        stmt = stmt.limit(limit)
        rows = (await db.execute(stmt)).scalars().all()

    return {
        "n_returned": len(rows),
        "recommendations": [
            {
                "id": r.id,
                "ticker": r.ticker,
                "strategy": r.strategy,
                "action": r.action,
                "composite_score": float(r.composite_score),
                "submitted": bool(r.submitted),
                "scan_timestamp": r.scan_timestamp.isoformat(),
                "entry_price": float(r.entry_price) if r.entry_price else None,
                "stop_loss": float(r.stop_loss) if r.stop_loss else None,
                "take_profit": float(r.take_profit) if r.take_profit else None,
            }
            for r in rows
        ],
    }


async def _tool_factor_history(
    args: dict[str, Any], ctx: ToolContext
) -> dict[str, Any]:
    """Recent factor snapshots for one ticker — the analyzer time-series
    a model would have seen at each as_of date."""
    ticker = (args.get("ticker") or "").upper()
    if not ticker:
        return {"error": "ticker is required"}
    limit = int(args.get("limit") or 12)
    factor_set = args.get("factor_set") or "sub_scores_v1"

    async with ctx.db_factory() as db:
        stmt = (
            select(FactorSnapshot)
            .where(FactorSnapshot.ticker == ticker)
            .where(FactorSnapshot.factor_set == factor_set)
            .order_by(desc(FactorSnapshot.as_of))
            .limit(limit)
        )
        rows = (await db.execute(stmt)).scalars().all()

    return {
        "ticker": ticker,
        "factor_set": factor_set,
        "n_returned": len(rows),
        "snapshots": [
            {
                "as_of": r.as_of.isoformat(),
                "values": r.values,
                "z_scores": r.z_scores,
            }
            for r in rows
        ],
    }


async def _tool_list_backtests(
    args: dict[str, Any], ctx: ToolContext
) -> dict[str, Any]:
    """Most recent backtest_runs rows — for comparing strategies without
    re-running them."""
    limit = int(args.get("limit") or 10)
    strategy = args.get("strategy")

    async with ctx.db_factory() as db:
        stmt = select(BacktestRun).order_by(desc(BacktestRun.created_at))
        if strategy:
            stmt = stmt.where(BacktestRun.strategy == strategy)
        stmt = stmt.limit(limit)
        rows = (await db.execute(stmt)).scalars().all()

    return {
        "n_returned": len(rows),
        "runs": [
            {
                "id": r.id,
                "strategy": r.strategy,
                "window_start": r.window_start.isoformat()
                if r.window_start
                else None,
                "window_end": r.window_end.isoformat() if r.window_end else None,
                "summary": (r.result or {}).get("summary")
                or (r.result or {}).get("metrics")
                or {},
            }
            for r in rows
        ],
    }


async def _tool_search_filings(
    args: dict[str, Any], ctx: ToolContext
) -> dict[str, Any]:
    """k-NN search over the EDGAR filings_corpus."""
    from datetime import date as _date

    from src.research_agent.rag.search import search_filings

    query = (args.get("query") or "").strip()
    if not query:
        return {"error": "query is required"}
    top_k = int(args.get("top_k") or 5)
    ticker = args.get("ticker")
    form = args.get("form")
    after_raw = args.get("filed_after")
    after: _date | None = None
    if after_raw:
        try:
            after = _date.fromisoformat(after_raw)
        except ValueError:
            return {"error": f"filed_after must be YYYY-MM-DD, got {after_raw!r}"}

    async with ctx.db_factory() as db:
        hits = await search_filings(
            db,
            query,
            top_k=top_k,
            ticker=ticker.upper() if ticker else None,
            form=form,
            after=after,
        )

    return {
        "query": query,
        "n_hits": len(hits),
        "hits": [
            {
                "ticker": h.ticker,
                "form": h.form,
                "filing_date": h.filing_date.isoformat(),
                "accession_no": h.accession_no,
                "chunk_index": h.chunk_index,
                "score": round(h.score, 4),
                # Truncate excerpts so the agent doesn't get token-flooded
                # by a single tool call. 600 chars ≈ 150 tokens.
                "excerpt": h.chunk_text[:600],
            }
            for h in hits
        ],
    }


async def _tool_list_scan_runs(
    args: dict[str, Any], ctx: ToolContext
) -> dict[str, Any]:
    """Most recent scan_runs — to compare what the scanner has flagged
    over time without re-scanning."""
    limit = int(args.get("limit") or 10)
    strategy = args.get("strategy")

    async with ctx.db_factory() as db:
        stmt = select(ScanRun).order_by(desc(ScanRun.scan_timestamp))
        if strategy:
            stmt = stmt.where(ScanRun.strategy == strategy)
        stmt = stmt.limit(limit)
        rows = (await db.execute(stmt)).scalars().all()

    return {
        "n_returned": len(rows),
        "runs": [
            {
                "run_id": r.universe_label,
                "strategy": r.strategy,
                "scan_timestamp": r.scan_timestamp.isoformat(),
                "n_candidates": r.n_candidates,
                "top_picks": [
                    {
                        "ticker": rec.get("ticker"),
                        "composite_score": rec.get("composite_score"),
                        "action": rec.get("action"),
                    }
                    for rec in (r.recommendations or [])[:5]
                ],
            }
            for r in rows
        ],
    }


# ─── registry ───────────────────────────────────────────────────────────────


TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="scan_market",
        description=(
            "Run a live market scan with the existing analyzer pipeline. "
            "Returns the top-N tickers ranked by composite score for the "
            "requested strategy. Expensive (~10s+); only call when you need "
            "current rankings — for recent rankings use list_scan_runs."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "strategy": {
                    "type": "string",
                    "description": "Strategy name from config/strategies.yaml. "
                    "Examples: swing_trading, long_term_growth, short_term_momentum, "
                    "value_investing.",
                    "default": "swing_trading",
                },
                "theme": {
                    "type": ["string", "null"],
                    "description": "Optional theme filter from config/sectors.yaml. "
                    "Examples: artificial_intelligence, semiconductors, "
                    "robotics_automation.",
                },
                "top": {
                    "type": "integer",
                    "description": "Max picks to return. Default 10, max 30.",
                    "minimum": 1,
                    "maximum": 30,
                },
            },
        },
        run=_tool_scan_market,
    ),
    ToolSpec(
        name="run_backtest",
        description=(
            "Run a walk-forward backtest of a strategy. Returns headline "
            "Sharpe / drawdown / win-rate. Expensive (~30s); prefer "
            "list_backtests for historical comparison."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "strategy": {"type": "string", "default": "swing_trading"},
                "years": {
                    "type": "integer",
                    "default": 3,
                    "minimum": 1,
                    "maximum": 10,
                },
                "universe": {
                    "type": "string",
                    "enum": ["watchlist", "portfolio", "themes"],
                    "default": "themes",
                },
                "min_score": {
                    "type": ["number", "null"],
                    "description": "Composite-score gate. Defaults to the strategy's.",
                },
            },
        },
        run=_tool_run_backtest,
    ),
    ToolSpec(
        name="get_portfolio_status",
        description=(
            "Snapshot of currently open paper-trade positions: ticker, "
            "shares, entry price, composite score at entry. Use this to "
            "ground recommendations against the actual book."
        ),
        input_schema={"type": "object", "properties": {}},
        run=_tool_get_portfolio_status,
    ),
    ToolSpec(
        name="list_recommendations",
        description=(
            "Recent paper-trade recommendations. Filter by ticker, or "
            "submitted_only=true to see only orders that actually went to "
            "Alpaca. Defaults to 20 most recent."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "ticker": {"type": ["string", "null"]},
                "submitted_only": {"type": "boolean", "default": False},
                "limit": {"type": "integer", "default": 20, "maximum": 100},
            },
        },
        run=_tool_list_recommendations,
    ),
    ToolSpec(
        name="get_factor_history",
        description=(
            "Time-series of sub-scores for one ticker from the ML feature "
            "store (factor_snapshots). Returns raw values + cross-sectional "
            "z-scores per analyzer. Useful for explaining why composite "
            "ranking moved."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "limit": {"type": "integer", "default": 12, "maximum": 100},
                "factor_set": {"type": "string", "default": "sub_scores_v1"},
            },
            "required": ["ticker"],
        },
        run=_tool_factor_history,
    ),
    ToolSpec(
        name="list_backtests",
        description=(
            "Recent backtest_runs rows. Cheap — no recomputation. Use "
            "before calling run_backtest to avoid duplicating work."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "strategy": {"type": ["string", "null"]},
                "limit": {"type": "integer", "default": 10, "maximum": 50},
            },
        },
        run=_tool_list_backtests,
    ),
    ToolSpec(
        name="search_filings",
        description=(
            "Semantic search over the EDGAR filings RAG corpus (10-K / "
            "10-Q / 8-K). Returns the top-K most relevant chunks with "
            "filing metadata + a 600-char excerpt each. Use this when the "
            "question is about *what a company said* in its filings — "
            "risk factors, MD&A commentary, business descriptions. Filter "
            "by ticker / form / filing date when the question is scoped."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural-language query. The retriever "
                    "embeds this and matches it semantically — phrase it "
                    "the way the filing would.",
                },
                "ticker": {"type": ["string", "null"]},
                "form": {
                    "type": ["string", "null"],
                    "description": "One of 10-K, 10-Q, 8-K.",
                },
                "filed_after": {
                    "type": ["string", "null"],
                    "description": "ISO date (YYYY-MM-DD). Skip older filings.",
                },
                "top_k": {
                    "type": "integer",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 20,
                },
            },
            "required": ["query"],
        },
        run=_tool_search_filings,
    ),
    ToolSpec(
        name="list_scan_runs",
        description=(
            "Recent scan_runs rows. Cheap — no scan recomputation. Use "
            "instead of scan_market when the question is about historical "
            "rankings."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "strategy": {"type": ["string", "null"]},
                "limit": {"type": "integer", "default": 10, "maximum": 50},
            },
        },
        run=_tool_list_scan_runs,
    ),
]


def tool_specs_for_anthropic() -> list[dict[str, Any]]:
    return [t.to_anthropic() for t in TOOLS]


def tool_by_name(name: str) -> Optional[ToolSpec]:
    for t in TOOLS:
        if t.name == name:
            return t
    return None
