#!/usr/bin/env python
"""Dispersion premium EXISTENCE gate — CBOE implied correlation vs forward realized.

Standalone. Modifies no tracked files. BACKTEST/MEASUREMENT ONLY. FREE existence
gate — no options data, indices + equity prices only.

This is the correlation-priced cousin of vrp_study.py (short index vol / long
single-name vol). A dispersion SELLER is, after vega-neutralizing, SHORT IMPLIED
CORRELATION: it profits when index-implied correlation systematically EXCEEDS the
subsequent realized average pairwise correlation of constituents. This script tests
ONLY whether that premium EXISTS — the gate before paying for option surfaces.

  (A) implied_corr(t) = CBOE COR3M (and COR1M) CLOSE at date t, /100 -> [0,1].
      COR* is a 1-/3-month-AHEAD implied average pairwise correlation of the top-50.
  (B) realized_corr over the FORWARD window matched to the tenor (t+1..t+H;
      H=63 for COR3M, H=21 for COR1M) = average pairwise correlation of constituent
      daily log-returns via the index-vs-constituent variance identity:
          rho = (var_index - sum_i w_i^2 var_i) / ((sum_i w_i sigma_i)^2 - sum_i w_i^2 var_i)
      var_index from SPY; var_i/sigma_i from the top-N liquid constituents present at t;
      EQUAL-WEIGHT (w_i = 1/N) for the gate (sign/significance robust to weighting).
  (C) spread_t = implied_corr(t) - realized_corr_fwd(t).  Hypothesis: mean(spread) > 0.

PRE-REGISTERED CONSTRUCTION (lookahead-safe, clone of vrp_study build_buckets):
  - implied set at t0 (COR close, KNOWN at t0); realized uses returns STRICTLY AFTER
    t0 (t0+1..t0+H). Payoff/spread STAMPED at settle = t0+H, never at t0.
  - NON-OVERLAPPING H-td buckets (i += H) -> honest IID stats, no overlap inflation.
  - anchor_offset PHASE SWEEP (0..H-1): per house rule project_phase_luck_capstone,
    never trust a single anchor. Report phase-averaged mean/median +- spread.
  - Both legs of the identity use the SAME forward window and the SAME [0,1] scale.

PRE-REGISTERED EXISTENCE GATE (set BEFORE looking; green-lights the $79 Stage-1
options backtest only if ALL hold):
  1. implied_corr > realized in >= 60% of non-overlapping windows.
  2. mean spread clearly positive (and phase-averaged median positive across the
     anchor-offset sweep).
  3. the premium does NOT entirely vanish/invert in the stress window(s) — some
     erosion in a corr-spike is expected and fine; TOTAL inversion (mean spread < 0
     across the stress window) would mean the seller is unpaid exactly when it matters.
Otherwise: NO-SHIP, do not spend.

HISTORY-DEPTH CAVEAT (flagged loudly in the verdict): the realized leg is built from
frozen snapshots. Stitched snapshots reach 2018-11 -> 2026-01, which DOES cover the
Feb-2018 Volmageddon tail and the Mar-2020 COVID correlation spike (only via snapshot
2c853f10c6638fc0). It does NOT reach 2008 / Aug-2011. A PASS here is necessary-not-
sufficient; the crash tail still wants deeper history before any options spend.

Usage:
    uv run python scripts/dispersion_premium_study.py --tenor 3M
    uv run python scripts/dispersion_premium_study.py --tenor 1M --top-n 50 --output reports/dispersion_premium_study.json
    uv run python scripts/dispersion_premium_study.py --smoke      # synthetic self-test, no fetch
"""
from __future__ import annotations

import argparse
import io
import json
import math
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "data" / "corr_cache"
SNAP_DIR = ROOT / "data" / "snapshots"
TD_PER_YEAR = 252
TENORS = {"1M": 21, "3M": 63}
COR_SYM = {"1M": "COR1M", "3M": "COR3M"}
CBOE_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/{sym}_History.csv"

