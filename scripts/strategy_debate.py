"""Opus 4.7 <-> Gemini strategy debate orchestrator.

Runs an automated, symmetric-critique debate between Claude Opus 4.7 and
Gemini 3.1 Pro over the LIVE factor system. Each round, the speaker sees the
full transcript so far and the shared dossier, then critiques freely + proposes
concrete improvements. Writes a markdown transcript to reports/.

Dossier = CLAUDE.md (architecture) + scripts/strategy_debate_brief.md (the
curated evidence pack describing what is *actually* traded). The brief is
authoritative: it explicitly tells both models NOT to debate the dead
config/strategies.yaml.

Usage:
    .venv/Scripts/python.exe scripts/strategy_debate.py --rounds 6
    .venv/Scripts/python.exe scripts/strategy_debate.py --mode collab \
        --seed-file scripts/debate_seed_institutional_liquidity.md --rounds 6
    .venv/Scripts/python.exe scripts/strategy_debate.py --list-gemini-models
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

REPO = Path(__file__).resolve().parent.parent
OPUS_MODEL = "claude-opus-4-7"
# Pro requires paid API billing (Tier 1+); free tier is limit:0 on 3.x Pro.
# Fall back to --gemini-model gemini-3.5-flash if running on the free tier.
GEMINI_MODEL = "gemini-3.1-pro-preview"
OPUS_MAX_TOKENS = 3000  # closing-synthesis turns (spec + tables) need the headroom
# Gemini 3.x Pro is a thinking model — reasoning tokens count against the output
# budget, so a tight cap truncates the visible answer mid-sentence. Give it room.
GEMINI_MAX_TOKENS = 8000
TIMEOUT_S = 240

FRAMING = """You are one of two AI quant reviewers in a SYMMETRIC CRITIQUE of a \
live, paper-traded US-equity strategy. The other reviewer is {opponent}.

Rules of engagement:
- Critique freely and propose concrete, prioritized improvements. There are no
  fixed sides; you may agree or disagree with the other reviewer.
- Be specific and cite the dossier's evidence. No generic quant platitudes.
- Do NOT repeat points already well made — advance the argument.
- HARD CONSTRAINT: every proposal must run on the dossier's stated data layer
  (Polygon EOD stocks + EDGAR PIT fundamentals + yfinance VIX/earnings + Alpaca).
  No dark-pool, options/dealer-gamma, intraday, or alternative data.
- The single most important question is MEASUREMENT: given the phase-luck
  finding, can any claimed edge be distinguished from noise? Weigh every idea
  against that.
- Keep each turn under ~400 words. Lead with your strongest point."""

OPENING = (
    "Open the debate. Identify the strategy's most serious weaknesses and your "
    "top proposed improvements, grounded in the dossier."
)
MIDDLE = (
    "Respond to the other reviewer's latest turn. Where do you agree, where do "
    "you push back (with reasons), and what did they miss?"
)
CLOSING = (
    "CLOSING TURN. Synthesize: the strongest points of agreement, the key "
    "remaining disagreements, and the top 3 concrete, prioritized actions — "
    "each justified by evidence and feasible on the stated data layer."
)

# --- collab mode: co-design ONE new strategy, not critique the existing one ---

COLLAB_FRAMING = """You are one of two AI quant researchers COLLABORATING to design \
ONE new equity strategy that can plausibly beat SPY net of costs. The other \
researcher is {opponent}. This is co-design, not debate: build on each other's \
ideas, fill the gaps in each other's proposals, and converge on a single concrete, \
implementable specification.

Ground rules:
- HARD DATA CONSTRAINT: the strategy must be buildable on the dossier's data layer
  (Polygon EOD US equities + EDGAR PIT fundamentals & 13F/Form-4 filings + yfinance
  VIX/earnings + semi-monthly short interest + Alpaca). NO dark-pool prints,
  options/dealer-gamma, intraday/L2, or paid alternative data. If a seed idea needs
  unavailable data, adapt the *thesis* to an EOD-observable proxy or replace it.
