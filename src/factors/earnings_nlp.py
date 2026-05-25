"""Earnings-call NLP factor — scaffolding.

Status as of 2026-05-18: shipped as INTERFACE ONLY. Transcript sourcing
isn't built into the codebase yet, and Claude API costs at SP500-scale
quarterly aren't free. The scaffold ships so the LLM-extraction shape
+ DB schema + factor surface are reviewable + testable before the
transcript pipeline lands.

Surfaces:

* :class:`EarningsCallSentiment` — pydantic shape we expect the LLM to
  return for one (ticker, call_date) call: management tone, guidance
  direction, analyst-Q-A friction, surprise %.
* :func:`extract_sentiment_from_transcript` — async LLM call wrapper.
  When a transcript text is supplied, prompts Claude for a JSON
  payload matching the schema and parses it. Pure function; no I/O
  beyond Anthropic.
* :func:`earnings_nlp_factor` — async DB-coupled factor builder. Looks
  up cached sentiments in (future) ``earnings_call_sentiments`` table
  and ranks. Returns empty when no row covers as_of (i.e., the
  pipeline hasn't been activated yet).

When transcripts land:
1. Build `scripts/ingest_earnings_calls.py` (transcript provider → DB).
2. Migrate ``earnings_call_sentiments`` table (Alembic).
3. Build `scripts/extract_call_sentiment.py` (DB transcript →
   :func:`extract_sentiment_from_transcript` → cache row).
4. Flip `--include-earnings-nlp` on in the daily picks pipeline.
"""

from __future__ import annotations

import logging
from typing import Any, Literal, Optional, Sequence

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


GuidanceDirection = Literal["raised", "in_line", "lowered", "withdrawn", "unknown"]
ToneLabel = Literal["bullish", "neutral", "bearish"]


class EarningsCallSentiment(BaseModel):
    """LLM-extracted features for one earnings call.

    Designed to be cheap to extract from a transcript (one LLM call,
    ~$0.01 per call on claude-sonnet-4-6) and stable across vendors.
    """

    model_config = ConfigDict(frozen=True)

    ticker: str
    call_date: str  # ISO date — Pydantic will accept str
    fiscal_period: str = ""  # e.g. "Q3 2025"

    # Management commentary on the just-reported quarter.
    tone_label: ToneLabel = "neutral"
    tone_confidence: float = Field(ge=0.0, le=1.0, default=0.5)

    # Forward guidance vs prior period.
    guidance_direction: GuidanceDirection = "unknown"
    guidance_confidence: float = Field(ge=0.0, le=1.0, default=0.5)

    # Analyst Q&A friction (defensive answers, dodged questions,
    # follow-up grilling). 0 = none, 1 = highly friction. Often
    # the most predictive piece in academic NLP studies (analysts
    # spot trouble before the headline reaction).
    qa_friction: float = Field(ge=0.0, le=1.0, default=0.0)

    # Earnings surprise % (consensus EPS vs actual; pulled from a
    # separate source, not the transcript). Stored here for convenience.
    eps_surprise_pct: Optional[float] = None

    # One-sentence summary the LLM emitted, surfaced in the UI.
    summary: str = ""


_EXTRACTION_PROMPT = """You are summarizing one quarterly earnings call for a quant
trading system. Return JSON ONLY (no prose, no markdown fences),
matching the EarningsCallSentiment schema below. Bias toward "neutral"
/ "unknown" / 0.5 confidence when the transcript is ambiguous — false
positives on tone or guidance cost us alpha.

Transcript:
{transcript}

Output JSON (keys exactly):
{{
  "tone_label": "bullish" | "neutral" | "bearish",
  "tone_confidence": <0.0-1.0>,
  "guidance_direction": "raised" | "in_line" | "lowered" | "withdrawn" | "unknown",
  "guidance_confidence": <0.0-1.0>,
  "qa_friction": <0.0-1.0>,
  "summary": "<one sentence>"
}}

Rules:
- "raised" requires explicit numerical lift vs prior guide; vague
  "we feel good" is NOT raised.
- "qa_friction" is high when management dodges or analysts push back
  with follow-ups. Calm Q&A is 0.0.
- "tone_label" reflects the management commentary on the JUST-REPORTED
  quarter, not the guidance.
"""


