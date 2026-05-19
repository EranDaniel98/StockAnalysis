"""AI pre-trade sanity check (ADVISORY ONLY).

Reads today's picks JSON. Optionally pulls the drift-detector report.
Asks Claude for a risk-aware review: per-pick KEEP / FLAG / VETO plus
an overall PROCEED / HOLD / REVIEW. Output saved to
``reports/ai_sanity_check_<date>.{json,md}``.

Advisory ONLY. Never blocks orders. The intent (per task #4) is to
ship this as a log-only veto layer, accumulate >=1 month of paper-
trade data tracking AI verdict vs realized outcome, and only then
decide whether to wire it into ``paper_trade_factor_picks.py`` as a
hard gate.

Usage
-----

    uv run python -m scripts.ai_sanity_check
    uv run python -m scripts.ai_sanity_check --picks-date 2026-05-19
    uv run python -m scripts.ai_sanity_check --model claude-opus-4-7

The script exits 0 on success regardless of AI verdict. A non-zero
exit indicates infrastructure failure (missing key, bad JSON, etc.)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Load .env so ANTHROPIC_API_KEY is available when run standalone.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger("ai_sanity_check")


SYSTEM_PROMPT = """You are a senior risk-aware portfolio reviewer auditing
today's algorithmic stock picks before a paper-trade rebalance. The picks
come from a momentum + quality + value + PEAD composite ranking on the
PIT Russell 1000, top 3% by composite z-score, rebalanced quarterly.

Your job: catch picks that the rules-based composite might select but a
human reviewer would flag. Specifically look for:

- Borderline composite z-scores (<1.5 = thin signal)
- Sector overconcentration relative to the 30% cap
- Names with known recent fundamental deterioration (within your training
  knowledge cutoff)
- Earnings imminent (within the next ~5 trading days) -- adds noise
- Weak factor breakdowns (e.g., great momentum but bottom-quartile quality)
- Drift-detector warnings on inputs

You are ADVISORY. You do not block orders. Your output is logged for
later comparison against realized outcomes. Be calibrated: don't FLAG
everything; reserve VETO for serious red flags.

Output ONLY valid JSON matching the schema in the user message. No
markdown, no commentary outside the JSON. If you cannot evaluate a
ticker, mark it KEEP with reason="insufficient_info"."""


SCHEMA_DESCRIPTION = """{
  "overall_verdict": "PROCEED" | "HOLD" | "REVIEW",
  "confidence": 0-100,
  "key_concerns": ["concern 1", "concern 2", ...],
  "per_pick": [
    {
      "ticker": "...",
      "verdict": "KEEP" | "FLAG" | "VETO",
      "reason": "short categorical (earnings_imminent / weak_quality / sector_cluster / fundamental_concern / no_data / etc.)",
      "evidence": "1-2 sentences of WHY"
    }
  ]
}

PROCEED = ship as-is. HOLD = small adjustments suggested. REVIEW =
material concerns; recommend manual sign-off before paper trade."""


def _build_messages(
    picks_data: dict[str, Any], drift_data: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """User message bundles picks + drift into a single JSON blob."""
    parts = [
        f"Picks JSON (top {picks_data.get('top_n')} by composite z):",
        json.dumps(
            {
                "as_of": picks_data.get("as_of"),
                "strategy": picks_data.get("strategy"),
                "universe_size": picks_data.get("universe_size"),
                "factors": picks_data.get("factors"),
                "sector_cap_skipped": picks_data.get("sector_cap_skipped"),
                "picks": picks_data.get("picks", []),
            },
            indent=2,
            default=str,
        ),
    ]
    if drift_data is not None:
        parts.append("")
        parts.append("Drift-detector report:")
        parts.append(json.dumps(drift_data, indent=2, default=str))
    parts.append("")
    parts.append("Required output schema:")
    parts.append(SCHEMA_DESCRIPTION)
    parts.append("")
    parts.append("Return ONLY JSON. Begin output with '{' and end with '}'.")
    return [{"role": "user", "content": "\n".join(parts)}]


def _extract_text(content: list[dict[str, Any]]) -> str:
    """Concatenate text blocks from a Claude response."""
    return "\n".join(b["text"] for b in content if b.get("type") == "text")


def _parse_json_response(text: str) -> dict[str, Any]:
    """Try strict json.loads first; fall back to the first {...} block."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError(
            f"No JSON object found in Claude response. First 300 chars: "
            f"{text[:300]!r}"
        )
    return json.loads(m.group(0))


