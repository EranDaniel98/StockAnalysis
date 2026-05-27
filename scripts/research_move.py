"""Explain why a stock moved — and turn each driver into a testable hypothesis.

  uv run python -m scripts.research_move --ticker SNDK --lookback-days 30

Gathers HARD evidence (return decomposition vs SPY + sector ETF, earnings
surprise, EDGAR filings in the window, short-interest change, volume spike),
then asks Claude to rank the CANDIDATE drivers — never "the cause" — with each
phrased as a cross-sectional hypothesis you can validate with the phase-envelope
harness before trading any "similar names". See src/research_agent/move_analyzer.py.

Works for any ticker (live Polygon/yfinance/EDGAR); short-interest + sector are
best-effort and reported as gaps when our coverage doesn't include the name.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from src.research_agent.move_analyzer import (
    SECTOR_ETF,
    MoveEvidence,
    analyze_move,
)

logger = logging.getLogger("research_move")


def _window_metrics(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp):
    """(return_pct, (biggest_day_date, biggest_day_pct), volume_spike_ratio)."""
    w = df[(df.index >= start) & (df.index <= end)]
    if len(w) < 2:
        return None
    ret = float(w["Close"].iloc[-1] / w["Close"].iloc[0] - 1.0) * 100.0
    daily = (w["Close"].pct_change().dropna() * 100.0)
    bday = None
    if not daily.empty:
        idx = daily.abs().idxmax()
        bday = (str(idx.date()), round(float(daily.loc[idx]), 2))
    spike = None
    if "Volume" in w.columns:
        trailing = df[df.index < start]["Volume"].tail(60)
        if len(trailing) and trailing.mean():
            spike = round(float(w["Volume"].mean() / trailing.mean()), 2)
    return round(ret, 2), bday, spike


def _earnings_in_window(ticker, start, end):
    """(in_window, date_str, surprise_pct) — PEAD-relevant earnings <= end and
    not older than ~7d before the window start."""
    try:
        from src.factors.earnings_cache import load_earnings_history
        eh = load_earnings_history(ticker)
    except Exception as e:  # noqa: BLE001
        logger.debug("earnings lookup failed for %s: %s", ticker, e)
        return False, None, None
    if eh is None or eh.empty:
        return False, None, None
    lo = start - pd.Timedelta(days=7)
    win = eh[(eh.index >= lo) & (eh.index <= end)]
    if win.empty:
        return False, None, None
    row = win.sort_index().iloc[-1]
    date = str(win.sort_index().index[-1].date())
    surprise = row.get("Surprise(%)")
    surprise = round(float(surprise), 2) if pd.notna(surprise) else None
    return True, date, surprise


_FILING_FORMS = ("8-K", "8-K/A", "10-Q", "10-K", "SC 13D", "SC 13G")


async def _edgar_filings(ticker, start, end, *, max_texts: int = 3):
    """In-window filings with 8-K Item labels + text excerpts for the 8-Ks
    (the event filings). None if EDGAR unreachable / no CIK match."""
    from src.research_agent.move_analyzer import html_to_text, label_items
    try:
        from src.market_data.edgar.client import EDGARClient, get_ticker_to_cik
        client = EDGARClient()
        try:
            cik = (await get_ticker_to_cik(client)).get(ticker.upper())
            if cik is None:
                return None
            recent = (await client.fetch_submissions(int(cik))).get("filings", {}).get("recent", {})
            forms, dates = recent.get("form", []), recent.get("filingDate", [])
            items, accns = recent.get("items", []), recent.get("accessionNumber", [])
            docs = recent.get("primaryDocument", [])
            s, e = start.date().isoformat(), end.date().isoformat()
            rows = []
            for i, f in enumerate(forms):
                d = dates[i] if i < len(dates) else ""
                if not (s <= d <= e) or f not in _FILING_FORMS:
                    continue
                rows.append({"form": f, "date": d,
                             "items": label_items(items[i] if i < len(items) else ""),
                             "_accn": accns[i] if i < len(accns) else "",
                             "_doc": docs[i] if i < len(docs) else ""})
            # Read the text of the most recent 8-Ks — that's where the "why" is.
            for r in [r for r in rows if r["form"].startswith("8-K")][:max_texts]:
                if r["_accn"] and r["_doc"]:
                    try:
                        html = await client.fetch_filing_text(int(cik), r["_accn"], r["_doc"])
                        r["excerpt"] = html_to_text(html)
                    except Exception as ex:  # noqa: BLE001
                        logger.debug("filing text fetch failed %s: %s", r["_accn"], ex)
        finally:
            await client.aclose()
    except Exception as e:  # noqa: BLE001
        logger.debug("EDGAR lookup failed for %s: %s", ticker, e)
        return None
    for r in rows:  # drop internal fetch fields before the LLM sees them
        r.pop("_accn", None)
        r.pop("_doc", None)
    return rows[:12]


async def _short_delta(ticker, end, window_days):
    """Short-interest change over the window (signed %), or None if not covered."""
    try:
        from src.db.session import dispose_engine, get_sessionmaker
        from src.factors.short_interest_delta import fetch_short_delta
        sm = get_sessionmaker()
        try:
            async with sm() as session:
                df = await fetch_short_delta(session, [ticker.upper()], end, window_days=window_days)
        finally:
            await dispose_engine()
    except Exception as e:  # noqa: BLE001
        logger.debug("short-interest lookup failed for %s: %s", ticker, e)
        return None
    if df is None or df.empty:
        return None
    row = df[df["ticker"] == ticker.upper()]
    if row.empty:
        return None
    return round(float(row["delta_pct"].iloc[0]) * 100.0, 2)


def _render_md(a) -> str:
    lines = [f"# Why did {a.ticker} move? ({a.window})", "",
             f"**Verdict:** {a.verdict}", "", a.summary, "",
             "## Candidate drivers (ranked, NOT proven cause)"]
    for i, d in enumerate(a.candidate_drivers, 1):
        lines += [f"### {i}. {d.driver}  _(plausibility: {d.plausibility})_",
                  f"- **Evidence:** {d.evidence}",
                  f"- **Testable hypothesis:** {d.testable_hypothesis}", ""]
    if a.cannot_determine:
        lines += ["## Cannot determine from the evidence"]
        lines += [f"- {x}" for x in a.cannot_determine]
    lines += ["", "_Drivers are candidates, not causes. Validate any 'similar "
              "names' idea cross-sectionally (phase_envelope.py) before trading._"]
    return "\n".join(lines)


async def _run(args) -> int:
    from src.config_loader import Config
    from src.data.sector_cache import lookup_sector
    from src.storage.universe_loader import load_prices

    config = Config()
    ticker = args.ticker.upper()
    end = pd.Timestamp(args.end) if args.end else pd.Timestamp(datetime.now(timezone.utc).date())
    start = pd.Timestamp(args.start) if args.start else end - pd.Timedelta(days=args.lookback_days)
    missing: list[str] = ["live news / analyst price-target actions "
                          "(SEC filing text IS read below, but no news-wire feed)"]

    # Sector -> ETF proxy.
    sector = None
    try:
        sector = lookup_sector(ticker)
    except Exception as e:  # noqa: BLE001
        logger.debug("sector lookup failed: %s", e)
    etf = SECTOR_ETF.get(sector) if sector else None
    if etf is None:
        missing.append(f"sector benchmark (no ETF mapped for sector {sector!r})")

    # Prices: ticker + SPY (+ sector ETF if mapped).
    want = [ticker, "SPY"] + ([etf] if etf else [])
    prices = load_prices(want, config=config)
    if ticker not in prices or prices[ticker].empty:
        logger.error("no price data for %s — cannot analyze.", ticker)
        return 1
    tm = _window_metrics(prices[ticker], start, end)
    if tm is None:
        logger.error("window %s..%s too short for %s.", start.date(), end.date(), ticker)
        return 1
    ticker_ret, bday, vspike = tm
    spy_ret = (_window_metrics(prices["SPY"], start, end) or [0.0])[0] if "SPY" in prices else 0.0
    sector_ret = None
    if etf and etf in prices:
        sm_ = _window_metrics(prices[etf], start, end)
        sector_ret = sm_[0] if sm_ else None

    # Catalysts (best-effort, run the async ones concurrently).
    earnings_t = asyncio.to_thread(_earnings_in_window, ticker, start, end)
    filings, sdelta, (e_in, e_date, e_surp) = await asyncio.gather(
        _edgar_filings(ticker, start, end),
        _short_delta(ticker, end, args.lookback_days),
        earnings_t,
    )
    if filings is None:
        missing.append("EDGAR filings (no CIK match / SEC unreachable)")
        filings = []
    if sdelta is None:
        missing.append("short interest (ticker not in our FINRA coverage)")

    evidence = MoveEvidence(
        ticker=ticker, start=start.date().isoformat(), end=end.date().isoformat(),
        ticker_return_pct=ticker_ret, market_return_pct=round(spy_ret, 2),
        sector_label=sector, sector_etf=etf, sector_return_pct=sector_ret,
        biggest_day_date=bday[0] if bday else None,
        biggest_day_pct=bday[1] if bday else None,
        volume_spike_ratio=vspike,
        earnings_in_window=e_in, earnings_date=e_date, earnings_surprise_pct=e_surp,
        filings=filings, short_interest_delta_pct=sdelta,
        missing_sources=missing,
    )

    try:
        from src.research_agent.llm_client import AnthropicClient
        client = AnthropicClient()
    except Exception as e:  # noqa: BLE001
        logger.error("LLM unavailable (%s). Evidence gathered but not synthesized.", e)
        print(json.dumps(asdict_evidence(evidence), indent=2, default=str))
        return 2

    analysis = await analyze_move(client, evidence, model=args.model)

    out_dir = Path("reports")
    out_dir.mkdir(exist_ok=True)
    stem = f"move_{ticker}_{end.date().isoformat()}"
    (out_dir / f"{stem}.json").write_text(json.dumps(
        {"evidence": asdict_evidence(evidence), "analysis": analysis.to_dict()},
        indent=2, default=str))
    md = _render_md(analysis)
    (out_dir / f"{stem}.md").write_text(md, encoding="utf-8")
    print(md)
    print(f"\nwrote reports/{stem}.json + .md")
    return 0


def asdict_evidence(ev) -> dict:
    from dataclasses import asdict
    return asdict(ev)


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    load_dotenv()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ticker", required=True)
    p.add_argument("--end", default=None, help="YYYY-MM-DD window end (default today)")
    p.add_argument("--start", default=None, help="YYYY-MM-DD window start (default end - lookback)")
    p.add_argument("--lookback-days", type=int, default=30)
    p.add_argument("--model", default="claude-sonnet-4-6")
    args = p.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