# Stitch order: prefer the EARLIER-starting snapshot up to its end on overlap, so
# (date,ticker) dedup never produces duplicate dates. 2c85 is the ONLY snapshot
# covering the Mar-2020 COVID correlation spike — the tail the thesis lives/dies on.
STITCH_SNAPSHOTS = [
    "2c853f10c6638fc0",  # 2018-11-28 -> 2021-12-31  (Feb-2018 partial? no -> starts 11/28; covers Mar-2020 COVID)
    "04baa0a97fec8c1c",  # 2021-05-17 -> 2024-09-10
    "9f448161ca59e465",  # 2022-11-28 -> 2026-01-02  (broad PIT, 2000 names)
]

# Stress windows we MUST surface (correlation-spike kill zones). 2018-02 only partly
# reachable (snap starts 2018-11), flagged present=False if absent.
WATCH_WINDOWS = ["2018-02", "2020-03", "2022", "2024-08", "2025-04"]


# --------------------------------------------------------------------------- #
# Metrics — local copies (task forbids modifying tracked files; per-script
# copies are the repo convention; mirrors vrp_study.py:70-119).
# --------------------------------------------------------------------------- #
def ann_sharpe(rets: pd.Series, periods_per_year: int) -> float:
    r = rets.dropna()
    if r.empty:
        return 0.0
    mu = r.mean()
    sigma = r.std(ddof=1)
    if sigma == 0 or np.isnan(sigma):
        return 0.0
    return float(mu / sigma * math.sqrt(periods_per_year))


def ar1_adjusted_sharpe(rets: pd.Series, periods_per_year: int) -> tuple[float, float, float]:
    """Returns (raw_sharpe, ar1, adj_sharpe). Variance-ratio shrink: S*sqrt((1-a)/(1+a))."""
    r = rets.dropna()
    raw = ann_sharpe(r, periods_per_year)
    if len(r) < 3:
        return raw, 0.0, raw
    ac1 = r.autocorr(1)
    if ac1 is None or np.isnan(ac1) or not (-1 < ac1 < 1):
        return raw, float(ac1) if ac1 is not None and not np.isnan(ac1) else 0.0, raw
    adj = raw * math.sqrt((1 - ac1) / (1 + ac1))
    return raw, float(ac1), float(adj)


def sharpe_se(sharpe: float, n: int) -> float:
    if n <= 1:
        return float("nan")
    return math.sqrt((1.0 + 0.5 * sharpe * sharpe) / n)


def max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    return float((equity / equity.cummax() - 1.0).min())


def stats_block(s: pd.Series) -> dict:
    s = s.dropna()
    if s.empty:
        return {"n": 0}
    return {
        "n": int(len(s)),
        "mean": float(s.mean()),
        "median": float(s.median()),
        "std": float(s.std(ddof=1)) if len(s) > 1 else 0.0,
        "min": float(s.min()),
        "max": float(s.max()),
        "pct_positive": float((s > 0).mean() * 100.0),
    }


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    idx = pd.to_datetime(df.index)
    if isinstance(idx, pd.DatetimeIndex) and idx.tz is not None:
        idx = idx.tz_localize(None)
    df.index = idx.normalize()
    return df[~df.index.duplicated(keep="last")].sort_index()