- Every signal must be defined precisely enough to implement: input data, formula,
  lookback, cross-sectional rank/z-score, update frequency.
- MEASURABILITY IS NON-NEGOTIABLE. Given this system's phase-luck reality (±20-30pp
  envelope on 2yr/63d backtests), the strategy must ship with a falsifiable
  validation plan: phase-averaged metrics, a permutation/null baseline, and a
  pre-registered decision rule. An idea that can't be told apart from luck is not a
  candidate — say so and fix it.
- Be additive, not repetitive. Extend, correct, or fill a missing piece (signal
  math, entry/exit, sizing, risk, validation). Keep each turn focused (~450 words)."""

COLLAB_OPENING = (
    "Open the co-design. Start from the seed proposal in the dossier's STARTING "
    "POINT. Salvage what's sound about its thesis, discard what needs unavailable "
    "data, and sketch v0 of an EOD-buildable strategy: the core inefficiency it "
    "exploits, the precise signals, the universe, and why it could survive "
    "arbitrage. Leave clear hooks for your collaborator to extend."
)
COLLAB_MIDDLE = (
    "Build directly on your collaborator's latest design. Add or fix the missing "
    "pieces — signal formulas, entry/exit logic, position sizing, rebalance cadence, "
    "or the validation plan. Flag any data-layer violation or measurement gap and "
    "repair it. Move the spec toward something implementable."
)
COLLAB_CLOSING = (
    "CLOSING TURN. Consolidate everything into the FINAL strategy spec: (1) thesis + "
    "the inefficiency exploited; (2) precise signal definitions (data, formula, "
    "lookback, ranking); (3) universe, entry/exit, sizing, rebalance cadence; (4) the "
    "pre-registered validation plan (phase-averaged metrics + permutation null + "
    "decision rule); (5) an honest verdict — realistic edge, failure modes, and "
    "whether it's worth building before the 2026-08-27 paper review."
)

MODES = {
    "critique": (FRAMING, OPENING, MIDDLE, CLOSING),
    "collab": (COLLAB_FRAMING, COLLAB_OPENING, COLLAB_MIDDLE, COLLAB_CLOSING),
}
MODE_LABEL = {
    "critique": "symmetric critique of the live `src/factors/*` system",
    "collab": "collaborative co-design of a new strategy",
}


def load_dossier() -> str:
    claude_md = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    brief = (REPO / "scripts" / "strategy_debate_brief.md").read_text(encoding="utf-8")
    return (
        "=== PROJECT ARCHITECTURE (CLAUDE.md) ===\n\n"
        + claude_md
        + "\n\n=== STRATEGY EVIDENCE BRIEF (authoritative) ===\n\n"
        + brief
    )


def format_transcript(turns: list[tuple[str, str]]) -> str:
    if not turns:
        return "(no turns yet — you open the debate)"
    return "\n\n".join(f"### {spk}\n{txt}" for spk, txt in turns)


def build_user_prompt(transcript: str, instruction: str, speaker: str) -> str:
    return (
        f"=== DEBATE SO FAR ===\n{transcript}\n\n"
        f"=== YOUR TASK (you are {speaker}) ===\n{instruction}"
    )


def with_retries(fn, *, attempts: int = 4):
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — surface after retries
            last = exc
            # Per-minute token/request caps (429 RESOURCE_EXHAUSTED) need a longer
            # wait than transient errors; both back off, capped at 60s.
            rate_limited = "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc)
            wait = min(60, (20 if rate_limited else 5) * (i + 1))
            print(f"  ! API error ({str(exc)[:120]}); retry {i + 1}/{attempts} in {wait}s", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"all {attempts} attempts failed; last: {last}") from last


def opus_turn(client, system_text: str, user_text: str) -> str:
    def call():
        # Cache the dossier system block — it is identical every Opus turn.
        resp = client.messages.create(
            model=OPUS_MODEL,
            max_tokens=OPUS_MAX_TOKENS,
            system=[{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_text}],
            timeout=TIMEOUT_S,
        )
        return "".join(b.text for b in resp.content if b.type == "text").strip()

    return with_retries(call)


def gemini_turn(client, gem_types, model: str, system_text: str, user_text: str) -> str:
    def call():
        resp = client.models.generate_content(
            model=model,
            contents=user_text,
            config=gem_types.GenerateContentConfig(
                system_instruction=system_text,
                max_output_tokens=GEMINI_MAX_TOKENS,
                temperature=0.7,
            ),
        )
        return (resp.text or "").strip()

    return with_retries(call)


def main() -> int:
    ap = argparse.ArgumentParser(description="Opus 4.7 <-> Gemini strategy debate")
    ap.add_argument("--rounds", type=int, default=6, help="total turns (alternating speakers)")
    ap.add_argument("--opener", choices=["opus", "gemini"], default="opus")
    ap.add_argument("--opus-model", default=OPUS_MODEL)
    ap.add_argument("--gemini-model", default=GEMINI_MODEL)
    ap.add_argument("--output", default=None, help="transcript path (default reports/debate_<date>.md)")
    ap.add_argument("--mode", choices=list(MODES), default="critique",
                    help="critique = stress-test the live system; collab = co-design a new strategy")
    ap.add_argument("--seed-file", default=None,
                    help="markdown file injected as STARTING POINT/GOAL (e.g. a strategy proposal)")
    ap.add_argument("--list-gemini-models", action="store_true")
    args = ap.parse_args()

    load_dotenv(REPO / ".env")

    from anthropic import Anthropic
    from google import genai
    from google.genai import types as gem_types

    gem_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    if args.list_gemini_models:
        for m in sorted(
            x.name for x in gem_client.models.list()
            if "generateContent" in (x.supported_actions or [])
        ):
            print(m)
        return 0

    opus_client = Anthropic(max_retries=2)  # ANTHROPIC_API_KEY from env
    dossier = load_dossier()
    if args.seed_file:
        seed = Path(args.seed_file).read_text(encoding="utf-8")
        dossier += "\n\n=== STARTING POINT / GOAL (seed for this session) ===\n\n" + seed

    framing, opening, middle, closing = MODES[args.mode]
    speakers = ["Opus 4.7", "Gemini"]
    if args.opener == "gemini":
        speakers.reverse()

    turns: list[tuple[str, str]] = []
    for i in range(args.rounds):
        speaker = speakers[i % 2]
        opponent = speakers[(i + 1) % 2]
        if i == 0:
            instruction = opening
        elif i >= args.rounds - 2:
            instruction = closing
        else:
            instruction = middle

        system_text = framing.format(opponent=opponent) + "\n\n" + dossier
        user_text = build_user_prompt(format_transcript(turns), instruction, speaker)

        print(f"[{i + 1}/{args.rounds}] {speaker} ...", file=sys.stderr)
        if speaker.startswith("Opus"):
            text = opus_turn(opus_client, system_text, user_text)
        else:
            text = gemini_turn(gem_client, gem_types, args.gemini_model, system_text, user_text)
        turns.append((speaker, text))

    out_path = Path(args.output) if args.output else REPO / "reports" / f"debate_{date.today().isoformat()}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        f"# Strategy Debate — {date.today().isoformat()}\n\n"
        f"- **Opus model:** `{args.opus_model}`\n"
        f"- **Gemini model:** `{args.gemini_model}`\n"
        f"- **Rounds:** {args.rounds} · **Opener:** {speakers[0]}\n"
        f"- **Format:** {MODE_LABEL[args.mode]}\n"
        + (f"- **Seed:** `{args.seed_file}`\n" if args.seed_file else "")
        + "\n---\n\n"
    )
    out_path.write_text(header + format_transcript(turns) + "\n", encoding="utf-8")
    print(f"\nWrote transcript -> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