async def extract_sentiment_from_transcript(
    *,
    ticker: str,
    call_date: str,
    transcript: str,
    eps_surprise_pct: Optional[float] = None,
    fiscal_period: str = "",
    model: str = "claude-sonnet-4-6",
    timeout_seconds: float = 60.0,
) -> EarningsCallSentiment:
    """Extract structured sentiment from a raw transcript via Claude.

    Raises if ANTHROPIC_API_KEY is missing — same posture as the
    sanity-check path; caller fallbacks if no key. Parse failures
    return a neutral default rather than raising.
    """
    import json
    import os

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "extract_sentiment_from_transcript requires ANTHROPIC_API_KEY."
        )

    from src.research_agent.llm_client import AnthropicClient

    client = AnthropicClient()
    prompt = _EXTRACTION_PROMPT.format(transcript=transcript[:60_000])
    response = await client.acomplete(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=500,
        timeout=timeout_seconds,
    )
    return _parse_extraction(
        response.text,
        ticker=ticker, call_date=call_date,
        fiscal_period=fiscal_period,
        eps_surprise_pct=eps_surprise_pct,
    )


def _parse_extraction(
    text: str,
    *,
    ticker: str,
    call_date: str,
    fiscal_period: str,
    eps_surprise_pct: Optional[float],
) -> EarningsCallSentiment:
    """Parse the LLM's JSON. Returns a neutral default on any error."""
    import json

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        logger.warning("earnings_nlp: no JSON block found in LLM output")
        return EarningsCallSentiment(
            ticker=ticker, call_date=call_date,
            fiscal_period=fiscal_period,
            eps_surprise_pct=eps_surprise_pct,
        )
    try:
        payload: dict[str, Any] = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        logger.warning("earnings_nlp: JSON parse failed; defaulting to neutral")
        return EarningsCallSentiment(
            ticker=ticker, call_date=call_date,
            fiscal_period=fiscal_period,
            eps_surprise_pct=eps_surprise_pct,
        )
    try:
        return EarningsCallSentiment(
            ticker=ticker,
            call_date=call_date,
            fiscal_period=fiscal_period,
            tone_label=payload.get("tone_label") or "neutral",
            tone_confidence=float(payload.get("tone_confidence", 0.5)),
            guidance_direction=payload.get("guidance_direction") or "unknown",
            guidance_confidence=float(payload.get("guidance_confidence", 0.5)),
            qa_friction=float(payload.get("qa_friction", 0.0)),
            eps_surprise_pct=eps_surprise_pct,
            summary=str(payload.get("summary") or "")[:500],
        )
    except Exception:
        logger.exception("earnings_nlp: validation failed; defaulting to neutral")
        return EarningsCallSentiment(
            ticker=ticker, call_date=call_date,
            fiscal_period=fiscal_period,
            eps_surprise_pct=eps_surprise_pct,
        )


def sentiment_to_factor_score(s: EarningsCallSentiment) -> float:
    """Collapse a sentiment record to a single 0-100 factor score.

    Heuristic; tunable once we have outcome-attributed training data:
    * Tone label: bullish=+15, neutral=0, bearish=-15.
    * Guidance: raised=+25, in_line=0, lowered=-25, withdrawn=-10.
    * Q&A friction: subtract 0..20 proportional to friction.
    * EPS surprise: clamp to [-25, 25], add directly.
    * Tone/guidance confidence scales their respective contributions.
    """
    tone_pts = {"bullish": 15.0, "neutral": 0.0, "bearish": -15.0}[s.tone_label]
    tone_pts *= s.tone_confidence

    guide_pts = {
        "raised": 25.0, "in_line": 0.0, "lowered": -25.0,
        "withdrawn": -10.0, "unknown": 0.0,
    }[s.guidance_direction]
    guide_pts *= s.guidance_confidence

    friction_pts = -20.0 * s.qa_friction

    surprise_pts = 0.0
    if s.eps_surprise_pct is not None:
        surprise_pts = max(-25.0, min(25.0, float(s.eps_surprise_pct)))

    total = 50.0 + tone_pts + guide_pts + friction_pts + surprise_pts
    return max(0.0, min(100.0, total))


def rank_sentiments(
    sentiments: Sequence[EarningsCallSentiment],
) -> pd.DataFrame:
    """Rank a list of sentiments as a factor frame."""
    if not sentiments:
        return pd.DataFrame(columns=["ticker", "raw", "rank", "z_score"])
    rows = [
        {"ticker": s.ticker, "raw": sentiment_to_factor_score(s)}
        for s in sentiments
    ]
    df = pd.DataFrame(rows).sort_values("raw", ascending=False).reset_index(drop=True)
    df["rank"] = df.index + 1
    mu = df["raw"].mean()
    sigma = df["raw"].std(ddof=0)
    df["z_score"] = (df["raw"] - mu) / sigma if sigma > 0 else 0.0
    return df[["ticker", "raw", "rank", "z_score"]]


__all__ = [
    "EarningsCallSentiment",
    "extract_sentiment_from_transcript",
    "sentiment_to_factor_score",
    "rank_sentiments",
]