# --------------------------------------------------------------------------- #
# Data — CBOE implied correlation, cached parquet under data/corr_cache/
# --------------------------------------------------------------------------- #
def fetch_cboe_corr(tenor: str, refresh: bool = False) -> pd.Series:
    """Daily CBOE implied-correlation CLOSE, rescaled /100 -> [0,1]. Cached.

    WebFetch truncates the CSV body ~2013; we use urllib to pull the FULL file.
    """
    sym = COR_SYM[tenor]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"{sym.lower()}_daily.parquet"
    if cache.exists() and not refresh:
        v = pd.read_parquet(cache)
    else:
        url = CBOE_URL.format(sym=sym)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        raw = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
        df = pd.read_csv(io.StringIO(raw))
        df["DATE"] = pd.to_datetime(df["DATE"], format="%m/%d/%Y")
        v = df.set_index("DATE")[["CLOSE"]].rename(columns={"CLOSE": "corr_pts"})
        v = _normalize(v)
        v.to_parquet(cache)
    # SCALE: COR* in points (~6-90); /100 -> implied avg pairwise corr in [0,1].
    # Documented assumption; the SPREAD the gate tests is scale-robust, but BOTH
    # legs must be pinned to [0,1] (gotcha #2) so we rescale here, once.
    s = (v["corr_pts"] if "corr_pts" in v.columns else v.iloc[:, 0]) / 100.0
    return _normalize(s.to_frame("implied"))["implied"]


# --------------------------------------------------------------------------- #
# Data — constituent + SPY panel, stitched from frozen snapshots
# --------------------------------------------------------------------------- #
def _load_snapshot_long(sid: str) -> tuple[pd.DataFrame, pd.Series]:
    """Returns (constituent_close_wide [date x ticker], spy_close_series)."""
    base = SNAP_DIR / sid
    p = pd.read_parquet(base / "prices.parquet")
    if "date" in p.columns and "ticker" in p.columns:  # long
        p["date"] = pd.to_datetime(p["date"])
        wide = p.pivot_table(index="date", columns="ticker", values="Close")
    else:  # wide fallback: index already dates, columns tickers
        wide = p.copy()
        wide.index = pd.to_datetime(wide.index)
    wide.index = pd.DatetimeIndex(wide.index).tz_localize(None).normalize()

    spy_path = base / "spy.parquet"
    spy = pd.read_parquet(spy_path)
    if "date" in spy.columns:
        spy["date"] = pd.to_datetime(spy["date"])
        spy_close = spy.set_index("date")["Close"]
    else:
        spy.index = pd.to_datetime(spy.index)
        spy_close = spy["Close"]
    spy_close.index = pd.DatetimeIndex(spy_close.index).tz_localize(None).normalize()
    spy_close = spy_close[~spy_close.index.duplicated(keep="last")].sort_index()
    return wide, spy_close


def load_stitched_panel(snapshots: list[str]) -> tuple[pd.DataFrame, pd.Series, list[dict]]:
    """Stitch snapshot constituent panels + SPY, preferring earlier-starting snaps
    on overlap (dedup by date). Returns (close_wide, spy_close, provenance)."""
    panels: list[tuple[str, pd.DataFrame, pd.Series, pd.Timestamp, pd.Timestamp]] = []
    for sid in snapshots:
        wide, spy = _load_snapshot_long(sid)
        if wide.empty:
            continue
        panels.append((sid, wide, spy, wide.index.min(), wide.index.max()))
    panels.sort(key=lambda x: x[3])  # by start date

    # Each snapshot owns the date range from its start up to the NEXT snapshot's
    # start (exclusive); the last owns everything to its end. No duplicate dates.
    prov = []
    const_parts, spy_parts = [], []
    for k, (sid, wide, spy, start, end) in enumerate(panels):
        lo = start
        hi = panels[k + 1][3] if k + 1 < len(panels) else end + pd.Timedelta(days=1)
        cmask = (wide.index >= lo) & (wide.index < hi)
        smask = (spy.index >= lo) & (spy.index < hi)
        cpart = wide.loc[cmask]
        const_parts.append(cpart)
        spy_parts.append(spy.loc[smask])
        prov.append({
            "snapshot": sid,
            "owns_from": str(lo.date()),
            "owns_to_excl": str(hi.date()),
            "n_dates": int(cmask.sum()),
            "n_tickers": int(cpart.dropna(axis=1, how="all").shape[1]),
            "spy_present": bool(smask.sum() > 0),
        })

    const = pd.concat(const_parts, axis=0)
    const = const[~const.index.duplicated(keep="last")].sort_index()
    spy_close = pd.concat(spy_parts, axis=0)
    spy_close = spy_close[~spy_close.index.duplicated(keep="last")].sort_index()
    return const, spy_close, prov


