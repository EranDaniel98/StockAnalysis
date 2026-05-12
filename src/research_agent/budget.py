"""Per-run token + dollar budget for the research agent.

Two budgets enforced in tandem:
  - hard token cap         no API call once the cumulative token bill
                           crosses this number (prevents runaway loops)
  - hard turn cap          no more than N tool-use cycles per run
                           (a model that keeps re-asking the same tool
                           burns money slowly without breaching tokens)

Pricing is hardcoded per model — Anthropic's pricing page is the source
of truth and ships once-per-quarter, not via the SDK. Re-verify on
upgrade. Values are USD per million tokens.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# Anthropic pricing as of 2026-05 (USD / 1M tokens). Sonnet 4.6 is the
# default orchestrator; Opus 4.7 reserved for hard hypothesis runs.
PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6": {
        "input": 3.00,
        "output": 15.00,
        "cache_read": 0.30,
        "cache_write_5m": 3.75,
    },
    "claude-opus-4-7": {
        "input": 15.00,
        "output": 75.00,
        "cache_read": 1.50,
        "cache_write_5m": 18.75,
    },
    "claude-haiku-4-5-20251001": {
        "input": 1.00,
        "output": 5.00,
        "cache_read": 0.10,
        "cache_write_5m": 1.25,
    },
}


class BudgetExceededError(RuntimeError):
    """Raised when a research run would exceed its cap. The orchestrator
    catches this and marks the run ``budget_exceeded`` rather than failed
    — the partial transcript is still useful."""


@dataclass
class BudgetCounter:
    """Running per-run token + cost tally.

    The orchestrator updates this after every LLM call. ``check()`` is
    called *before* the next call to decide whether to keep going.
    """

    model: str
    max_input_tokens: int = 200_000
    """Cumulative input tokens (includes cache reads) before we stop."""

    max_output_tokens: int = 8_000
    """Cumulative output tokens before we stop."""

    max_turns: int = 8
    """Hard cap on tool-use cycles."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    turns: int = 0
    cost_usd: float = 0.0

    def add_usage(self, usage: dict[str, int]) -> None:
        """Record one LLM call's token usage. ``usage`` mirrors the Anthropic
        SDK's ``Message.usage`` shape: ``input_tokens``, ``output_tokens``,
        and the optional ``cache_read_input_tokens`` / ``cache_creation_input_tokens``."""
        self.input_tokens += int(usage.get("input_tokens", 0))
        self.output_tokens += int(usage.get("output_tokens", 0))
        self.cache_read_tokens += int(usage.get("cache_read_input_tokens", 0))
        self.cache_write_tokens += int(usage.get("cache_creation_input_tokens", 0))
        self.cost_usd = self._compute_cost()

    def increment_turn(self) -> None:
        self.turns += 1

    def check(self) -> None:
        """Raise if the next call would exceed any cap. Called before
        each call to the model — cheaper than aborting mid-stream."""
        if self.turns >= self.max_turns:
            raise BudgetExceededError(
                f"turn cap reached ({self.turns}/{self.max_turns})"
            )
        if self.input_tokens >= self.max_input_tokens:
            raise BudgetExceededError(
                f"input-token cap reached ({self.input_tokens}/{self.max_input_tokens})"
            )
        if self.output_tokens >= self.max_output_tokens:
            raise BudgetExceededError(
                f"output-token cap reached ({self.output_tokens}/{self.max_output_tokens})"
            )

    def _compute_cost(self) -> float:
        prices = PRICING.get(self.model)
        if prices is None:
            # Unknown model — report zero cost rather than guess. The token
            # counts still get recorded for human review.
            return 0.0
        usd = (
            self.input_tokens * prices["input"]
            + self.output_tokens * prices["output"]
            + self.cache_read_tokens * prices["cache_read"]
            + self.cache_write_tokens * prices["cache_write_5m"]
        ) / 1_000_000
        return round(usd, 6)

    def as_dict(self) -> dict[str, float | int]:
        return {
            "model": self.model,
            "turns": self.turns,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "cost_usd": self.cost_usd,
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "max_turns": self.max_turns,
        }
