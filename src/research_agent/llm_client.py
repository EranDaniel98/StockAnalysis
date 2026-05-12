"""Thin async wrapper around the Anthropic SDK.

Why a wrapper:
  - explicit timeout + retry policy (the SDK retries by default but
    not on the time budget we want for a research agent)
  - prompt caching of the system prompt (cuts cost ~10x on repeated
    runs that share the same tool schemas)
  - a single seam to swap to streaming later (Phase 5.2)
  - a single seam to inject a fake client in tests
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

from anthropic import AsyncAnthropic, AsyncMessageStream

logger = logging.getLogger(__name__)


DEFAULT_MODEL = "claude-sonnet-4-6"
HARDER_MODEL = "claude-opus-4-7"

# Single SDK timeout per call; the orchestrator wraps multiple calls
# under its own wall-clock budget too.
DEFAULT_TIMEOUT_S = 120.0
DEFAULT_MAX_RETRIES = 2


@dataclass
class LLMResponse:
    """Subset of the Anthropic Message shape the orchestrator needs."""

    content: list[dict[str, Any]]
    """List of content blocks (text / tool_use). Already converted from
    SDK objects to plain dicts so we can persist + replay."""

    stop_reason: str
    """One of: ``end_turn``, ``tool_use``, ``max_tokens``, ``stop_sequence``."""

    usage: dict[str, int]
    """Token counters: input_tokens, output_tokens, cache_read_input_tokens,
    cache_creation_input_tokens. Missing keys default to 0."""

    model: str


class AnthropicClient:
    """Async wrapper around ``AsyncAnthropic``. Kept stateless so the
    orchestrator can construct one per run (or share one across runs —
    both are fine; the SDK pools connections internally)."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is required for the research agent. "
                "Set it in .env or pass api_key="
            )
        self._client = AsyncAnthropic(
            api_key=key, timeout=timeout_s, max_retries=max_retries
        )

    async def create(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int = 2048,
        cache_system: bool = True,
    ) -> LLMResponse:
        """One round-trip to the model.

        ``cache_system`` writes the system prompt to the 5-minute prompt
        cache. The first call in a run pays the write cost (1.25× input);
        subsequent calls within 5 min pay 0.1× input. For multi-turn tool
        loops this saves real money — the tool schemas are big.
        """
        system_blocks: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": system,
            }
        ]
        if cache_system:
            system_blocks[0]["cache_control"] = {"type": "ephemeral"}

        message = await self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_blocks,
            messages=messages,
            tools=tools,
        )

        content = [_block_to_dict(b) for b in message.content]
        usage = {
            "input_tokens": getattr(message.usage, "input_tokens", 0) or 0,
            "output_tokens": getattr(message.usage, "output_tokens", 0) or 0,
            "cache_read_input_tokens": getattr(
                message.usage, "cache_read_input_tokens", 0
            )
            or 0,
            "cache_creation_input_tokens": getattr(
                message.usage, "cache_creation_input_tokens", 0
            )
            or 0,
        }
        return LLMResponse(
            content=content,
            stop_reason=message.stop_reason or "",
            usage=usage,
            model=message.model,
        )


def _block_to_dict(block: Any) -> dict[str, Any]:
    """Convert one Anthropic content block to a JSON-serializable dict.

    The SDK ships pydantic models with ``model_dump`` — but we want to
    decouple persistence from the SDK version so future upgrades don't
    silently change the on-disk transcript shape.
    """
    bt = getattr(block, "type", None)
    if bt == "text":
        return {"type": "text", "text": getattr(block, "text", "")}
    if bt == "tool_use":
        return {
            "type": "tool_use",
            "id": getattr(block, "id", ""),
            "name": getattr(block, "name", ""),
            "input": getattr(block, "input", {}),
        }
    # Future block types (thinking, server_tool_use, etc.) — fall back to
    # the SDK's own serialization so the transcript still round-trips.
    if hasattr(block, "model_dump"):
        return block.model_dump(mode="json")
    return {"type": bt or "unknown", "raw": repr(block)}
