# /// script
# dependencies = ["pandas", "numpy", "requests", "python-dotenv"]
# ///
"""Does Polygon news sentiment predict forward returns? An honest IC check.

We now INGEST per-ticker news sentiment (the /news + /outlook surfaces) but
nothing trades on it. Before it ever influences a decision, measure whether it
has any cross-sectional information coefficient (IC) on forward returns — or
whether it is a dashboard-only signal.

METHOD (lookahead-safe):
  - Per (ticker, day): sentiment score = mean over that ticker's same-day
    articles of {positive:+1, neutral:0, mixed:0, negative:-1} (Polygon's own
    per-ticker `insights` sentiment). Articles published on day t are known by
    that day's close.
  - Forward return = close[t+h]/close[t]-1 (enter at close[t] after seeing the
    day's news). Daily adjusted closes from Polygon.
  - IC = cross-sectional Spearman (rank corr) between sentiment and fwd return,
    computed per day, then averaged. t-stat = mean/std * sqrt(n_days). Pooled
    Spearman reported as a cross-check.

CAVEATS baked into the output: short history (~7wk, 1000-article cap on mega
caps), single regime (includes the 2026-06-05 chip selloff), Polygon sentiment
is strongly positive-skewed, and mega-cap coverage bias. A first signal check,
not a tradeable backtest.

    uv run python -m scripts.research.news_sentiment_ic
    uv run python -m scripts.research.news_sentiment_ic --universe-file data/universe_ai_broad_2026-06-06.txt --since 2026-04-16
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

_SENT = {"positive": 1.0, "neutral": 0.0, "mixed": 0.0, "negative": -1.0}


def _read_universe(path: Path) -> list[str]:
    lines = [ln.strip().upper() for ln in path.read_text(encoding="utf-8").splitlines()]
    return [ln for ln in lines if ln and not ln.startswith("#")]


def _daily_sentiment(client, ticker: str, since: str) -> pd.Series:
    """Mean per-ticker insight sentiment per calendar day. Empty if no news."""
    try:
        arts = client.news(ticker, limit=1000, published_gte=since)
    except Exception:
        return pd.Series(dtype=float)
    rows: list[tuple[str, float]] = []
    for a in arts:
        day = (a.get("published_utc") or "")[:10]
        if not day:
            continue
        for ins in a.get("insights") or []:
            if ins.get("ticker") == ticker and ins.get("sentiment") in _SENT:
                rows.append((day, _SENT[ins["sentiment"]]))
                break
    if not rows:
        return pd.Series(dtype=float)
    df = pd.DataFrame(rows, columns=["day", "s"])
    return df.groupby("day")["s"].mean()


def _daily_closes(client, ticker: str, since: str, end: str) -> pd.Series:
    from src.market_data.polygon import bars_to_frame
    try:
        bars = client.aggregates(ticker, since, end, timespan="day", multiplier=1, adjusted=True)
    except Exception:
        return pd.Series(dtype=float)
    df = bars_to_frame(bars, daily=True)
    if df is None or df.empty:
        return pd.Series(dtype=float)
    s = df["Close"].copy()
    s.index = [d.date().isoformat() for d in s.index]
    return s


def _spearman(a: pd.Series, b: pd.Series) -> float | None:
    """Rank correlation = Pearson of ranks. None if <3 paired points or no variance."""
    m = pd.concat([a, b], axis=1).dropna()
    if len(m) < 3:
        return None
    ra, rb = m.iloc[:, 0].rank(), m.iloc[:, 1].rank()
    if ra.std() == 0 or rb.std() == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--universe-file", default="data/universe_ai_broad_2026-06-06.txt")
    ap.add_argument("--since", default="2026-04-16", help="news + price start (ISO).")
    ap.add_argument("--end", default="2026-06-07")
    ap.add_argument("--horizons", default="1,3,5", help="forward-return horizons in trading days.")
    args = ap.parse_args()

    from src.market_data.polygon import PolygonClient
    client = PolygonClient()
    universe = _read_universe(Path(args.universe_file))
    horizons = [int(h) for h in args.horizons.split(",")]
    print(f"news-sentiment IC | {len(universe)} names | {args.since} -> {args.end} | horizons {horizons}")

    # Fan out news + prices concurrently.
    sent: dict[str, pd.Series] = {}
    px: dict[str, pd.Series] = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        fs = {ex.submit(_daily_sentiment, client, t, args.since): t for t in universe}
        fp = {ex.submit(_daily_closes, client, t, args.since, args.end): t for t in universe}
        for f in as_completed(fs):
            sent[fs[f]] = f.result()
        for f in as_completed(fp):
            px[fp[f]] = f.result()

    n_with_news = sum(1 for s in sent.values() if not s.empty)
    print(f"  names with news: {n_with_news}/{len(universe)}")

    # Build a long panel: (day, ticker, sentiment, fwd_ret_h).
    for h in horizons:
        recs: list[dict] = []
        for t in universe:
            s, p = sent.get(t), px.get(t)
            if s is None or s.empty or p is None or p.empty:
                continue
            pser = p.sort_index()
            days = list(pser.index)
            pos = {d: i for i, d in enumerate(days)}
            for day, sc in s.items():
                i = pos.get(day)
                if i is None or i + h >= len(days):
                    continue
                fwd = pser.iloc[i + h] / pser.iloc[i] - 1.0
                recs.append({"day": day, "ticker": t, "sent": sc, "fwd": float(fwd)})
        panel = pd.DataFrame(recs)
        if panel.empty:
            print(f"\nhorizon {h}d: no overlapping obs.")
            continue

        # Per-day cross-sectional IC, then average.
        ics = []
        for day, g in panel.groupby("day"):
            ic = _spearman(g["sent"], g["fwd"])
            if ic is not None:
                ics.append(ic)
        ics = np.array(ics)
        pooled = _spearman(panel["sent"], panel["fwd"])
        mean_ic = ics.mean() if len(ics) else float("nan")
        std_ic = ics.std(ddof=1) if len(ics) > 1 else float("nan")
        tstat = (mean_ic / std_ic * np.sqrt(len(ics))) if len(ics) > 1 and std_ic > 0 else float("nan")
        # Sign hit-rate of pooled sentiment vs return direction (nonzero sentiment only).
        nz = panel[panel["sent"] != 0]
        hit = (np.sign(nz["sent"]) == np.sign(nz["fwd"])).mean() if len(nz) else float("nan")

        print(f"\nhorizon {h}d:  n_obs={len(panel)}  n_days={len(ics)}")
        print(f"  mean daily IC = {mean_ic:+.4f}  (std {std_ic:.4f}, t={tstat:+.2f})")
        print(f"  pooled Spearman = {pooled:+.4f}" if pooled is not None else "  pooled Spearman = n/a")
        print(f"  directional hit-rate (nonzero sent) = {hit:.3f}  (n={len(nz)})")

    print("\nCAVEATS: ~7wk single-regime window (incl. 2026-06-05 chip selloff); Polygon "
          "sentiment is positive-skewed; mega-cap coverage bias; first signal check, not a backtest.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