# --------------------------------------------------------------------------- #
# Realized average-pairwise correlation via the index-variance identity
# --------------------------------------------------------------------------- #
def _select_top_n(const: pd.DataFrame, t0_pos: int, dates: pd.DatetimeIndex,
                  window: int, top_n: int, min_cov: float) -> list[str]:
    """Top-N liquid names with >= min_cov coverage over the FORWARD window.

    Liquidity proxy = trailing-21d median Close (no volume in the wide Close panel,
    so we rank by recent price level as a coarse cap proxy; equal-weight makes the
    exact ranking non-critical per scope report). Coverage is measured on the
    forward window so the variance identity has complete data.
    """
    fwd = const.iloc[t0_pos + 1: t0_pos + 1 + window]
    cov = fwd.notna().mean(axis=0)
    eligible = cov[cov >= min_cov].index
    if len(eligible) == 0:
        return []
    # trailing 21d median price as the (coarse) liquidity/size proxy
    lo = max(0, t0_pos - 21)
    trail = const.iloc[lo: t0_pos + 1][eligible].median(axis=0)
    ranked = trail.sort_values(ascending=False).index.tolist()
    return ranked[:top_n]


def realized_avg_pairwise_corr(spy_logret: pd.Series, const_logret: pd.DataFrame,
                               names: list[str]) -> float | None:
    """Equal-weight realized avg pairwise corr over the window via the identity.

    rho = (var_index - sum w_i^2 var_i) / ((sum w_i sigma_i)^2 - sum w_i^2 var_i)
    Guards: drop if <2 names, denom ~0, or NaN. Clip to [-1, 1].
    """
    names = [n for n in names if n in const_logret.columns]
    if len(names) < 2:
        return None
    sub = const_logret[names].dropna(axis=1, how="any")  # forward window already sliced
    if sub.shape[1] < 2 or sub.shape[0] < 2:
        return None
    w = 1.0 / sub.shape[1]
    var_i = sub.var(ddof=0)
    sigma_i = np.sqrt(var_i)
    var_index = float(spy_logret.var(ddof=0))
    sum_w2_var = float((w ** 2 * var_i).sum())
    sum_w_sigma_sq = float((w * sigma_i).sum()) ** 2
    denom = sum_w_sigma_sq - sum_w2_var
    if not np.isfinite(denom) or abs(denom) < 1e-12:
        return None
    rho = (var_index - sum_w2_var) / denom
    if not np.isfinite(rho):
        return None
    return float(np.clip(rho, -1.0, 1.0))


# --------------------------------------------------------------------------- #
# Core: non-overlapping forward buckets, lookahead-safe (clone build_buckets)
# --------------------------------------------------------------------------- #
def build_corr_buckets(implied: pd.Series, spy_close: pd.Series, const: pd.DataFrame,
                       window: int, top_n: int, min_cov: float,
                       anchor_offset: int = 0) -> pd.DataFrame:
    """Non-overlapping forward buckets. Row per settled bucket.

    t0 = bucket start (implied corr KNOWN at t0's close).
    realized window = constituent + SPY log-returns over t0+1..t0+window (forward).
    settle = t0+window. Spread STAMPED at settle (never at t0).
    """
    # Common calendar = dates where BOTH SPY and the constituent panel exist.
    cal = const.index.intersection(spy_close.index).sort_values()
    const = const.reindex(cal)
    spy_close = spy_close.reindex(cal)
    implied_aligned = implied.reindex(cal)  # NaN where CBOE has no row for that date

    spy_logret = np.log(spy_close).diff()
    const_logret = np.log(const).diff()

    dates = cal
    n = len(dates)
    rows = []
    i = anchor_offset
    while i + window < n:
        t0 = dates[i]
        imp = implied_aligned.iloc[i]
        if pd.isna(imp):
            i += window
            continue
        settle = dates[i + window]
        names = _select_top_n(const, i, dates, window, top_n, min_cov)
        if len(names) < max(2, int(0.8 * min(top_n, 50))):  # require breadth
            i += window
            continue
        fwd_spy = spy_logret.iloc[i + 1: i + 1 + window].dropna()
        fwd_const = const_logret.iloc[i + 1: i + 1 + window]
        if len(fwd_spy) < window:
            i += window
            continue
        rho = realized_avg_pairwise_corr(fwd_spy, fwd_const, names)
        if rho is None:
            i += window
            continue
        rows.append({
            "t0": t0,
            "settle": settle,
            "implied_corr": float(imp),
            "realized_corr": float(rho),
            "spread": float(imp) - float(rho),
            "n_names": len(names),
        })
        i += window  # non-overlapping

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.set_index("settle").sort_index()  # stamp at settlement
    return df


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def by_year(spread: pd.Series) -> dict:
    res = {}
    for yr, grp in spread.groupby(spread.index.year):
        res[str(int(yr))] = {
            "n": int(len(grp)),
            "mean_spread": round(float(grp.mean()), 4),
            "median_spread": round(float(grp.median()), 4),
            "pct_positive": round(float((grp > 0).mean() * 100), 1),
        }
    return res