def _render_markdown(verdict: dict[str, Any], picks: list[dict[str, Any]],
                     as_of: str, model: str, usage: dict[str, int]) -> str:
    by_ticker = {p["ticker"]: p for p in picks}
    lines = [
        f"# AI Sanity Check — {as_of}",
        "",
        f"**Model:** `{model}`",
        f"**Tokens:** in={usage.get('input_tokens', 0)} "
        f"out={usage.get('output_tokens', 0)} "
        f"(cache_read={usage.get('cache_read_input_tokens', 0)} "
        f"cache_write={usage.get('cache_creation_input_tokens', 0)})",
        "",
        "## Overall verdict",
        "",
        f"**{verdict.get('overall_verdict', '?')}** "
        f"(confidence {verdict.get('confidence', '?')}/100)",
        "",
    ]
    concerns = verdict.get("key_concerns", []) or []
    if concerns:
        lines.append("**Key concerns:**")
        lines.append("")
        for c in concerns:
            lines.append(f"- {c}")
        lines.append("")
    lines.append("## Per-pick")
    lines.append("")
    lines.append("| Ticker | Verdict | z | Sector | Reason | Evidence |")
    lines.append("|---|---|---|---|---|---|")
    for pp in verdict.get("per_pick", []) or []:
        t = pp.get("ticker", "?")
        original = by_ticker.get(t, {})
        z = original.get("z_score")
        z_str = f"{z:+.2f}" if isinstance(z, (int, float)) else "?"
        sector = original.get("sector", "?")
        verdict_str = pp.get("verdict", "?")
        reason = pp.get("reason", "")
        evidence = pp.get("evidence", "").replace("|", "\\|")
        lines.append(
            f"| {t} | **{verdict_str}** | {z_str} | {sector} | {reason} | {evidence} |"
        )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*Advisory only. This output is logged for verdict-vs-outcome "
                 "tracking but does NOT block paper-trade execution.*")
    return "\n".join(lines)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--picks-date", default=None,
                   help="YYYY-MM-DD; defaults to today (UTC).")
    p.add_argument("--picks-dir", default="data/daily_picks",
                   help="Directory containing daily picks JSONs.")
    p.add_argument("--drift-report", default=None,
                   help="Path to a drift-detector JSON. Optional.")
    p.add_argument("--output-dir", default="reports",
                   help="Where to write .json and .md outputs.")
    p.add_argument("--model", default="claude-sonnet-4-6",
                   help="Anthropic model. Default sonnet-4-6 (balance of "
                        "cost / speed). Pass claude-opus-4-7 for deeper "
                        "analysis at higher cost.")
    p.add_argument("--max-tokens", type=int, default=4096)
    return p.parse_args()


async def _run(args: argparse.Namespace) -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        logger.error(
            "ANTHROPIC_API_KEY not set; AI sanity check requires it. "
            "Set in .env or environment.",
        )
        return 1

    date_str = args.picks_date or datetime.now(timezone.utc).date().isoformat()
    picks_path = Path(args.picks_dir) / f"{date_str}.json"
    if not picks_path.exists():
        logger.error("No picks file at %s -- run daily_factor_picks first.",
                     picks_path)
        return 1
    picks_data = json.loads(picks_path.read_text(encoding="utf-8"))
    if not picks_data.get("picks"):
        logger.warning("Picks file %s has no picks (gate may have fired). "
                       "Nothing to sanity check.", picks_path)
        return 0

    drift_data: dict[str, Any] | None = None
    if args.drift_report:
        drift_path = Path(args.drift_report)
        if drift_path.exists():
            drift_data = json.loads(drift_path.read_text(encoding="utf-8"))
        else:
            logger.warning("Drift report %s missing; proceeding without.",
                           drift_path)

    # Import here so the script can `--help` without anthropic installed.
    from src.research_agent.llm_client import AnthropicClient

    client = AnthropicClient()
    messages = _build_messages(picks_data, drift_data)
    logger.info("Calling Claude (%s) with %d picks...",
                args.model, len(picks_data["picks"]))
    response = await client.create(
        model=args.model,
        system=SYSTEM_PROMPT,
        messages=messages,
        tools=[],
        max_tokens=args.max_tokens,
        cache_system=True,
    )
    logger.info("Response: stop=%s in=%d out=%d",
                response.stop_reason,
                response.usage.get("input_tokens", 0),
                response.usage.get("output_tokens", 0))

    text = _extract_text(response.content)
    try:
        verdict = _parse_json_response(text)
    except (ValueError, json.JSONDecodeError) as e:
        logger.error("Failed to parse JSON from Claude: %s", e)
        # Save the raw response so the user can inspect manually.
        out_dir = Path(args.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        raw_path = out_dir / f"ai_sanity_check_{date_str}.raw.txt"
        raw_path.write_text(text, encoding="utf-8")
        logger.error("Raw response saved to %s", raw_path)
        return 2

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_payload = {
        "as_of": date_str,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": response.model,
        "usage": response.usage,
        "input_picks": picks_data.get("picks", []),
        "verdict": verdict,
    }
    json_path = out_dir / f"ai_sanity_check_{date_str}.json"
    json_path.write_text(
        json.dumps(json_payload, indent=2, default=str), encoding="utf-8",
    )
    md_path = out_dir / f"ai_sanity_check_{date_str}.md"
    md_path.write_text(
        _render_markdown(verdict, picks_data["picks"], date_str,
                         response.model, response.usage),
        encoding="utf-8",
    )
    logger.info("Wrote %s and %s", json_path, md_path)

    # Brief stdout summary
    print(f"AI verdict: {verdict.get('overall_verdict', '?')} "
          f"(confidence {verdict.get('confidence', '?')}/100)")
    per_pick = verdict.get("per_pick", []) or []
    flags = [p for p in per_pick if p.get("verdict") == "FLAG"]
    vetoes = [p for p in per_pick if p.get("verdict") == "VETO"]
    print(f"  KEEP: {sum(1 for p in per_pick if p.get('verdict') == 'KEEP')}  "
          f"FLAG: {len(flags)}  VETO: {len(vetoes)}")
    if vetoes:
        for v in vetoes:
            print(f"  VETO  {v.get('ticker')}: {v.get('reason')}")
    return 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = _parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
