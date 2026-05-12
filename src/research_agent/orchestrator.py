"""Agent loop — Anthropic tool-use until done or capped.

Public entry point: ``run_research(question, *, sessionmaker, config, model=None)``
which:

  1. Inserts a ``research_runs`` row in ``status='pending'``.
  2. Calls Anthropic with the system prompt + tool schemas.
  3. While the model emits ``tool_use`` blocks, executes them in
     parallel and feeds results back. Each tool runs in a fresh DB
     session so a long run doesn't sit on a transaction.
  4. When the model emits ``end_turn`` (or budget is hit), extracts
     the last text block as ``final_answer`` and updates the row.

The orchestrator never raises on a tool failure — it threads the
error back into the transcript as a ``tool_result`` so the agent can
react. The only exceptions that escape are programming bugs and
``BudgetExceededError``, which is converted to ``status='budget_exceeded'``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.db.models import ResearchRun
from src.research_agent.budget import BudgetCounter, BudgetExceededError
from src.research_agent.llm_client import (
    DEFAULT_MODEL,
    AnthropicClient,
    LLMResponse,
)
from src.research_agent.tools import (
    ToolContext,
    tool_by_name,
    tool_specs_for_anthropic,
)

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are the research analyst for a personal quant trading platform.

You have tools that can scan the market, run backtests, query the paper-
trading database, and read the ML feature store. Use them to answer the
user's question with evidence, not vibes.

Workflow:
  1. Decompose the question into 1-3 things you'd need to know.
  2. Pick the cheapest tool first — list_* tools read cached DB rows;
     scan_market and run_backtest are expensive (~10-30s each).
  3. After 2-3 tool calls, synthesize what you found into a final
     answer. Don't loop indefinitely — the user is paying per token.

When you write the final answer:
  - Lead with the punch line (1-2 sentences). The user reads the top
    first and the detail only if interested.
  - Cite specific numbers from tool outputs. Don't say "Sharpe is
    good" — say "Sharpe = 1.61 OOS over 3 years".
  - If a tool returned an error or empty result, say so explicitly.
    Don't fabricate a clean answer from missing data.
  - Format in concise markdown. Tables when there are >3 numbers to
    compare; bullets otherwise.

Strategies available: swing_trading, long_term_growth, short_term_momentum,
value_investing, dividend_income. Default to swing_trading unless the
question implies otherwise.
"""


