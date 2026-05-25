"""Build a survivorship-clean, PIT, liquidity-filtered broad US-equity universe
from Polygon, for the universe-breadth alpha experiment.

PIT membership: /v3/reference/tickers?date=<as_of> gives common stocks as they
existed on as_of — INCLUDING names that later delisted (no hindsight). Liquidity
filter: trailing median dollar volume from Polygon grouped-daily bars (one call
per trading day, computed ONLY from data <= as_of). Output: top-N tickers, one
per line, to data/universe_broad_pit_<as_of>.txt — feed to the EDGAR backfill
and build_snapshot.

Usage: uv run python scripts/research/build_broad_universe.py [AS_OF] [TOP_N]
"""
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
KEY = os.getenv("POLYGON_API_KEY") or os.getenv("MASSIVE_API_KEY")
BASE = "https://api.polygon.io"
MAJOR = {"XNYS", "XNAS", "XASE"}

AS_OF = sys.argv[1] if len(sys.argv) > 1 else "2024-01-02"
TOP_N = int(sys.argv[2]) if len(sys.argv) > 2 else 2000
LIQUIDITY_DAYS = 50          # trailing trading days for the dollar-volume rank
MIN_PRICE = 5.0


def _get(url):
    for attempt in range(4):
        r = requests.get(url, timeout=40)
        if r.status_code == 429:
            time.sleep(1.5 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("rate-limited")


def pit_cs(as_of: str) -> set[str]:
    url = (f"{BASE}/v3/reference/tickers?market=stocks&type=CS&active=true"
           f"&date={as_of}&limit=1000&apiKey={KEY}")
    out = set()
    while url:
        j = _get(url)
        for r in j.get("results") or []:
            if r.get("primary_exchange") in MAJOR and r.get("ticker"):
                out.add(r["ticker"].upper())
        nxt = j.get("next_url")
        url = f"{nxt}&apiKey={KEY}" if nxt else None
        time.sleep(0.15)
    return out


def liquidity(as_of: str, eligible: set[str]) -> dict[str, dict]:
    """Median daily dollar volume + last close per ticker over the trailing
    window, from grouped-daily bars (only dates strictly before as_of)."""
    end = date.fromisoformat(as_of) - timedelta(days=1)
    start = end - timedelta(days=int(LIQUIDITY_DAYS * 1.6) + 10)  # cal days -> ~50 trading
    acc: dict[str, list] = {}
    last_close: dict[str, float] = {}
    d = end
    seen = 0
    while d >= start and seen < LIQUIDITY_DAYS:
        url = (f"{BASE}/v2/aggs/grouped/locale/us/market/stocks/{d.isoformat()}"
               f"?adjusted=true&apiKey={KEY}")
        j = _get(url)
        res = j.get("results") or []
        if res:
            seen += 1
            for b in res:
                t = (b.get("T") or "").upper()
                if t in eligible and b.get("c") and b.get("v"):
                    acc.setdefault(t, []).append(b["c"] * b["v"])
                    last_close.setdefault(t, b["c"])  # most recent first (descending)
        d -= timedelta(days=1)
        time.sleep(0.1)
    import statistics
    out = {}
    for t, vols in acc.items():
        out[t] = {"med_dollar_vol": statistics.median(vols), "last_close": last_close.get(t, 0.0)}
    return out


def main():
    if not KEY:
        sys.exit("no POLYGON_API_KEY")
    print(f"PIT common stocks as-of {AS_OF} ...")
    eligible = pit_cs(AS_OF)
    print(f"  {len(eligible)} major-exchange CS")
    print(f"ranking by trailing-{LIQUIDITY_DAYS}d median $volume ...")
    liq = liquidity(AS_OF, eligible)
    ranked = sorted(
        (t for t, m in liq.items() if m["last_close"] >= MIN_PRICE),
        key=lambda t: liq[t]["med_dollar_vol"], reverse=True,
    )
    top = ranked[:TOP_N]
    out_path = ROOT / "data" / f"universe_broad_pit_{AS_OF}.txt"
    out_path.write_text(
        f"# PIT survivorship-clean broad universe, as-of {AS_OF}\n"
        f"# major-exchange common stocks, price>=${MIN_PRICE}, top {len(top)} by "
        f"trailing-{LIQUIDITY_DAYS}d median $volume\n"
        + "\n".join(top) + "\n")
    print(f"  {len(liq)} priced; wrote top {len(top)} to {out_path}")
    print(f"  liquidity cut: #{len(top)} med $vol = "
          f"${liq[top[-1]]['med_dollar_vol']/1e6:.1f}M/day" if top else "")


if __name__ == "__main__":
    main()
