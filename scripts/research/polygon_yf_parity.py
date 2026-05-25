# /// script
# dependencies = ["yfinance", "pandas", "numpy", "scipy", "requests", "python-dotenv"]
# ///
"""
Cutover gate (Phase E): does Polygon reproduce yfinance's prices + momentum,
and is it actually deterministic? Run BEFORE flipping data.source to polygon.

Three checks:
  1. Close parity — median/p95/max relative |diff| of split/div-adjusted Close
     on overlapping dates across ~30 liquid large-caps + SPY.
  2. Momentum parity — recompute the REAL src.factors.momentum.momentum_12_1 on
     both sources; cross-sectional rank-IC. CUTOVER CRITERION: rank-IC >= ~0.95.
  3. Determinism — fetch the same Polygon window twice; assert bit-identical
     (the documented yfinance failure: same backtest drifted Sharpe 2.08->1.60).

Output: reports/polygon_yf_parity.json + console verdict.
Usage: uv run scripts/research/polygon_yf_parity.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from dotenv import load_dotenv
from scipy import stats

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.data.polygon_fetcher import PolygonDataFetcher  # noqa: E402  (light import chain)

# Load momentum directly by path — src.factors.__init__ eagerly imports
# composite/quality/value (DB + EDGAR deps) which aren't in this isolated env.
_spec = importlib.util.spec_from_file_location("_momentum", ROOT / "src" / "factors" / "momentum.py")
_mom = importlib.util.module_from_spec(_spec)
sys.modules["_momentum"] = _mom  # so @dataclass can resolve cls.__module__
_spec.loader.exec_module(_mom)
momentum_12_1 = _mom.momentum_12_1

TICKERS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "V", "MA",
           "UNH", "HD", "PG", "JNJ", "XOM", "CVX", "KO", "PEP", "COST", "WMT",
           "BAC", "ABBV", "CRM", "ADBE", "NFLX", "AMD", "INTC", "CSCO", "ORCL", "MCD", "SPY"]
PERIOD = "2y"
CUTOVER_RANK_IC = 0.95


def norm_yf(df: pd.DataFrame) -> pd.DataFrame:
    """yfinance frame -> naive-UTC date index, canonical OHLCV (match adapter)."""
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    idx = pd.to_datetime(df.index, utc=True).tz_convert("UTC").tz_localize(None).normalize()
    df.index = pd.DatetimeIndex(idx, name="Date")
    cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
    return df[cols].sort_index()


def fetch_yf(ticker: str) -> pd.DataFrame | None:
    for attempt in range(3):
        try:
            h = yf.Ticker(ticker).history(period=PERIOD, interval="1d", auto_adjust=True)
        except Exception:
            h = None
        if h is not None and not h.empty:
            return norm_yf(h)
        time.sleep(1.0 * (attempt + 1))
    return None


def main():
    pf = PolygonDataFetcher()  # no config/cache; key from .env
    print(f"fetching {len(TICKERS)} tickers x {PERIOD} from Polygon (adjusted) ...")
    poly = pf.fetch_batch(TICKERS, period=PERIOD, interval="1d", adjusted=True)
    print(f"  polygon: {len(poly)}/{len(TICKERS)}")
    print("fetching from yfinance (sequential, throttle-tolerant) ...")
    yfp = {}
    for t in TICKERS:
        df = fetch_yf(t)
        if df is not None:
            yfp[t] = df
        time.sleep(0.4)
    print(f"  yfinance: {len(yfp)}/{len(TICKERS)}")

    common = sorted(set(poly) & set(yfp))

    # --- 1. Close parity on overlapping dates
    rels, per_ticker = [], {}
    for t in common:
        a, b = poly[t]["Close"], yfp[t]["Close"]
        idx = a.index.intersection(b.index)
        if len(idx) < 30:
            continue
        rel = ((a.loc[idx] - b.loc[idx]).abs() / b.loc[idx].abs()).replace([np.inf], np.nan).dropna()
        rels.append(rel)
        per_ticker[t] = {"overlap_days": int(len(idx)),
                         "median_rel_diff": round(float(rel.median()), 6),
                         "max_rel_diff": round(float(rel.max()), 6)}
    allrel = pd.concat(rels) if rels else pd.Series(dtype=float)
    close_parity = {
        "tickers_compared": len(per_ticker),
        "median_rel_diff": round(float(allrel.median()), 6) if len(allrel) else None,
        "p95_rel_diff": round(float(allrel.quantile(0.95)), 6) if len(allrel) else None,
        "max_rel_diff": round(float(allrel.max()), 6) if len(allrel) else None,
        "worst_tickers": dict(sorted(per_ticker.items(),
                                     key=lambda kv: kv[1]["max_rel_diff"], reverse=True)[:5])}

    # --- 2. Momentum parity (the REAL factor)
    as_of = pd.Timestamp.today().normalize()
    mp = momentum_12_1(poly, as_of).rename(columns={"raw": "raw_poly"})[["ticker", "raw_poly"]]
    my = momentum_12_1(yfp, as_of).rename(columns={"raw": "raw_yf"})[["ticker", "raw_yf"]]
    merged = mp.merge(my, on="ticker")
    if len(merged) >= 5:
        rank_ic = float(stats.spearmanr(merged["raw_poly"], merged["raw_yf"]).statistic)
        pear = float(np.corrcoef(merged["raw_poly"], merged["raw_yf"])[0, 1])
    else:
        rank_ic = pear = float("nan")
    momentum_parity = {"n_names": int(len(merged)), "rank_ic": round(rank_ic, 4),
                       "pearson_raw": round(pear, 4),
                       "passes_cutover": bool(rank_ic >= CUTOVER_RANK_IC)}

    # --- 3. Determinism
    a = pf.fetch_price_data("SPY", PERIOD, "1d", adjusted=True)
    b = pf.fetch_price_data("SPY", PERIOD, "1d", adjusted=True)
    determinism = {"spy_fetched_twice_identical": bool(a is not None and b is not None and a.equals(b))}

    report = {"gate": "polygon_vs_yfinance_parity", "period": PERIOD,
              "coverage": {"polygon": len(poly), "yfinance": len(yfp), "common": len(common)},
              "close_parity": close_parity, "momentum_parity": momentum_parity,
              "determinism": determinism}
    (ROOT / "reports" / "polygon_yf_parity.json").write_text(json.dumps(report, indent=2))

    print("\n" + "=" * 64)
    print(f"coverage: polygon {len(poly)} | yfinance {len(yfp)} | common {len(common)}")
    cp = close_parity
    print(f"\nClose parity ({cp['tickers_compared']} tickers): median rel diff "
          f"{cp['median_rel_diff']}, p95 {cp['p95_rel_diff']}, max {cp['max_rel_diff']}")
    mpar = momentum_parity
    print(f"\nMomentum parity: rank-IC={mpar['rank_ic']} pearson={mpar['pearson_raw']} "
          f"(n={mpar['n_names']})  ->  {'PASS' if mpar['passes_cutover'] else 'FAIL'} "
          f"(cutover >= {CUTOVER_RANK_IC})")
    print(f"\nDeterminism: SPY fetched twice identical = {determinism['spy_fetched_twice_identical']}")
    print(f"\nwrote {ROOT / 'reports' / 'polygon_yf_parity.json'}")


if __name__ == "__main__":
    main()
