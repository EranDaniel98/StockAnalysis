"""Pre-trade sanity check for BUY+ recommendations.

Asymmetric trust: the checker can downgrade a BUY to CAUTION or REJECT,
but it can never upgrade. Hallucination risk is one-sided — we want it
to err toward "I'm not sure" rather than "looks great." The composite
score is the source of confidence; the LLM is the brake.

Layout:
  - ``check_buy_signal(ticker, ...)`` — real LLM path. Needs
    ``ANTHROPIC_API_KEY``. Returns a :class:`SanityCheck`.
  - ``check_buy_signal_mock(ticker, ...)`` — deterministic mock that
    lets every code path light up before the API key is wired in.

Both share the same return type so the orchestrator can be flipped
between them via a feature flag (``settings.sanity_check.mode``).

Cost note: a real call costs ~$0.005/ticker on claude-sonnet-4-6 with
~200 input + 150 output tokens. 10 BUY signals = ~$0.05 per scan.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from src.api.schemas.sanity import SanityCheck

logger = logging.getLogger(__name__)


# ─── Inputs ────────────────────────────────────────────────────────────


class SanityCheckInputs:
    """Bundle of evidence handed to the LLM for one ticker.

    Kept simple on purpose — the LLM does the reasoning, our job is to
    feed it the right snippets. Anything added here that the prompt
    doesn't reference is dead weight + cost.
    """

    def __init__(
        self,
        *,
        ticker: str,
        recent_filings_summary: str,
        recent_news_summary: str,
        price_anomaly_summary: Optional[str],
        composite_score: float,
        action: str,
    ) -> None:
        self.ticker = ticker
        self.recent_filings_summary = recent_filings_summary
        self.recent_news_summary = recent_news_summary
        self.price_anomaly_summary = price_anomaly_summary
        self.composite_score = composite_score
        self.action = action


# ─── Prompt ────────────────────────────────────────────────────────────


_SYSTEM_PROMPT = """You are a sanity checker for a personal quant trading system. The
system has flagged {ticker} as {action} (composite score {score:.1f})
based on systematic factor scoring.

Your job: identify obvious one-off catalysts that might explain a recent
price move and warn that the systematic signal is likely to mean-revert
rather than continue. You CAN downgrade signals to CAUTION or REJECT.
You CANNOT upgrade — your role is purely defensive.

Recent 8-K filings (last 30 days):
{filings}

Recent news headlines:
{news}

Recent price/volume anomaly:
{anomaly}

Output JSON only, no prose:
{{
  "verdict": "OK" | "CAUTION" | "REJECT",
  "reason": "<one sentence>",
  "catalysts_found": ["<short label>", ...],
  "confidence": <0.0-1.0>
}}

REJECT only for clear one-off catalysts: announced M&A target, takeover
rumor, single-issue earnings surprise that explains the entire move,
binary regulatory event. CAUTION for ambiguous signals (recent insider
sales, downgrade from major analyst). OK when the move looks like a
sustained trend or fundamentals-driven re-rating.

Bias toward OK. False REJECTs are a worse failure mode than false OKs
because the composite already passed many quality gates.
"""


def _render_prompt(inputs: SanityCheckInputs) -> str:
    return _SYSTEM_PROMPT.format(
        ticker=inputs.ticker,
        action=inputs.action,
        score=inputs.composite_score,
        filings=inputs.recent_filings_summary or "(none in the last 30 days)",
        news=inputs.recent_news_summary or "(none)",
        anomaly=inputs.price_anomaly_summary or "none",
    )


# ─── Real LLM path ─────────────────────────────────────────────────────


async def check_buy_signal(
    inputs: SanityCheckInputs,
    *,
    model: str = "claude-sonnet-4-6",
    timeout_seconds: float = 30.0,
) -> SanityCheck:
    """Real LLM check. Raises if ANTHROPIC_API_KEY is missing — caller
    should fall back to the mock or skip the check entirely."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "check_buy_signal called without ANTHROPIC_API_KEY in env. "
            "Either set the key, or use check_buy_signal_mock for a "
            "deterministic no-API-call placeholder."
        )

    # Lazy import — anthropic SDK is heavy. Don't pay for it on every
    # scan when the sanity check is disabled.
    from src.research_agent.llm_client import AnthropicClient

    client = AnthropicClient(timeout_s=timeout_seconds)
    prompt = _render_prompt(inputs)

    # The shared client exposes ``create(...)`` (tool-use aware). The
    # sanity check is a single text round-trip — no tools, no system —
    # so we hand the prompt as a user message and concatenate any text
    # blocks the model returns.
    response = await client.create(
        model=model,
        system="",
        messages=[{"role": "user", "content": prompt}],
        tools=[],
        max_tokens=300,
        cache_system=False,
    )
    text = "".join(
        b.get("text", "")
        for b in response.content
        if isinstance(b, dict) and b.get("type") == "text"
    )
    return _parse_llm_output(text, model=model, mocked=False)