def watch_window_table(df: pd.DataFrame) -> dict:
    res = {}
    for tag in WATCH_WINDOWS:
        if len(tag) == 4:
            mask = df.index.year == int(tag)
        else:
            y, m = tag.split("-")
            mask = (df.index.year == int(y)) & (df.index.month == int(m))
        grp = df[mask]
        if grp.empty:
            res[tag] = {"present": False}
            continue
        res[tag] = {
            "present": True,
            "n": int(len(grp)),
            "mean_spread": round(float(grp["spread"].mean()), 4),
            "min_spread": round(float(grp["spread"].min()), 4),
            "max_realized_corr": round(float(grp["realized_corr"].max()), 4),
            "mean_implied_corr": round(float(grp["implied_corr"].mean()), 4),
            "inverted": bool(grp["spread"].mean() < 0),  # total inversion = seller unpaid
        }
    return res


def run(implied: pd.Series, spy_close: pd.Series, const: pd.DataFrame, prov: list[dict],
        tenor: str, top_n: int, min_cov: float,
        start: str | None, end: str | None) -> dict:
    window = TENORS[tenor]
    if start:
        ts = pd.Timestamp(start)
        const = const[const.index >= ts]; spy_close = spy_close[spy_close.index >= ts]
    if end:
        ts = pd.Timestamp(end)
        const = const[const.index <= ts]; spy_close = spy_close[spy_close.index <= ts]

    # ---- PHASE SWEEP over anchor_offset 0..window-1 (house rule: never one anchor) ----
    phase_rows = []
    base_df = None
    for off in range(window):
        df = build_corr_buckets(implied, spy_close, const, window, top_n, min_cov, anchor_offset=off)
        if df.empty:
            continue
        sb = stats_block(df["spread"])
        phase_rows.append({
            "offset": off, "n": sb["n"], "mean": sb["mean"],
            "median": sb["median"], "pct_positive": sb["pct_positive"],
        })
        if off == 0:
            base_df = df
    if not phase_rows:
        raise SystemExit("No buckets formed — check snapshot/CBOE date overlap.")
    if base_df is None:
        # offset 0 produced nothing; fall back to the first non-empty offset's df
        first_off = phase_rows[0]["offset"]
        base_df = build_corr_buckets(implied, spy_close, const, window, top_n, min_cov, anchor_offset=first_off)

    phase_means = np.array([p["mean"] for p in phase_rows])
    phase_meds = np.array([p["median"] for p in phase_rows])
    phase_pos = np.array([p["pct_positive"] for p in phase_rows])
    phase_summary = {
        "n_offsets": len(phase_rows),
        "mean_of_means": float(np.mean(phase_means)),
        "median_of_means": float(np.median(phase_means)),
        "mean_spread_min": float(np.min(phase_means)),
        "mean_spread_max": float(np.max(phase_means)),
        "median_of_medians": float(np.median(phase_meds)),
        "mean_pct_positive": float(np.mean(phase_pos)),
        "pct_positive_min": float(np.min(phase_pos)),
    }

    # ---- PART A: premium existence on the offset-0 (base) buckets ----
    spread = base_df["spread"]
    spread_stats = stats_block(spread)
    raw_s, ac1, adj_s = ar1_adjusted_sharpe(spread, periods_per_year=TD_PER_YEAR // window)
    se = sharpe_se(raw_s, len(spread))

    yr = by_year(spread)
    watch = watch_window_table(base_df)

    # ---- PART B: lightweight short-correlation PnL proxy ----
    # Seller is short implied corr: per-bucket payoff proportional to the spread.
    # Vol-target sized so the series is comparable; NOT the options book.
    unit = spread.copy()
    mvol = unit.std(ddof=1)
    target = 0.10 / math.sqrt(TD_PER_YEAR / window)
    scale = (target / mvol) if (mvol and not np.isnan(mvol) and mvol > 0) else 1.0
    pnl = unit * scale
    eq = (1 + pnl).cumprod()
    p_raw, p_ac1, p_adj = ar1_adjusted_sharpe(pnl, periods_per_year=TD_PER_YEAR // window)

    # ---- PRE-REGISTERED EXISTENCE GATE ----
    bar1_pct_pos = spread_stats.get("pct_positive", 0) >= 60.0
    bar2_mean_pos = (spread_stats.get("mean", 0) > 0) and (phase_summary["median_of_medians"] > 0) \
        and (phase_summary["mean_of_means"] > 0)
    # stress: not TOTALLY inverted. PASS if every PRESENT watch window is not inverted
    # (mean spread >= 0). Some erosion fine; total inversion in stress = fail.
    present_watch = {k: v for k, v in watch.items() if v.get("present")}
    stress_inversions = [k for k, v in present_watch.items() if v.get("inverted")]
    bar3_stress_ok = len(present_watch) > 0 and len(stress_inversions) == 0
    # house-rule phase robustness: phase-averaged median positive
    bar4_phase_pos = phase_summary["median_of_medians"] > 0 and phase_summary["mean_pct_positive"] >= 60.0

    ship = bool(bar1_pct_pos and bar2_mean_pos and bar3_stress_ok and bar4_phase_pos)

    covid_present = watch.get("2020-03", {}).get("present", False)
    span = (str(base_df["t0"].min().date()), str(base_df.index.max().date()))

    return {
        "tenor": tenor,
        "window_td": window,
        "params": {"top_n": top_n, "min_cov": min_cov, "weighting": "equal",
                   "non_overlapping": True, "cor_divisor": 100.0,
                   "realized_method": "index-variance-identity, equal-weight top-N"},
        "history": {
            "bucket_span": {"first_t0": span[0], "last_settle": span[1],
                            "n_buckets_offset0": int(len(base_df))},
            "snapshot_provenance": prov,
            "covid_2020_03_reachable": covid_present,
            "depth_caveat": ("Stitched snapshots reach ~2018-11 -> 2026-01. Covers "
                             "Mar-2020 COVID corr spike (snap 2c853f10c6638fc0) but NOT "
                             "2008 / Aug-2011. PASS is necessary-not-sufficient; the "
                             "crash tail wants deeper history before any options spend."),
        },
        "partA_premium_existence": {
            "spread_stats": spread_stats,
            "ar1_adj_sharpe_of_spread": round(p_adj, 3),
            "spread_ar1": round(ac1, 3),
            "spread_sharpe_se_approx": round(se, 3) if not np.isnan(se) else None,
            "interpretation": "spread = implied_corr(t) - forward realized avg pairwise corr (t->t+H)",
        },
        "phase_sweep": {"summary": phase_summary, "per_offset": phase_rows[:window]},
        "by_year": yr,
        "stress_windows": watch,
        "partB_short_corr_pnl_proxy": {
            "note": "spread-proportional, vol-target sized; NOT the options book (existence gate only)",
            "ann_sharpe_iid": round(p_raw, 3),
            "ann_sharpe_ar1_adj": round(p_adj, 3),
            "total_ret_pct": round((eq.iloc[-1] - 1) * 100, 2),
            "max_dd_pct": round(max_drawdown(eq) * 100, 2),
            "pct_positive": round(float((pnl > 0).mean() * 100), 1),
        },
        "gate": {
            "1_pct_positive_ge_60": bool(bar1_pct_pos),
            "2_mean_spread_clearly_positive": bool(bar2_mean_pos),
            "3_no_total_inversion_in_stress": bool(bar3_stress_ok),
            "4_phase_averaged_median_positive": bool(bar4_phase_pos),
            "stress_windows_present": list(present_watch.keys()),
            "stress_inversions": stress_inversions,
            "PASS": ship,
        },
        "verdict": _verdict(ship, bar1_pct_pos, bar2_mean_pos, bar3_stress_ok, bar4_phase_pos,
                            spread_stats, phase_summary, present_watch, stress_inversions,
                            covid_present),
    }


def _verdict(ship, b1, b2, b3, b4, ss, phase, present_watch, inversions, covid) -> str:
    cov_note = ("COVID Mar-2020 corr spike IS in-sample." if covid
                else "WARNING: COVID Mar-2020 NOT reached — crash tail untested.")
    if ship:
        return (f"GATE PASS -> green-light the $79 Stage-1 options backtest. "
                f"Implied > realized in {ss.get('pct_positive', 0):.0f}% of non-overlapping "
                f"windows; mean spread {ss.get('mean', 0):+.4f} (phase-avg median "
                f"{phase['median_of_medians']:+.4f}); no total inversion in stress "
                f"({', '.join(present_watch) or 'none present'}). {cov_note} "
                f"NECESSARY-NOT-SUFFICIENT: 2018-11->2026 only, no 2008/2011 — confirm "
                f"crash tail on deeper data before any options spend.")
    fails = []
    if not b1:
        fails.append(f"implied>realized only {ss.get('pct_positive', 0):.0f}% of windows (<60%)")
    if not b2:
        fails.append(f"mean spread not clearly positive (mean {ss.get('mean', 0):+.4f}, "
                     f"phase-med {phase['median_of_medians']:+.4f})")
    if not b3:
        fails.append(f"TOTAL INVERSION in stress {inversions} — seller unpaid when it matters")
    if not b4:
        fails.append(f"phase-averaged median not robustly positive "
                     f"({phase['median_of_medians']:+.4f}, {phase['mean_pct_positive']:.0f}% pos)")
    return f"GATE FAIL -> do NOT spend. {'; '.join(fails)}. {cov_note}"


# --------------------------------------------------------------------------- #
# Smoke: synthetic data, proves the pipeline reaches a gate block (no fetch)
# --------------------------------------------------------------------------- #
def smoke() -> dict:
    rng = np.random.default_rng(11)
    n = 4 * TD_PER_YEAR
    idx = pd.bdate_range("2019-01-02", periods=n)
    n_names = 60

    # One common factor + idiosyncratic. Low realized corr normally; one corr-spike
    # window where idiosyncratic vol collapses (everything moves together -> corr->1).
    spike = np.zeros(n)
    spike[500:540] = 1.0  # the corr-spike window
    common = rng.normal(0, 1, n) * (0.006 + 0.03 * spike)
    const = {}
    for k in range(n_names):
        idio_scale = np.where(spike > 0, 0.002, 0.012)  # idio collapses in spike -> high corr
        idio = rng.normal(0, 1, n) * idio_scale
        r = common + idio
        const[f"T{k:02d}"] = 100 * np.exp(np.cumsum(r))
    const_df = pd.DataFrame(const, index=idx)

    # SPY ~ equal-weight basket return
    basket_r = np.log(const_df).diff().mean(axis=1).fillna(0)
    spy = pd.Series(100 * np.exp(np.cumsum(basket_r)), index=idx, name="spy")

    # Implied corr: trailing realized basket-vs-mean corr proxy, marked UP (richer than
    # realized) outside the spike, so the seller is paid on average.
    trail_common_vol = pd.Series(common, index=idx).rolling(63).std().bfill()
    trail_idio_vol = np.log(const_df).diff().std(axis=1).rolling(63).mean().bfill()
    base_corr = (trail_common_vol ** 2 / (trail_common_vol ** 2 + trail_idio_vol ** 2)).clip(0.05, 0.95)
    implied = (base_corr * 1.25 + 0.05).clip(0.05, 0.98)  # marked richer
    implied.name = "implied"

    prov = [{"snapshot": "SMOKE", "owns_from": str(idx[0].date()),
             "owns_to_excl": str(idx[-1].date()), "n_dates": n,
             "n_tickers": n_names, "spy_present": True}]
    res = run(implied, spy, const_df, prov, tenor="3M", top_n=50, min_cov=0.99,
              start=None, end=None)
    ok = (
        "verdict" in res
        and "gate" in res
        and isinstance(res["gate"]["PASS"], bool)
        and res["history"]["bucket_span"]["n_buckets_offset0"] > 5
        and res["phase_sweep"]["summary"]["n_offsets"] > 1
        # the engineered spike must show as the worst (most-negative-spread) stress-ish bucket
        and res["partA_premium_existence"]["spread_stats"]["min"]
            < res["partA_premium_existence"]["spread_stats"]["mean"]
    )
    return {"smoke_pass": bool(ok),
            "n_buckets": res["history"]["bucket_span"]["n_buckets_offset0"],
            "n_offsets": res["phase_sweep"]["summary"]["n_offsets"],
            "mean_spread": round(res["partA_premium_existence"]["spread_stats"]["mean"], 4),
            "pct_positive": res["partA_premium_existence"]["spread_stats"]["pct_positive"],
            "gate_pass": res["gate"]["PASS"],
            "verdict": res["verdict"][:90]}


def main() -> int:
    ap = argparse.ArgumentParser(description="Dispersion premium existence gate (CBOE implied vs forward realized corr).")
    ap.add_argument("--tenor", choices=["1M", "3M"], default="3M", help="COR tenor / forward window (default 3M=63td)")
    ap.add_argument("--top-n", type=int, default=50, help="liquid constituent subset size (COR* indexes top-50)")
    ap.add_argument("--min-cov", type=float, default=0.99, help="min forward-window coverage per name (default 0.99)")
    ap.add_argument("--start", default=None, help="window start YYYY-MM-DD")
    ap.add_argument("--end", default=None, help="window end YYYY-MM-DD")
    ap.add_argument("--snapshots", nargs="*", default=None, help="override stitch snapshot ids")
    ap.add_argument("--output", default=None, help="write JSON report here")
    ap.add_argument("--refresh", action="store_true", help="bypass CBOE parquet cache, re-fetch")
    ap.add_argument("--smoke", action="store_true", help="synthetic self-test, no data fetch")
    args = ap.parse_args()

    if args.smoke:
        out = smoke()
        print(json.dumps(out, indent=2))
        return 0 if out["smoke_pass"] else 1

    implied = fetch_cboe_corr(args.tenor, refresh=args.refresh)
    snaps = args.snapshots or STITCH_SNAPSHOTS
    const, spy_close, prov = load_stitched_panel(snaps)
    res = run(implied, spy_close, const, prov, args.tenor, args.top_n, args.min_cov,
              args.start, args.end)

    print(json.dumps(res, indent=2, default=str))
    print("\n" + "=" * 70)
    print(res["verdict"])
    print("=" * 70)

    if args.output:
        outp = Path(args.output)
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(json.dumps(res, indent=2, default=str))
        print(f"\nwrote {outp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
