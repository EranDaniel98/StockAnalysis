"""Explain WHY a stock moved — honest causal attribution, not a signal.

Given a ticker + window, we (1) deterministically decompose the move into
market / sector / idiosyncratic components and gather hard evidence (earnings
surprise, EDGAR filings, short-interest change, volume spike), then (2) ask
Claude to rank the *candidate* drivers with the evidence attached.

Discipline (this is the whole point — see the system prompt):
  - We surface CANDIDATE drivers ranked by plausibility, never "the cause."
    A single move is overdetermined; attribution is underdetermined.
  - The LLM may cite ONLY the provided evidence; gaps are stated, not guessed.
  - Every driver is phrased as a TESTABLE cross-sectional hypothesis, so the
    "find similar names" follow-up feeds the backtest harness (IC / phase
    envelope) instead of becoming a hindsight-narrative trade.

This module is pure: evidence is assembled by the caller (scripts/research_move.py)
which owns the I/O; here we hold the data contract, the deterministic
decomposition, and the LLM synthesis.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# yfinance sector label -> SPDR sector ETF, our proxy for "how the sector moved"
# (we have no peer-ticker list; the ETF is a clean, fetchable sector benchmark).
SECTOR_ETF: dict[str, str] = {
    "Technology": "XLK",
    "Financial Services": "XLF",
    "Healthcare": "XLV",
    "Energy": "XLE",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Industrials": "XLI",
    "Basic Materials": "XLB",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
}


@dataclass
class MoveEvidence:
    """The hard facts about a move, assembled before any LLM call."""
    ticker: str
    start: str
    end: str
    # Return attribution (event-window level, not beta regression — a few-day
    # window is too short to estimate beta reliably).
    ticker_return_pct: float
    market_return_pct: float                 # SPY over the window
    sector_label: str | None = None
    sector_etf: str | None = None
    sector_return_pct: float | None = None   # sector ETF over the window
    # Derived gaps (filled in __post_init__).
    vs_market_pct: float = 0.0
    vs_sector_pct: float | None = None
    sector_vs_market_pct: float | None = None
    # Move shape.
    biggest_day_date: str | None = None
    biggest_day_pct: float | None = None
    volume_spike_ratio: float | None = None  # window avg vol / trailing-60d avg
    # Catalysts.
    earnings_in_window: bool = False
    earnings_date: str | None = None
    earnings_surprise_pct: float | None = None
    filings: list[dict[str, str]] = field(default_factory=list)  # {form, date, ...}
    short_interest_delta_pct: float | None = None  # +=more shorts, -=covering
    # Honest gaps — sources we did NOT consult (so the LLM doesn't invent them).
    missing_sources: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.vs_market_pct = round(self.ticker_return_pct - self.market_return_pct, 2)
        if self.sector_return_pct is not None:
            self.vs_sector_pct = round(self.ticker_return_pct - self.sector_return_pct, 2)
            self.sector_vs_market_pct = round(self.sector_return_pct - self.market_return_pct, 2)


@dataclass
class CandidateDriver:
    driver: str
    plausibility: str          # high | medium | low
    evidence: str              # cites ONLY the provided evidence
    testable_hypothesis: str   # how to validate it as a cross-sectional factor


@dataclass
class MoveAnalysis:
    ticker: str
    window: str
    verdict: str               # idiosyncratic | sector-driven | market-driven | mixed
    summary: str
    candidate_drivers: list[CandidateDriver]
    cannot_determine: list[str]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


_SYSTEM_PROMPT = """\
You are a markets analyst explaining why a single stock moved over a window. \
You are deliberately disciplined and honest:

- A price move is OVERDETERMINED (earnings, sector rotation, a squeeze, one big \
buyer, macro — often at once) and attribution is UNDERDETERMINED. You therefore \
produce CANDIDATE drivers ranked by plausibility. You NEVER assert "the cause."
- You may cite ONLY the evidence provided in the user message. If something \
isn't in the evidence (e.g. news, analyst actions when listed as missing), you \
must NOT invent it — name it under cannot_determine instead.
- Lean on the return attribution: if the stock barely beat its sector ETF, the \
move is mostly sector/market, not stock-specific — say so even if it's boring.
- For EACH candidate driver, give a TESTABLE cross-sectional hypothesis: how \
would one express this driver as a factor and check it across the whole universe \
out-of-sample (so a "find similar names" follow-up gets validated, not traded on \
a hunch).

Return ONLY a JSON object, no prose around it:
{
  "verdict": "idiosyncratic" | "sector-driven" | "market-driven" | "mixed",
  "summary": "<= 3 sentences, plain, hedged appropriately",
  "candidate_drivers": [
    {"driver": "...", "plausibility": "high|medium|low",
     "evidence": "...cite the provided numbers/filings...",
     "testable_hypothesis": "...cross-sectional factor + how to validate..."}
  ],
  "cannot_determine": ["...what the evidence can't settle..."]
}
Order candidate_drivers most-plausible first. 2-5 drivers."""


def _extract_text(resp: Any) -> str:
    """Pull text from an LLMResponse's content blocks."""
    out = []
    for block in getattr(resp, "content", []) or []:
        if getattr(block, "type", None) == "text":
            out.append(block.text)
        elif isinstance(block, dict) and block.get("type") == "text":
            out.append(block.get("text", ""))
    return "".join(out).strip()


def _parse_json(text: str) -> dict[str, Any]:
    """Parse the model's JSON, tolerating stray prose / code fences."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise


async def analyze_move(client: Any, evidence: MoveEvidence, *,
                       model: str = "claude-sonnet-4-6") -> MoveAnalysis:
    """Ask Claude to rank candidate drivers for the move described by ``evidence``."""
    user_msg = (
        "Explain this stock move. Evidence (the ONLY facts you may cite):\n\n"
        + json.dumps(asdict(evidence), indent=2, default=str)
    )
    resp = await client.create(
        model=model,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
        tools=[],
        max_tokens=1500,
    )
    data = _parse_json(_extract_text(resp))
    drivers = [
        CandidateDriver(
            driver=d.get("driver", ""),
            plausibility=d.get("plausibility", "low"),
            evidence=d.get("evidence", ""),
            testable_hypothesis=d.get("testable_hypothesis", ""),
        )
        for d in data.get("candidate_drivers", [])
    ]
    return MoveAnalysis(
        ticker=evidence.ticker,
        window=f"{evidence.start}..{evidence.end}",
        verdict=data.get("verdict", "mixed"),
        summary=data.get("summary", ""),
        candidate_drivers=drivers,
        cannot_determine=data.get("cannot_determine", []),
    )