def _parse_llm_output(text: str, *, model: str, mocked: bool) -> SanityCheck:
    """Parse the LLM's JSON response into a SanityCheck. The LLM may
    surround the JSON with prose (instruction-following is imperfect);
    we extract the first {...} block we can parse.

    On any parse failure we return CAUTION rather than crashing — the
    operator should see "we couldn't read the LLM's output" not "scan
    crashed because a BUY signal couldn't be sanity-checked".
    """
    payload = _extract_json_block(text)
    if payload is None:
        logger.warning("Sanity-check parse failed; defaulting to CAUTION")
        return SanityCheck(
            verdict="CAUTION",
            reason="LLM output could not be parsed as JSON",
            catalysts_found=[],
            confidence=0.0,
            model_used=model,
            mocked=mocked,
            checked_at=datetime.now(timezone.utc).isoformat(),
        )

    try:
        return SanityCheck(
            verdict=payload.get("verdict", "CAUTION"),
            reason=str(payload.get("reason") or "")[:500],
            catalysts_found=list(payload.get("catalysts_found") or [])[:10],
            confidence=float(payload.get("confidence", 0.0)),
            model_used=model,
            mocked=mocked,
            checked_at=datetime.now(timezone.utc).isoformat(),
        )
    except Exception:
        logger.exception("Sanity-check validation failed; defaulting to CAUTION")
        return SanityCheck(
            verdict="CAUTION",
            reason="LLM output did not match schema",
            catalysts_found=[],
            confidence=0.0,
            model_used=model,
            mocked=mocked,
            checked_at=datetime.now(timezone.utc).isoformat(),
        )


def _extract_json_block(text: str) -> Optional[dict]:
    """Find the first {...} JSON object in ``text`` and parse it. None
    if no parseable JSON object is present."""
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break
        # If we hit EOF or a parse error, advance and try again.
        start = text.find("{", start + 1)
    return None


# ─── Mock path (no API key required) ───────────────────────────────────


def check_buy_signal_mock(inputs: SanityCheckInputs) -> SanityCheck:
    """Deterministic mock for shipping the wiring before live keys land.

    Heuristic: REJECT when the filings summary mentions "merger",
    "acquisition", "tender offer", or "takeover"; CAUTION when it
    mentions insider sales; OK otherwise. Same shape as the real
    checker so swap-in is a one-line change.

    This is good enough to validate the integration end-to-end and to
    write tests against. It is NOT good enough to deploy as a real
    sanity check — every output is rule-based, no semantic
    understanding. The instant ANTHROPIC_API_KEY is set, flip
    settings.sanity_check.mode to "live" to swap to the real path.
    """
    blob = " ".join([
        inputs.recent_filings_summary,
        inputs.recent_news_summary,
        inputs.price_anomaly_summary or "",
    ]).lower()

    catalysts: list[str] = []
    verdict: str = "OK"
    reason = (
        "No one-off catalysts detected in recent filings or news; "
        "systematic BUY appears clean."
    )

    if any(t in blob for t in ("merger", "acquisition", "tender offer", "takeover")):
        verdict = "REJECT"
        catalysts.append("M&A or takeover language in filings/news")
        reason = (
            "Recent filings mention M&A — recent price move likely "
            "reflects deal premium, not systematic momentum."
        )
    elif "insider sale" in blob or "insider sales" in blob:
        verdict = "CAUTION"
        catalysts.append("Recent insider selling")
        reason = (
            "Insider selling detected; the BUY may be running into "
            "supply at higher prices."
        )

    # Mock confidence is intentionally low — the real model would
    # have meaningful uncertainty here. Treat the mock as a
    # placeholder that lets the FE light up, not a real signal.
    return SanityCheck(
        verdict=verdict,
        reason=reason,
        catalysts_found=catalysts,
        confidence=0.3,  # purely rule-based, no semantic understanding
        model_used="mock",
        mocked=True,
        checked_at=datetime.now(timezone.utc).isoformat(),
    )


# ─── Dispatch ──────────────────────────────────────────────────────────


async def check_buy_signal_auto(
    inputs: SanityCheckInputs,
    *,
    mode: str = "auto",
) -> SanityCheck:
    """Dispatch helper: use the real checker when ANTHROPIC_API_KEY is
    available, fall back to the mock otherwise.

    ``mode='auto'`` honors the env. ``mode='mock'`` forces the mock.
    ``mode='live'`` forces the real path and raises if the key is
    missing — useful when you specifically want the failure to
    surface rather than silently degrade.
    """
    if mode == "mock":
        return check_buy_signal_mock(inputs)
    if mode == "live":
        return await check_buy_signal(inputs)
    # auto
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return await check_buy_signal(inputs)
        except Exception:
            logger.exception(
                "Sanity check live path failed; falling back to mock",
            )
            return check_buy_signal_mock(inputs)
    return check_buy_signal_mock(inputs)
