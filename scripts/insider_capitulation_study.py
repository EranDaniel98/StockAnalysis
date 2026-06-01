"""Panel #1 — Distressed-Insider Cluster Buy event study (PRE-REGISTERED).

Tests one hypothesis: do open-market insider CLUSTER buys during idiosyncratic
capitulation predict positive beta-adjusted forward returns? The decision rule
below is pre-registered — this script BUILDS it exactly, it does not tune it.

TRIGGER on date t (t == the FILING date of the 2nd qualifying Form-4; filing_date
is the PIT-available timestamp, transaction_date leaks):
  - resid_63   = R_i[-63,-1] - beta_i * R_SPY[-63,-1]  <= -20%   (beta trailing-only)
  - drawdown_126 <= -25% from trailing 126-day high
  - within trailing 10 CALENDAR days: >=2 unique reportingOwner CIK
    OR a CEO/CFO/Chair, transaction_code 'P' (open-market buy), acquired 'A'
  - total purchase value (10d) >= max($100k, 0.25% * ADV20$)
  - EXCLUDE codes M/A/G/F etc (only 'P'); exclude 10%-owner-ONLY filings.

SIGNAL: B=log1p(buy_value_10d/ADV20$); C=log1p(unique_buyers_10d);
        D=abs(resid_63); S = z(B) + 0.5*z(C) + 0.5*z(D)   (cross-sectional z over events)

ENTRY/EXIT: long at NEXT OPEN after t; hold 20 trading days (primary), 10d & 40d
            robustness; equal-weight; cap 8 concurrent (reported, not enforced in
            the return math — this is an event study of per-event alpha).

PRIMARY METRIC: alpha20 = R_i[t+1,t+20] - beta_i[-252,-21]*R_SPY[t+1,t+20] - 0.003
                (beta strictly from the pre-event [-252,-21] trailing window;
                 -0.003 = round-trip cost charge.)

NULLS:
  - MATCHED-CONTROL: per event, up to 20 pseudo-dates on the SAME ticker that
    satisfy the capitulation conditions but have NO Form-4 'P' within +/-30 days.
    Tests the INSIDER signal above the capitulation-reversal baseline.
  - PERMUTATION: within each calendar year, permute cluster labels across
    capitulated firm-dates (n>=200 shuffles).

SHIP RULE (all must hold):
  median alpha20 > +3%  AND  %-positive >= 55%  AND  permutation p < 0.05
  AND positive median sign in >=2 of {10,20,40}d
  AND leave-COVID-out (drop entry in Feb-May 2020) still positive median.

LOOKAHEAD DISCIPLINE: every filter / beta / resid / drawdown / ADV slices
df.loc[:t] (<= t inclusive). Entry is the first OPEN strictly after t; forward
returns are strictly post-entry. EDGAR filing_date is day-granular (asyncpg date,
no intraday), so the earliest honest entry is next session's open.

USAGE:
  rtk uv run python scripts/insider_capitulation_study.py --limit 5 --start 2018-01-01 --end 2026-05-01
  rtk uv run python scripts/insider_capitulation_study.py                      # full study (do NOT run blind)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select

from src.config_loader import Config
from src.data.fetcher_factory import get_data_fetcher
from src.db.models import InsiderTransaction as Tx
from src.db.session import dispose_engine, get_sessionmaker

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("insider_capitulation_study")

# ---- pre-registered thresholds (DO NOT TUNE) -------------------------------
RESID_63_MAX = -0.20          # idiosyncratic capitulation
DRAWDOWN_126_MAX = -0.25      # trailing-high drawdown
CLUSTER_CAL_DAYS = 10         # calendar-day window for the cluster
MIN_UNIQUE_BUYERS = 2         # OR a top exec (CEO/CFO/Chair)
MIN_BUY_VALUE_ABS = 100_000.0
MIN_BUY_VALUE_ADV_FRAC = 0.0025  # 0.25% of ADV20$
PRICE_FLOOR = 5.0
ADV20_FLOOR = 10_000_000.0
COST_CHARGE = 0.003           # round-trip cost subtracted from alpha
HOLD_DAYS = {"10d": 10, "20d": 20, "40d": 40}
PRIMARY_HOLD = "20d"
MAX_CONCURRENT = 8
CONTROL_NO_FORM4_DAYS = 30    # +/- window that must be clear of any 'P' for a control date
MAX_CONTROLS_PER_EVENT = 20
PERMUTATION_N = 1000          # >= 200 required by spec
TOP_EXEC_KEYWORDS = ("chief executive", "ceo", "chief financial", "cfo",
                     "chair", "chairman", "chairwoman", "chairperson", "president")
COVID_START = pd.Timestamp("2020-02-01")
COVID_END = pd.Timestamp("2020-05-31")


# ============================================================================
# DB access (PIT-correct: filing_date gate added ourselves)
# ============================================================================
async def fetch_all_buys(session, tickers, start: date, end: date) -> pd.DataFrame:
    """All officer/director open-market buys ('P','A') with filing_date in
    [start, end+slack]. Returns a tidy frame; one row per (tx x owner).

    PIT note: we pull by filing_date (the public timestamp). Each row is gated
    again per-event by filing_date <= t downstream.
    """
    stmt = (
        select(
            Tx.ticker, Tx.filing_date, Tx.transaction_date, Tx.owner_cik,
            Tx.owner_name, Tx.owner_role, Tx.officer_title,
            Tx.shares, Tx.price_per_share, Tx.value_usd,
        )
        .where(Tx.transaction_code == "P")
        .where(Tx.acquired_disposed == "A")
        .where(Tx.shares > 0)
        .where(Tx.filing_date >= start)
        .where(Tx.filing_date <= end)
        # exclude 10%-owner-ONLY: require officer or director substring present
        .where(Tx.owner_role.like("%officer%") | Tx.owner_role.like("%director%"))
        .order_by(Tx.ticker.asc(), Tx.filing_date.asc())
    )
    if tickers:
        stmt = stmt.where(Tx.ticker.in_([t.upper() for t in tickers]))
    rows = (await session.execute(stmt)).all()
    if not rows:
        return pd.DataFrame(
            columns=["ticker", "filing_date", "transaction_date", "owner_cik",
                     "owner_name", "owner_role", "officer_title",
                     "shares", "price_per_share", "value_usd"]
        )
    df = pd.DataFrame(rows, columns=[
        "ticker", "filing_date", "transaction_date", "owner_cik",
        "owner_name", "owner_role", "officer_title",
        "shares", "price_per_share", "value_usd",
    ])
    for col in ("shares", "price_per_share", "value_usd"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    # value_usd null fallback = shares * price (rare for 'P'); else NaN
    miss = df["value_usd"].isna()
    df.loc[miss, "value_usd"] = df.loc[miss, "shares"] * df.loc[miss, "price_per_share"]
    df["filing_ts"] = pd.to_datetime(df["filing_date"]).dt.normalize()
    df["txn_ts"] = pd.to_datetime(df["transaction_date"]).dt.normalize()
    return df


async def candidate_tickers(session, start: date, end: date) -> list[str]:
    """Tickers that have at least one qualifying officer/director 'P' buy in window."""
    stmt = (
        select(Tx.ticker)
        .where(Tx.transaction_code == "P")
        .where(Tx.acquired_disposed == "A")
        .where(Tx.shares > 0)
        .where(Tx.filing_date >= start)
        .where(Tx.filing_date <= end)
        .where(Tx.owner_role.like("%officer%") | Tx.owner_role.like("%director%"))
        .group_by(Tx.ticker)
        .order_by(Tx.ticker.asc())
    )
    return [r[0] for r in (await session.execute(stmt)).all()]


# ============================================================================
# Price-derived metrics (all <= t except the forward label)
# ============================================================================
def _aligned_beta(stock_close: pd.Series, spy_close: pd.Series) -> float:
    """CAPM beta over a pre-sliced common window. Mirrors _capm_alpha_beta:
    simple pct_change, inner-join + dropna, len>=30 & var>0 guard."""
    s = stock_close.pct_change().dropna()
    m = spy_close.pct_change().dropna()
    df = pd.concat([s.rename("s"), m.rename("m")], axis=1).dropna()
    if len(df) < 30 or df["m"].var() == 0:
        return 0.0
    return float(df["s"].cov(df["m"]) / df["m"].var())


def resid_63(stock: pd.DataFrame, spy: pd.DataFrame, t: pd.Timestamp) -> float | None:
    """63d beta-neutral residual return using ONLY data <= t."""
    win = stock.loc[:t].tail(64)
    spy_win = spy.loc[:t].tail(64)
    if len(win) < 64 or len(spy_win) < 64:
        return None
    beta = _aligned_beta(win["Close"], spy_win["Close"])
    stock_ret = win["Close"].iloc[-1] / win["Close"].iloc[0] - 1.0
    mkt_ret = spy_win["Close"].iloc[-1] / spy_win["Close"].iloc[0] - 1.0
    return float(stock_ret - beta * mkt_ret)


def drawdown_126(stock: pd.DataFrame, t: pd.Timestamp) -> float | None:
    c = stock.loc[:t]["Close"].tail(126)
    if len(c) < 126:
        return None
    return float((c / c.cummax() - 1.0).min())


def adv20_usd(stock: pd.DataFrame, t: pd.Timestamp) -> float | None:
    w = stock.loc[:t].tail(20)
    if len(w) < 20:
        return None
    return float((w["Close"] * w["Volume"]).mean())


def price_at_t(stock: pd.DataFrame, t: pd.Timestamp) -> float | None:
    c = stock.loc[:t]["Close"]
    if c.empty:
        return None
    return float(c.iloc[-1])


def beta_pre_event(stock: pd.DataFrame, spy: pd.DataFrame, t: pd.Timestamp) -> float:
    """Beta from the [-252,-21] trailing window: drop the last 21 sessions <= t,
    take the prior 252. Strictly pre-event so the capitulation crash doesn't
    contaminate beta used to risk-adjust the label."""
    s = stock.loc[:t]
    m = spy.loc[:t]
    if len(s) < (252 + 21) or len(m) < (252 + 21):
        return 0.0
    s_win = s.iloc[-(252 + 21):-21]
    m_win = m.iloc[-(252 + 21):-21]
    return _aligned_beta(s_win["Close"], m_win["Close"])


def forward_open_return(prices: pd.DataFrame, t: pd.Timestamp, n: int,
                        data_end: pd.Timestamp):
    """Enter at the first OPEN strictly after t, exit at the OPEN n sessions later.

    Survivorship fix: if the stock DELISTS in-horizon (its price series ends well
    before ``data_end`` with fewer than n+1 forward bars), exit at the LAST
    available open — capturing the realized hold-to-delisting return instead of
    silently dropping the (often catastrophic) outcome. This is distinguished
    from a merely RECENT event (t near data_end), which legitimately has no
    forward label yet and is dropped (None, nan, 0) rather than imputed.

    Returns (entry_ts, open_to_open_return, held_bars). ``held_bars`` is n for a
    full hold, or the shorter realized hold when the name delisted early; the SPY
    leg must be measured over the SAME held_bars for a matched beta-adjustment.
    Caveat: Polygon's last bar is the last TRADE, so a bankruptcy's sub-last-trade
    wipeout to ~0 is not fully captured — mildly optimistic, but no longer SILENT."""
    fwd = prices[prices.index > t]
    if len(fwd) < 2:
        return None, np.nan, 0
    delisted = prices.index.max() < (data_end - pd.Timedelta(days=10))
    if len(fwd) < n + 1:
        if not delisted:
            return None, np.nan, 0   # recent event, no label yet — do NOT impute
        exit_i = len(fwd) - 1        # delisted early — hold to last available bar
    else:
        exit_i = n
    entry_open = float(fwd["Open"].iloc[0])
    exit_open = float(fwd["Open"].iloc[exit_i])
    if entry_open <= 0:
        return None, np.nan, 0
    return fwd.index[0], float(exit_open / entry_open - 1.0), exit_i


def forward_spy_return(spy: pd.DataFrame, entry_ts: pd.Timestamp, held: int) -> float:
    """SPY open-to-open return over the SAME ``held`` bars as the stock leg,
    so beta-adjustment uses matched windows (held may be < n on early delisting)."""
    win = spy[spy.index >= entry_ts]
    if held < 1 or len(win) < held + 1:
        return np.nan
    o0 = float(win["Open"].iloc[0])
    on = float(win["Open"].iloc[held])
    if o0 <= 0:
        return np.nan
    return float(on / o0 - 1.0)


# ============================================================================
# Event detection
# ============================================================================
def detect_events(buys_t: pd.DataFrame, stock: pd.DataFrame, spy: pd.DataFrame) -> list[dict]:
    """For one ticker, walk each candidate filing date t (filing of a 'P' buy),
    test the FULL pre-registered trigger using only data <= t, and emit an event
    at the date the 2nd qualifying buy became public (clustered within 10 cal days).

    De-dup: once an event fires at t, suppress further events whose cluster window
    overlaps (avoid re-firing on every subsequent same-cluster filing). We advance
    past the last filing_date in the firing cluster.
    """
    events: list[dict] = []
    buys_t = buys_t.sort_values("filing_ts").reset_index(drop=True)
    filing_dates = sorted(buys_t["filing_ts"].unique())
    suppress_until: pd.Timestamp | None = None

    for t in filing_dates:
        t = pd.Timestamp(t).normalize()
        if suppress_until is not None and t <= suppress_until:
            continue
        # cluster = all PIT-public buys (filing<=t) whose filing is within trailing 10 cal days
        win_start = t - pd.Timedelta(days=CLUSTER_CAL_DAYS)
        cluster = buys_t[(buys_t["filing_ts"] <= t) & (buys_t["filing_ts"] >= win_start)]
        if cluster.empty:
            continue

        unique_buyers = cluster["owner_cik"].nunique()
        roles = (cluster["owner_role"].fillna("") + " " + cluster["officer_title"].fillna("")).str.lower()
        has_top_exec = roles.str.contains("|".join(TOP_EXEC_KEYWORDS), regex=True).any()
        if not (unique_buyers >= MIN_UNIQUE_BUYERS or has_top_exec):
            continue

        # require the cluster to represent at least 2 filings becoming public
        # (the "2nd qualifying Form-4 filing" trigger) — single-filing top-exec
        # buys still need a 2nd public filing to fire the cluster entry.
        if cluster["filing_ts"].nunique() < 2 and not (unique_buyers >= MIN_UNIQUE_BUYERS):
            continue

        # price-derived capitulation filters, all <= t
        px = price_at_t(stock, t)
        if px is None or px < PRICE_FLOOR:
            continue
        adv = adv20_usd(stock, t)
        if adv is None or adv < ADV20_FLOOR:
            continue
        r63 = resid_63(stock, spy, t)
        if r63 is None or r63 > RESID_63_MAX:
            continue
        dd = drawdown_126(stock, t)
        if dd is None or dd > DRAWDOWN_126_MAX:
            continue

        buy_value_10d = float(cluster["value_usd"].sum(skipna=True))
        if not np.isfinite(buy_value_10d) or buy_value_10d <= 0:
            continue
        if buy_value_10d < max(MIN_BUY_VALUE_ABS, MIN_BUY_VALUE_ADV_FRAC * adv):
            continue

        events.append({
            "ticker": cluster["ticker"].iloc[0],
            "t": t,
            "unique_buyers_10d": int(unique_buyers),
            "buy_value_10d": buy_value_10d,
            "adv20_usd": adv,
            "resid_63": r63,
            "drawdown_126": dd,
            "has_top_exec": bool(has_top_exec),
        })
        suppress_until = cluster["filing_ts"].max()

    return events


def detect_control_dates(stock: pd.DataFrame, spy: pd.DataFrame,
                         buy_filing_dates: list[pd.Timestamp],
                         t_min: pd.Timestamp, t_max: pd.Timestamp) -> list[pd.Timestamp]:
    """Pseudo-dates on the SAME ticker that satisfy capitulation (resid_63,
    drawdown_126, price/ADV liquidity) but have NO 'P' buy within +/-30 days.
    Sampled on session dates; tests the insider signal vs capitulation reversal."""
    buy_arr = pd.DatetimeIndex(buy_filing_dates) if buy_filing_dates else pd.DatetimeIndex([])
    sessions = stock.index[(stock.index >= t_min) & (stock.index <= t_max)]
    out: list[pd.Timestamp] = []
    for t in sessions:
        t = pd.Timestamp(t).normalize()
        if len(buy_arr):
            gap = np.abs((buy_arr - t).days)
            if (gap <= CONTROL_NO_FORM4_DAYS).any():
                continue
        px = price_at_t(stock, t)
        if px is None or px < PRICE_FLOOR:
            continue
        adv = adv20_usd(stock, t)
        if adv is None or adv < ADV20_FLOOR:
            continue
        r63 = resid_63(stock, spy, t)
        if r63 is None or r63 > RESID_63_MAX:
            continue
        dd = drawdown_126(stock, t)
        if dd is None or dd > DRAWDOWN_126_MAX:
            continue
        out.append(t)
    return out


# ============================================================================
# Returns + stats
# ============================================================================
def compute_alpha(prices: pd.DataFrame, spy: pd.DataFrame, t: pd.Timestamp,
                  n: int, data_end: pd.Timestamp,
                  charge_cost: bool = True) -> tuple[float, pd.Timestamp | None]:
    """alphaN = R_i[t+1..t+n] - beta_pre*R_SPY[t+1..t+n] - cost (open-to-open).
    Delisting-aware: the stock and SPY legs are measured over the same realized
    hold (shorter than n when the name delists in-horizon)."""
    entry_ts, r_i, held = forward_open_return(prices, t, n, data_end)
    if entry_ts is None or not np.isfinite(r_i) or held < 1:
        return np.nan, None
    r_spy = forward_spy_return(spy, entry_ts, held)
    if not np.isfinite(r_spy):
        return np.nan, None
    beta = beta_pre_event(prices, spy, t)
    alpha = r_i - beta * r_spy - (COST_CHARGE if charge_cost else 0.0)
    return float(alpha), entry_ts


def permutation_pvalue(events_df: pd.DataFrame, n_perm: int, rng: np.random.Generator) -> float:
    """Within each calendar year, permute cluster labels across capitulated
    firm-dates (events + controls pooled per year). The 'label' is event(1) vs
    control(0); statistic = mean alpha20[label==1] - mean alpha20[label==0].
    p = fraction of permutations with statistic >= observed."""
    d = events_df.dropna(subset=["alpha20"]).copy()
    if d.empty or d["is_event"].sum() == 0 or (~d["is_event"]).sum() == 0:
        return float("nan")
    d["year"] = d["entry_ts"].dt.year

    def stat(labels: np.ndarray) -> float:
        a = d["alpha20"].to_numpy()
        ev = a[labels == 1]
        ct = a[labels == 0]
        if len(ev) == 0 or len(ct) == 0:
            return np.nan
        return float(np.nanmean(ev) - np.nanmean(ct))

    d = d.reset_index(drop=True)
    base_labels = d["is_event"].astype(int).to_numpy()
    obs = stat(base_labels)
    if not np.isfinite(obs):
        return float("nan")

    # integer row positions grouped by calendar year (permute labels within year)
    year_pos = {y: np.asarray(idx) for y, idx in d.groupby("year").indices.items()}

    ge = 0
    for _ in range(n_perm):
        perm = base_labels.copy()
        for locs in year_pos.values():
            vals = perm[locs].copy()
            rng.shuffle(vals)
            perm[locs] = vals
        s = stat(perm)
        if np.isfinite(s) and s >= obs:
            ge += 1
    return (ge + 1) / (n_perm + 1)


# ============================================================================
# Orchestration
# ============================================================================
async def run_study(limit: int | None, start: date, end: date, seed: int):
    config = Config()
    fetcher = get_data_fetcher(config, cache=None)
    spy_raw = fetcher.fetch_price_data("SPY", period="10y", interval="1d", adjusted=True)
    if spy_raw is None or spy_raw.empty:
        raise SystemExit("SPY fetch failed — cannot run event study.")
    spy = spy_raw.copy()
    spy.index = pd.to_datetime(spy.index).tz_localize(None).normalize()
    spy = spy[~spy.index.duplicated(keep="last")].sort_index()

    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)

    async with get_sessionmaker()() as session:
        tickers = await candidate_tickers(session, start, end)
        total_candidates = len(tickers)
        if limit:
            tickers = tickers[:limit]
        logger.info("Candidate tickers in window: %d (using %d)", total_candidates, len(tickers))
        all_buys = await fetch_all_buys(session, tickers, start, end)
    await dispose_engine()

    if all_buys.empty:
        logger.warning("No qualifying open-market buys in window — nothing to study.")
        return

    rng = np.random.default_rng(seed)
    event_rows: list[dict] = []
    control_rows: list[dict] = []
    data_end = spy.index.max()  # latest available session — used to tell delisting from "recent"

    # Resilience fix: fetch all ticker histories via the parallel batch API up
    # front (workers, per-ticker failures dropped) instead of a synchronous
    # per-ticker loop that previously died mid-run on a single hung fetch.
    tickers_with_buys = sorted(all_buys["ticker"].unique().tolist())
    logger.info("Batch-fetching 10y prices for %d tickers...", len(tickers_with_buys))
    price_map = fetcher.fetch_batch(tickers_with_buys, period="10y", interval="1d", adjusted=True)
    logger.info("Got prices for %d/%d tickers", len(price_map), len(tickers_with_buys))

    groups = list(all_buys.groupby("ticker"))
    for i, (ticker, grp) in enumerate(groups):
        if i % 50 == 0:
            logger.info("Processing %d/%d tickers (events=%d, controls=%d)",
                        i, len(groups), len(event_rows), len(control_rows))
        praw = price_map.get(ticker)
        if praw is None or praw.empty:
            continue
        try:
            prices = praw.copy()
            prices.index = pd.to_datetime(prices.index).tz_localize(None).normalize()
            prices = prices[~prices.index.duplicated(keep="last")].sort_index()
            # pre-event history adequacy is enforced by the resid_63/drawdown_126/
            # beta filters (they need >=64/126/273 bars <= t), so no total-history
            # gate is needed — a short total series is exactly a delisted name we
            # must KEEP, not drop (survivorship fix).
            if len(prices) < 2:
                continue

            events = detect_events(grp, prices, spy)
            events = [e for e in events if start_ts <= e["t"] <= end_ts]
            if not events:
                continue

            buy_filings = sorted(grp["filing_ts"].unique())
            for e in events:
                row = dict(e)
                for label, n in HOLD_DAYS.items():
                    a, entry_ts = compute_alpha(prices, spy, e["t"], n, data_end)
                    row[f"alpha{n}"] = a
                    if label == PRIMARY_HOLD:
                        row["entry_ts"] = entry_ts
                row["is_event"] = True
                event_rows.append(row)

            # matched controls for this ticker
            t_min = max(prices.index.min() + pd.Timedelta(days=400), start_ts)
            t_max = min(prices.index.max() - pd.Timedelta(days=80), end_ts)
            if t_max <= t_min:
                continue
            ctrl_dates = detect_control_dates(prices, spy, buy_filings, t_min, t_max)
            if ctrl_dates:
                if len(ctrl_dates) > MAX_CONTROLS_PER_EVENT * len(events):
                    pick = rng.choice(len(ctrl_dates),
                                      size=MAX_CONTROLS_PER_EVENT * len(events), replace=False)
                    ctrl_dates = [ctrl_dates[i] for i in sorted(pick)]
                for ct in ctrl_dates:
                    crow = {"ticker": ticker, "t": ct, "is_event": False}
                    for label, n in HOLD_DAYS.items():
                        a, entry_ts = compute_alpha(prices, spy, ct, n, data_end)
                        crow[f"alpha{n}"] = a
                        if label == PRIMARY_HOLD:
                            crow["entry_ts"] = entry_ts
                    control_rows.append(crow)
        except Exception as exc:  # belt-and-suspenders: one bad ticker can't kill the run
            logger.warning("ticker %s failed: %s", ticker, exc)
            continue

    ev = pd.DataFrame(event_rows)
    ct = pd.DataFrame(control_rows)
    if ev.empty:
        logger.warning("No events fired the full trigger in window.")
        _print_verdict(ev, ct, ship=False, reason="no events")
        return

    # cross-sectional signal score S over events (reported diagnostic)
    if len(ev) >= 2:
        B = np.log1p(ev["buy_value_10d"] / ev["adv20_usd"])
        C = np.log1p(ev["unique_buyers_10d"].astype(float))
        D = ev["resid_63"].abs()
        ev["signal_S"] = _z(B) + 0.5 * _z(C) + 0.5 * _z(D)
    else:
        ev["signal_S"] = np.nan

    _print_results(ev, ct, rng)


def _z(x: pd.Series) -> pd.Series:
    sd = x.std(ddof=0)
    return (x - x.mean()) / sd if sd and np.isfinite(sd) and sd > 0 else x * 0.0


def _print_results(ev: pd.DataFrame, ct: pd.DataFrame, rng: np.random.Generator):
    primary_n = HOLD_DAYS[PRIMARY_HOLD]
    a20 = ev[f"alpha{primary_n}"].dropna()

    print("\n" + "=" * 70)
    print("PANEL #1 — DISTRESSED-INSIDER CLUSTER BUY: EVENT STUDY RESULTS")
    print("=" * 70)
    print(f"Events fired: {len(ev)}  |  with usable alpha{primary_n}: {len(a20)}")
    print(f"Controls: {len(ct)}  |  unique tickers (events): {ev['ticker'].nunique()}")
    print(f"Concurrency cap (reported, not enforced in per-event math): {MAX_CONCURRENT}")

    if a20.empty:
        _print_verdict(ev, ct, ship=False, reason="no usable forward returns")
        return

    med20 = float(a20.median())
    pct_pos20 = float((a20 > 0).mean() * 100.0)
    print("\n-- Forward beta-adjusted alpha (open-to-open, cost -0.3%) --")
    for label, n in HOLD_DAYS.items():
        col = ev[f"alpha{n}"].dropna()
        if col.empty:
            print(f"  alpha{n:<4} n=0")
            continue
        print(f"  alpha{n:<4} n={len(col):<4} median={col.median()*100:+6.2f}%  "
              f"mean={col.mean()*100:+6.2f}%  %pos={float((col>0).mean()*100):5.1f}%")

    # signs across {10,20,40}
    signs = []
    for n in (10, 20, 40):
        col = ev[f"alpha{n}"].dropna()
        signs.append(col.median() > 0 if not col.empty else False)
    pos_horizons = sum(signs)
    print(f"\n  Positive median sign in {pos_horizons} of 3 horizons {dict(zip(('10d','20d','40d'),signs))}")

    # matched-control null
    mc_delta = mc_p = float("nan")
    if not ct.empty:
        cc = ct[f"alpha{primary_n}"].dropna()
        if not cc.empty:
            mc_delta = med20 - float(cc.median())
            # Mann-Whitney-ish via simple permutation of pooled labels (ticker-agnostic)
            pooled = np.concatenate([a20.to_numpy(), cc.to_numpy()])
            labels = np.array([1] * len(a20) + [0] * len(cc))
            obs = np.median(pooled[labels == 1]) - np.median(pooled[labels == 0])
            ge = 0
            for _ in range(2000):
                rng.shuffle(labels)
                s = np.median(pooled[labels == 1]) - np.median(pooled[labels == 0])
                if s >= obs:
                    ge += 1
            mc_p = (ge + 1) / 2001
            print("\n-- MATCHED-CONTROL NULL (insider signal vs capitulation reversal) --")
            print(f"  control median alpha{primary_n} = {cc.median()*100:+.2f}%  (n={len(cc)})")
            print(f"  event - control = {mc_delta*100:+.2f}pp   label-perm p = {mc_p:.4f}")
    else:
        print("\n-- MATCHED-CONTROL NULL -- no controls found.")

    # permutation null (within-year cluster-label permute over events+controls)
    perm_p = float("nan")
    if not ct.empty:
        pool = pd.concat([
            ev[["entry_ts", f"alpha{primary_n}"]].assign(is_event=True),
            ct[["entry_ts", f"alpha{primary_n}"]].assign(is_event=False),
        ], ignore_index=True).rename(columns={f"alpha{primary_n}": "alpha20"})
        pool = pool.dropna(subset=["alpha20", "entry_ts"]).reset_index(drop=True)
        perm_p = permutation_pvalue(pool, PERMUTATION_N, rng)
        print("\n-- PERMUTATION NULL (within-year cluster-label permute, n=%d) --" % PERMUTATION_N)
        print(f"  p = {perm_p:.4f}")

    # leave-COVID-out
    covid_mask = (ev["entry_ts"] >= COVID_START) & (ev["entry_ts"] <= COVID_END)
    lco = ev.loc[~covid_mask, f"alpha{primary_n}"].dropna()
    lco_med = float(lco.median()) if not lco.empty else float("nan")
    print(f"\n-- LEAVE-COVID-OUT (drop entry {COVID_START.date()}..{COVID_END.date()}) --")
    print(f"  dropped {int(covid_mask.sum())} COVID events; remaining median alpha{primary_n} = {lco_med*100:+.2f}% (n={len(lco)})")

    # ---- ship rule ----
    cond = {
        "median_alpha20 > +3%": med20 > 0.03,
        "%-positive >= 55%": pct_pos20 >= 55.0,
        "permutation p < 0.05": np.isfinite(perm_p) and perm_p < 0.05,
        "positive sign >=2 of {10,20,40}d": pos_horizons >= 2,
        "leave-COVID-out median > 0": np.isfinite(lco_med) and lco_med > 0,
    }
    ship = all(cond.values())
    print("\n" + "=" * 70)
    print("SHIP RULE")
    print("=" * 70)
    print(f"  median alpha{primary_n} = {med20*100:+.2f}%   %pos = {pct_pos20:.1f}%")
    for k, v in cond.items():
        print(f"  [{'PASS' if v else 'FAIL'}] {k}")
    print("-" * 70)
    print(f"  VERDICT: {'SHIP' if ship else 'DO NOT SHIP'}")
    print("=" * 70 + "\n")


def _print_verdict(ev, ct, ship: bool, reason: str):
    print("\n" + "=" * 70)
    print("SHIP RULE")
    print("=" * 70)
    print(f"  VERDICT: {'SHIP' if ship else 'DO NOT SHIP'}  ({reason})")
    print("=" * 70 + "\n")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Panel #1 distressed-insider cluster-buy event study.")
    p.add_argument("--limit", type=int, default=None, help="Limit to first N candidate tickers (smoke test).")
    p.add_argument("--start", type=str, default="2018-01-01", help="Earliest entry date (YYYY-MM-DD).")
    p.add_argument("--end", type=str, default="2026-05-01", help="Latest entry date (YYYY-MM-DD).")
    p.add_argument("--seed", type=int, default=12345, help="RNG seed for control sampling + permutations.")
    return p.parse_args(argv)


def main():
    args = parse_args()
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    asyncio.run(run_study(args.limit, start, end, args.seed))


if __name__ == "__main__":
    main()