async def run_research(
    question: str,
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    config,
    llm: Optional[AnthropicClient] = None,
    model: str = DEFAULT_MODEL,
    max_turns: int = 8,
    max_input_tokens: int = 200_000,
    max_output_tokens: int = 8_000,
    notes: Optional[str] = None,
) -> ResearchRun:
    """Drive one research run end-to-end. Returns the persisted row."""
    client = llm or AnthropicClient()
    budget = BudgetCounter(
        model=model,
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        max_turns=max_turns,
    )

    started_at = datetime.now(timezone.utc)
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": question},
    ]
    tool_calls: list[dict[str, Any]] = []

    async with sessionmaker() as db:
        row = ResearchRun(
            question=question,
            model=model,
            status="running",
            transcript=list(messages),
            tool_calls=[],
            n_turns=0,
            started_at=started_at,
            notes=notes,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        run_id = row.id

    ctx = ToolContext(config=config, db_factory=sessionmaker)

    final_answer: Optional[str] = None
    status = "running"
    error: Optional[str] = None

    try:
        tools_schema = tool_specs_for_anthropic()
        while True:
            budget.check()
            response = await client.create(
                model=model,
                system=SYSTEM_PROMPT,
                messages=messages,
                tools=tools_schema,
                max_tokens=2048,
            )
            budget.add_usage(response.usage)
            budget.increment_turn()

            # Persist the assistant turn into the transcript verbatim.
            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                # Either end_turn, max_tokens, or stop_sequence.
                final_answer = _extract_final_text(response)
                status = "complete" if response.stop_reason == "end_turn" else "incomplete"
                break

            tool_results = await _execute_tool_blocks(response.content, ctx, tool_calls)
            messages.append({"role": "user", "content": tool_results})

            # Stream progress to the row so the UI can poll mid-flight.
            await _checkpoint(sessionmaker, run_id, messages, tool_calls, budget, status="running")

    except BudgetExceededError as e:
        status = "budget_exceeded"
        error = str(e)
        logger.warning("research run %d hit budget: %s", run_id, e)
    except Exception as e:  # noqa: BLE001 — keep the partial transcript
        status = "failed"
        error = f"{type(e).__name__}: {e}"
        logger.exception("research run %d crashed", run_id)

    completed_at = datetime.now(timezone.utc)
    async with sessionmaker() as db:
        # Re-fetch and mutate so we don't fight a stale session.
        row = await db.get(ResearchRun, run_id)
        if row is None:
            raise RuntimeError(f"research run {run_id} disappeared mid-flight")
        row.status = status
        row.final_answer = final_answer
        row.transcript = messages
        row.tool_calls = tool_calls
        row.n_turns = budget.turns
        row.input_tokens = budget.input_tokens
        row.output_tokens = budget.output_tokens
        row.cache_read_tokens = budget.cache_read_tokens
        row.cache_write_tokens = budget.cache_write_tokens
        row.estimated_cost_usd = budget.cost_usd
        row.completed_at = completed_at
        row.error = error
        await db.commit()
        await db.refresh(row)
        return row


async def _execute_tool_blocks(
    content: list[dict[str, Any]],
    ctx: ToolContext,
    tool_calls_log: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Run every ``tool_use`` block in one assistant turn concurrently.

    Concurrent because Anthropic models routinely emit multiple tool_use
    blocks per turn (it's the cheaper-than-multi-turn path). Sequential
    here would double the wall-clock for no benefit.
    """
    tasks: list[asyncio.Task] = []
    blocks: list[dict[str, Any]] = []
    for block in content:
        if block.get("type") != "tool_use":
            continue
        blocks.append(block)
        tasks.append(asyncio.create_task(_run_one_tool(block, ctx)))

    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    out: list[dict[str, Any]] = []
    for block, result in zip(blocks, raw_results):
        tool_use_id = block.get("id", "")
        if isinstance(result, Exception):
            payload = {"error": f"{type(result).__name__}: {result}"}
            is_error = True
        else:
            payload = result
            is_error = False
        tool_calls_log.append(
            {
                "tool": block.get("name"),
                "input": block.get("input"),
                "is_error": is_error,
                "result_summary": _summarize(payload),
            }
        )
        out.append(
            {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": json.dumps(payload, default=str),
                "is_error": is_error,
            }
        )
    return out


async def _run_one_tool(block: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    name = block.get("name", "")
    spec = tool_by_name(name)
    if spec is None:
        raise LookupError(f"unknown tool: {name}")
    args = block.get("input") or {}
    return await spec.run(args, ctx)


def _extract_final_text(response: LLMResponse) -> Optional[str]:
    """Concatenate all text blocks in the model's last response — that's
    the agent's final synthesis."""
    parts = [b.get("text", "") for b in response.content if b.get("type") == "text"]
    text = "\n".join(p for p in parts if p)
    return text or None


def _summarize(payload: Any, *, limit: int = 400) -> str:
    """Compact representation of a tool result for the tool_calls log.
    Keeps the registry row scannable without blowing up storage."""
    try:
        text = json.dumps(payload, default=str)
    except Exception:  # noqa: BLE001
        text = str(payload)
    return text if len(text) <= limit else text[: limit - 1] + "…"


async def _checkpoint(
    sessionmaker: async_sessionmaker[AsyncSession],
    run_id: int,
    messages: list[dict[str, Any]],
    tool_calls: list[dict[str, Any]],
    budget: BudgetCounter,
    *,
    status: str,
) -> None:
    """Persist intermediate state every turn so a long run can be
    inspected from the UI without waiting for the final write."""
    async with sessionmaker() as db:
        row = await db.get(ResearchRun, run_id)
        if row is None:
            return
        row.status = status
        row.transcript = messages
        row.tool_calls = tool_calls
        row.n_turns = budget.turns
        row.input_tokens = budget.input_tokens
        row.output_tokens = budget.output_tokens
        row.cache_read_tokens = budget.cache_read_tokens
        row.cache_write_tokens = budget.cache_write_tokens
        row.estimated_cost_usd = budget.cost_usd
        await db.commit()
