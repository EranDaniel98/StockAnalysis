"""Pydantic schemas for the /api/research surface.

The full Anthropic transcript is persisted but not surfaced — it's verbose
and the frontend only needs the high-level shape (tool calls + final
answer + cost). Set ``include_transcript=true`` on the GET to opt in.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class ResearchAskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    model: Optional[str] = Field(default=None, description="Override default Sonnet 4.6")
    max_turns: int = Field(default=8, ge=1, le=20)
    notes: Optional[str] = None


class ToolCallEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool: str
    input: dict[str, Any] = Field(default_factory=dict)
    is_error: bool = False
    result_summary: str = ""


class ResearchRunSummary(BaseModel):
    """List view — light shape, no transcript."""

    model_config = ConfigDict(frozen=True)

    id: int
    question: str
    model: str
    status: str
    final_answer: Optional[str] = None
    n_turns: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    started_at: datetime
    completed_at: Optional[datetime] = None
    error: Optional[str] = None


class ResearchRunDetail(ResearchRunSummary):
    """Detail view — adds tool_calls + (optionally) the transcript."""

    model_config = ConfigDict(frozen=True)

    tool_calls: list[ToolCallEntry] = Field(default_factory=list)
    transcript: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Full Anthropic message list. Omitted unless include_transcript=true.",
    )


class FilingNotificationItem(BaseModel):
    """Row from filing_notifications — what the /research/feed page lists."""

    model_config = ConfigDict(frozen=True)

    id: int
    ticker: str
    form: str
    accession_no: str
    filing_date: str
    primary_document: Optional[str] = None
    detected_at: datetime
    research_run_id: Optional[int] = None
    summary: Optional[str] = None


class SummarizeNotificationResponse(BaseModel):
    """What ``POST /api/research/notifications/{id}/summarize`` returns:
    the notification (now linked to a run) plus the run detail itself."""

    model_config = ConfigDict(frozen=True)

    notification: FilingNotificationItem
    run: ResearchRunDetail
