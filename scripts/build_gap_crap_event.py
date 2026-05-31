"""Panel idea #4 — Earnings Gap-Up Opening-Range Failure ("gap & crap"), intraday.

Hypothesis: in a complacent regime, an earnings gap-up that is REJECTED in the first
30 min (VWAP < open, price < open on heavy volume) reveals institutional VWAP-
distribution into retail liquidity -> fade it intraday. Distinct from PEAD (which buys
CONFIRMED gaps). Test = 3-arm event study (the panel's required control):
  A  earnings gap-up + red first-30min  (THE TRADE: short 10:01 -> 15:55)
  B  earnings gap-up + green first-30min (PEAD continuation; should differ from A)
  C  NON-earnings gap-up + red first-30min (generic opening-range fade — the control;
     A must beat C or the "earnings" part adds nothing)
All intraday, no overnight. Polygon minute bars (no Postgres needed).

    uv run python -m scripts.build_gap_crap_event --snapshot-id ed270407fd89cf60 --max-events 400
"""

from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

SNAP_ROOT = Path("data/snapshots")
GAP_MIN = 0.04          # gap-up threshold
VIX_MAX = 15.0          # complacent-regime filter
RELVOL_MIN = 0.10       # first-30min volume >= 10% of 20d ADV


def _series(p, cols=("Close", "close", "adj_close", "Adj Close")):
    df = pd.read_parquet(p)
    dc = next((c for c in ("date", "Date") if c in df.columns), df.columns[0])
    cc = next((c for c in cols if c in df.columns), None)
    return df.set_index(pd.to_datetime(df[dc]))[cc].sort_index()


