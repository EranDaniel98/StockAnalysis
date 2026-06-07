"""#3 PoC — LLM-extracted filing-text signal as a cross-sectional factor.

Tests the one genuinely-orthogonal signal type left: does the *tone* of a firm's
most recent 8-K (material-events filing) predict forward returns cross-sectionally?
Pipeline per (ticker, as_of): newest 8-K filed in the trailing `lookback_days`
(PIT — filing_date <= as_of) -> primary-doc text (truncated) -> gpt-4o-mini scores
forward-looking tone in [-1, +1] -> sidecar json. A separate step computes IC.

Bounded by design: --max-calls hard-caps OpenAI usage (PoC ~$0.30 on gpt-4o-mini).
This is a hypothesis test, NOT a production ingest — if the IC is null we stop here.

    uv run python -m scripts.build_filing_signal --snapshot-id ed270407fd89cf60 \
        --n-tickers 80 --dates 2024-09-03,2025-01-02,2025-05-01 --max-calls 300
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
log = logging.getLogger("filing_signal")

SNAP_ROOT = Path("data/snapshots")
TONE_PROMPT = (
    "You are a sell-side analyst. Read this excerpt from a company's 8-K filing and "
    "rate its FORWARD-LOOKING tone for the stock over the next 1-3 months on a scale "
    "from -1.0 (clearly negative: guidance cut, litigation, impairment, executive "
    "departure under duress) to +1.0 (clearly positive: raised guidance, strong "
    "preliminary results, accretive deal, buyback). 0.0 = neutral/administrative. "
    "Respond with ONLY a JSON object: {\"tone\": <float>, \"reason\": \"<=12 words\"}."
)


def _strip_html(t: str) -> str:
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"&#?\w+;", " ", t)
    return re.sub(r"\s+", " ", t).strip()


async def _latest_8k_text(client, cik: int, as_of: pd.Timestamp, lookback_days: int) -> str | None:
    """Most recent 8-K primary-doc text filed in (as_of - lookback, as_of], stripped + truncated."""
    try:
        sub = await client.fetch_submissions(cik)
    except Exception:
        return None
    recent = sub.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accns = recent.get("accessionNumber", [])
    docs = recent.get("primaryDocument", [])
    lo = (as_of - pd.Timedelta(days=lookback_days)).date().isoformat()
    hi = as_of.date().isoformat()
    for form, fd, acc, doc in zip(forms, dates, accns, docs):
        if form == "8-K" and lo < fd <= hi:  # arrays are newest-first -> first match is latest
            try:
                txt = await client.fetch_filing_text(cik, acc, doc)
            except Exception:
                return None
            return _strip_html(txt)[:6000]
    return None


def _score_tone(oai, text: str) -> float | None:
    try:
        r = oai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": TONE_PROMPT},
                      {"role": "user", "content": text}],
            max_tokens=40, temperature=0,
            response_format={"type": "json_object"},
        )
        return float(json.loads(r.choices[0].message.content)["tone"])
    except Exception as exc:  # noqa: BLE001
        log.warning("tone score failed: %s", str(exc)[:80])
        return None


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot-id", required=True)
    ap.add_argument("--n-tickers", type=int, default=80, help="liquid subset size for the PoC")
    ap.add_argument("--dates", required=True, help="comma list of as_of dates (YYYY-MM-DD)")
    ap.add_argument("--lookback-days", type=int, default=90)
    ap.add_argument("--max-calls", type=int, default=300, help="hard cap on OpenAI calls (cost guard)")
    args = ap.parse_args()
    load_dotenv()

    from openai import OpenAI
    from src.market_data.edgar.client import EDGARClient, get_ticker_to_cik

    snap = SNAP_ROOT / args.snapshot_id
    manifest = json.loads((snap / "manifest.json").read_text(encoding="utf-8"))
    universe = manifest["tickers"]
    # Liquid subset = highest median dollar-volume names (tradeable + likely to file 8-Ks).
    raw = pd.read_parquet(snap / "prices.parquet")
    raw["date"] = pd.to_datetime(raw["date"])
    dv = (raw.assign(dv=raw["Close"] * raw["Volume"]).groupby("ticker")["dv"].median()
          .reindex(universe).dropna().sort_values(ascending=False))
    tickers = list(dv.head(args.n_tickers).index)
    dates = [pd.Timestamp(d) for d in args.dates.split(",")]

    cache = Path("data/edgar_cache")
    t2c_path = cache / "ticker_cik.json"
    t2c = {k: int(v) for k, v in json.loads(t2c_path.read_text(encoding="utf-8")).items()} if t2c_path.exists() else {}

    oai = OpenAI()
    client = EDGARClient()
    calls = 0
    out: dict[str, dict] = {}  # date_iso -> {ticker: tone}
    try:
        if not t2c:
            t2c = await get_ticker_to_cik(client)
        for d in dates:
            day: dict[str, float] = {}
            for t in tickers:
                if calls >= args.max_calls:
                    log.warning("hit --max-calls=%d cap", args.max_calls); break
                cik = t2c.get(t.upper()) or t2c.get(t.replace(".", "-").upper())
                if cik is None:
                    continue
                text = await _latest_8k_text(client, cik, d, args.lookback_days)
                if not text or len(text) < 200:
                    continue
                tone = _score_tone(oai, text)
                calls += 1
                if tone is not None:
                    day[t] = tone
            out[d.date().isoformat()] = day
            print(f"  {d.date()}: scored {len(day)} tickers (calls so far {calls})", flush=True)
    finally:
        await client.aclose()

    sidecar = snap / "filing_tone_signal.json"
    sidecar.write_text(json.dumps(out), encoding="utf-8")
    n_scores = sum(len(v) for v in out.values())
    print(f"wrote {sidecar} | {n_scores} tone scores across {len(dates)} dates | {calls} OpenAI calls")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
