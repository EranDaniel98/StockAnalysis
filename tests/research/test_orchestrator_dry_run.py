"""Dry-run the orchestrator with a faked LLM client.

Verifies the loop without needing an Anthropic API key or hitting the
network. The fake replays a canned tool_use → tool_result → end_turn
script so we can assert on transcript shape, budget accounting, and
persistence.
"""

from __future__ import annotations

import asyncio
import socket
import uuid
from typing import Any

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.config_loader import Config
from src.db.models import ResearchRun
from src.db.session import get_dsn
from src.research_agent.llm_client import LLMResponse
from src.research_agent.orchestrator import run_research


def _postgres_reachable() -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        s.connect(("127.0.0.1", 5432))
        return True
    except OSError:
        return False
    finally:
        s.close()


pytestmark = pytest.mark.skipif(
    not _postgres_reachable(),
    reason="Postgres not reachable — `docker compose up` first",
)


class _FakeAnthropic:
    """Replay a fixed sequence of LLM responses.

    Each turn the orchestrator consumes one entry from ``responses``.
    Use this to script the agent loop exactly — first turn requests a
    tool, second turn ends with a text answer.
    """

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> LLMResponse:
        self.calls.append(kwargs)
        if not self._responses:
            raise RuntimeError("FakeAnthropic ran out of responses")
        return self._responses.pop(0)


@pytest.mark.asyncio
async def test_orchestrator_runs_one_tool_then_synthesizes() -> None:
    """First turn: tool_use(list_recommendations). Second turn: end_turn
    with the final text. Verifies the round-trip + persisted shape."""
    fake = _FakeAnthropic(
        [
            LLMResponse(
                content=[
                    {
                        "type": "tool_use",
                        "id": "tu_test_1",
                        "name": "list_recommendations",
                        "input": {"limit": 5},
                    }
                ],
                stop_reason="tool_use",
                usage={
                    "input_tokens": 1200,
                    "output_tokens": 80,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 1100,
                },
                model="claude-sonnet-4-6",
            ),
            LLMResponse(
                content=[
                    {
                        "type": "text",
                        "text": "Top recent recommendation: AAPL @ score 72.5.",
                    }
                ],
                stop_reason="end_turn",
                usage={
                    "input_tokens": 2500,
                    "output_tokens": 40,
                    "cache_read_input_tokens": 1100,
                    "cache_creation_input_tokens": 0,
                },
                model="claude-sonnet-4-6",
            ),
        ]
    )

    engine = create_async_engine(get_dsn())
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    config = Config()

    try:
        row = await run_research(
            f"smoke test {uuid.uuid4()}",
            sessionmaker=SessionLocal,
            config=config,
            llm=fake,
            max_turns=4,
        )
        assert row.status == "complete"
        assert row.final_answer and "AAPL" in row.final_answer
        assert row.n_turns == 2
        assert row.input_tokens == 3700
        assert row.output_tokens == 120
        assert row.cache_read_tokens == 1100
        assert row.cache_write_tokens == 1100
        # Tool log captured the call
        names = [tc["tool"] for tc in (row.tool_calls or [])]
        assert names == ["list_recommendations"]
        # Cost > 0 because Sonnet pricing is non-trivial
        assert float(row.estimated_cost_usd) > 0

        # Two LLM calls made
        assert len(fake.calls) == 2
        # Second call includes the tool_result the orchestrator built
        msgs = fake.calls[1]["messages"]
        assert any(
            isinstance(m.get("content"), list)
            and any(b.get("type") == "tool_result" for b in m["content"])
            for m in msgs
        )

        await _cleanup(row.id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_orchestrator_marks_budget_exceeded_on_turn_cap() -> None:
    """Force the loop to exceed max_turns and verify the row reflects it."""
    fake = _FakeAnthropic(
        [
            LLMResponse(
                content=[
                    {
                        "type": "tool_use",
                        "id": f"tu_loop_{i}",
                        "name": "list_recommendations",
                        "input": {"limit": 1},
                    }
                ],
                stop_reason="tool_use",
                usage={"input_tokens": 100, "output_tokens": 10},
                model="claude-sonnet-4-6",
            )
            for i in range(5)
        ]
    )

    engine = create_async_engine(get_dsn())
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    config = Config()

    try:
        row = await run_research(
            f"budget cap test {uuid.uuid4()}",
            sessionmaker=SessionLocal,
            config=config,
            llm=fake,
            max_turns=2,
        )
        assert row.status == "budget_exceeded"
        assert row.error and "turn cap" in row.error
        assert row.n_turns == 2

        await _cleanup(row.id)
    finally:
        await engine.dispose()


async def _cleanup(run_id: int) -> None:
    engine = create_async_engine(get_dsn())
    try:
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with Session() as s:
            await s.execute(delete(ResearchRun).where(ResearchRun.id == run_id))
            await s.commit()
    finally:
        await engine.dispose()