def _intraday_features(client, ticker: str, day: pd.Timestamp, adv20: float):
    """Fetch one session's minute bars; return (open, vwap30, px1000, px1001, px1555, relvol30) or None."""
    bars = client.aggregates(ticker, day.date(), day.date(), timespan="minute",
                             multiplier=1, adjusted=False)
    if not bars:
        return None
    df = pd.DataFrame(bars)
    df["et"] = pd.to_datetime(df["t"], unit="ms", utc=True).dt.tz_convert("America/New_York")
    df = df[(df["et"].dt.time >= pd.Timestamp("09:30").time()) &
            (df["et"].dt.time < pd.Timestamp("16:00").time())].sort_values("et")
    if len(df) < 60:
        return None
    day_open = float(df.iloc[0]["o"])
    w30 = df[df["et"].dt.time < pd.Timestamp("10:00").time()]
    if w30.empty or w30["v"].sum() <= 0:
        return None
    vwap30 = float((w30["c"] * w30["v"]).sum() / w30["v"].sum())
    # adv20 is DOLLAR volume -> first-30min DOLLAR volume for a unit-consistent ratio.
    relvol30 = float((w30["c"] * w30["v"]).sum() / adv20) if adv20 > 0 else 0.0

    def at(tstr):
        sub = df[df["et"].dt.time <= pd.Timestamp(tstr).time()]
        return float(sub.iloc[-1]["c"]) if len(sub) else None

    return day_open, vwap30, at("10:00"), at("10:01"), at("15:55"), relvol30


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot-ids", default="ed270407fd89cf60",
                    help="comma list — pool events across windows for power")
    ap.add_argument("--max-events", type=int, default=400, help="cap minute-bar fetches PER snapshot")
    args = ap.parse_args()

    from dotenv import load_dotenv
    load_dotenv()
    from src.factors.earnings_cache import load_earnings_histories
    from src.market_data.polygon import PolygonClient

    rng = np.random.default_rng(7)
    cand = []  # (ticker, day, is_earnings, adv20)
    for sid in args.snapshot_ids.split(","):
        snap = SNAP_ROOT / sid
        if not snap.exists():
            continue
        manifest = json.loads((snap / "manifest.json").read_text(encoding="utf-8"))
        universe = manifest["tickers"]
        raw = pd.read_parquet(snap / "prices.parquet"); raw["date"] = pd.to_datetime(raw["date"])
        close = raw.pivot(index="date", columns="ticker", values="Close").sort_index()
        opn = raw.pivot(index="date", columns="ticker", values="Open").sort_index()
        dollar = (raw.assign(dv=raw["Close"] * raw["Volume"])
                  .pivot(index="date", columns="ticker", values="dv").sort_index())
        spy = _series(snap / "spy.parquet"); spy_sma50 = spy.rolling(50).mean()
        vix = _series(snap / "vix.parquet")
        dates = close.index
        earnings = load_earnings_histories(universe, max_age_hours=10 ** 9)
        earn_set = {t: set(pd.DatetimeIndex(eh.index).normalize()) for t, eh in earnings.items() if eh is not None}
        snap_cand = []
        for t in universe:
            if t not in close.columns:
                continue
            c = close[t]; o = opn[t]
            for i in range(60, len(dates) - 1):
                d = dates[i]
                if c.iloc[i - 1] <= 0 or pd.isna(o.iloc[i]) or pd.isna(c.iloc[i - 1]):
                    continue
                if o.iloc[i] / c.iloc[i - 1] - 1.0 <= GAP_MIN:
                    continue
                sd = spy.index.asof(d); vd = vix.index.asof(d)
                if pd.isna(sd) or spy.loc[sd] <= (spy_sma50.loc[sd] if sd in spy_sma50 else np.inf):
                    continue
                if pd.isna(vd) or vix.loc[vd] >= VIX_MAX:
                    continue
                adv20 = float(dollar[t].iloc[i - 20:i].median())
                if adv20 < 50e6 or c.iloc[i] < 5:
                    continue
                is_earn = d.normalize() in earn_set.get(t, set()) or (dates[i - 1].normalize() in earn_set.get(t, set()))
                snap_cand.append((t, d, is_earn, adv20))
        # per-snapshot cap (balanced earnings/non-earnings), then pool
        rng.shuffle(snap_cand)
        e = [x for x in snap_cand if x[2]][: args.max_events // 2]
        ne = [x for x in snap_cand if not x[2]][: args.max_events - len(e)]
        cand.extend(e + ne)
        print(f"  {sid[:8]}: {len(snap_cand)} candidates -> {len(e)+len(ne)} sampled", flush=True)
    rng.shuffle(cand)
    todo = cand  # already per-snapshot balanced + capped above
    print(f"{len(cand)} pooled gap-up candidates ({sum(x[2] for x in cand)} earnings) | "
          f"fetching {len(todo)} minute-bar days", flush=True)

    client = PolygonClient()
    rows = []
    for n, (t, d, is_earn, adv20) in enumerate(todo, 1):
        try:
            f = _intraday_features(client, t, d, adv20)
        except Exception:
            f = None
        if f is None:
            continue
        op, vwap30, px1000, px1001, px1555, relvol30 = f
        if None in (px1000, px1001, px1555) or relvol30 < RELVOL_MIN:
            continue
        red30 = (vwap30 < op) and (px1000 < op)
        short_ret = -(px1555 / px1001 - 1.0)  # fade: short at 10:01, cover 15:55
        rows.append({"ticker": t, "date": d.isoformat(), "is_earnings": is_earn,
                     "red30": red30, "short_ret": short_ret})
        if n % 50 == 0:
            print(f"  {n}/{len(todo)} fetched", flush=True)

    df = pd.DataFrame(rows)
    out = Path("reports") / "gap_crap_events_pooled.json"
    df.to_json(out, orient="records")
    print(f"\nwrote {out} | {len(df)} usable events")
    if df.empty:
        return 1

    def arm(mask, label):
        s = df[mask]["short_ret"]
        if len(s) < 5:
            print(f"  {label:42s} n={len(s)} (too few)"); return
        t = s.mean() / (s.std() / np.sqrt(len(s))) if s.std() > 0 else 0
        print(f"  {label:42s} n={len(s):>4} mean fade-ret {s.mean()*100:+.3f}%  t={t:+.2f}  win {100*(s>0).mean():.0f}%")

    print("\n=== 3-arm intraday fade event study (short 10:01 -> 15:55) ===")
    arm(df["is_earnings"] & df["red30"], "A earnings gap-up + red-30m (THE TRADE)")
    arm(df["is_earnings"] & ~df["red30"], "B earnings gap-up + green-30m (PEAD cont.)")
    arm(~df["is_earnings"] & df["red30"], "C non-earnings gap-up + red-30m (CONTROL)")
    print("\nPASS only if A's fade-return > C's (earnings adds over generic gap-fade) AND A t>2.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
