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


# 8-K Item codes -> plain label. The codes alone are a strong signal of WHAT a
# filing is about (2.02 = earnings, 5.02 = exec change, 1.01 = a deal, ...).
ITEM_8K_LABELS: dict[str, str] = {
    "1.01": "Entry into Material Agreement", "1.02": "Termination of Material Agreement",
    "1.03": "Bankruptcy/Receivership", "2.01": "Completion of Acquisition/Disposition",
    "2.02": "Results of Operations (earnings)", "2.03": "Material Financial Obligation",
    "2.04": "Triggering of an Obligation", "2.05": "Exit/Disposal Costs",
    "2.06": "Material Impairment", "3.01": "Delisting/Listing Notice",
    "3.02": "Unregistered Equity Sale", "3.03": "Modification to Securityholder Rights",
    "4.01": "Change in Accountant", "4.02": "Non-Reliance on Prior Financials",
    "5.01": "Change in Control", "5.02": "Director/Officer Departure or Election",
    "5.03": "Amendments to Articles/Bylaws", "5.07": "Shareholder Vote Results",
    "7.01": "Reg FD Disclosure", "8.01": "Other Events",
    "9.01": "Financial Statements & Exhibits",
}


def label_items(items: str | None) -> str:
    """'8.01,9.01' -> '8.01 Other Events; 9.01 Financial Statements & Exhibits'."""
    if not items:
        return ""
    return "; ".join(
        f"{c.strip()} {ITEM_8K_LABELS.get(c.strip(), '')}".strip()
        for c in items.split(",") if c.strip()
    )


def html_to_text(html: str, max_chars: int = 2500) -> str:
    """Strip a filing's HTML to collapsed plain text, truncated. Keeps the
    Item narrative on the 8-K cover page; the LLM cites it as evidence."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(separator=" ")).strip()
    return text[:max_chars]


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
    filings: list[dict[str, str]] = field(default_factory=list)  # {form, date, items, excerpt}
    short_interest_delta_pct: float | None = None  # +=more shorts, -=covering
    short_interest_days_to_cover: float | None = None
    news: list[dict[str, str]] = field(default_factory=list)  # {date, title, sentiment, publisher}
    peers: list[str] = field(default_factory=list)            # related tickers (validation targets)
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
    peers: list[str] = field(default_factory=list)  # carried from evidence for the report

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
- Use the news feed (with per-ticker sentiment when present) and the 8-K filing \
excerpts to identify the actual catalyst — these are now provided, so a sharp \
single-day move with matching news should be named, not left as "cannot determine."
- For EACH candidate driver, give a TESTABLE cross-sectional hypothesis: how \
would one express this driver as a factor and check it across the whole universe \
out-of-sample (so a "find similar names" follow-up gets validated, not traded on \
a hunch). When the driver is stock-specific, name the provided `peers` as the \
concrete candidate set to screen + validate.

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
        max_tokens=4000,
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
        peers=list(evidence.peers),
    )
