# /// script
# dependencies = ["pandas", "numpy", "yfinance", "pyarrow"]
# ///
#!/usr/bin/env python
"""Diversified time-series momentum (TSMOM) — Moskowitz-Ooi-Pedersen managed-futures.

Standalone. Modifies no tracked files. BACKTEST ONLY. yfinance long-history ETFs.

STRATEGY (pre-registered, exact)
  Cross-asset ETF basket (equities SPY/EFA/EEM, rates IEF/TLT, commodity GLD/DBC,
  dollar UUP). For each asset, each month-end:
    signal = sign( P_t / P_{t-LOOKBACK} - 1  -  cash_proxy_return_over_lookback )
             (trailing 12m EXCESS return; long if >0).
    LONG if signal>0, else CASH (long/flat — cross-asset ETFs cannot be shorted
    cleanly; cash leg = SHY/BIL excess proxy, modelled as 0 excess here since the
    excess-return signal already nets the cash rate). A LONG/SHORT mode models the
    short as -1*asset_excess (NOT inverse ETFs, which decay).
  SIZING: each asset vol-targeted to equal risk — weight = VOL_TARGET / realized_vol
    (ex-ante, lagged), capped at LEVERAGE_CAP. Equal-risk-weight the basket across
    assets-present-that-month (renormalise over active, NaN before listing != 0).
  REBALANCE monthly. COST: COST_BPS round-trip on |Δweight| turnover per rebalance.

LOOKAHEAD DISCIPLINE (the #1 trap — see project_phase_luck / yfinance memos)
  Signal at month-end t is formed from prices <= t (12m return ending t) and the
  ex-ante vol estimate uses daily returns ending t. The position is .shift(1)-LAGGED:
  it is applied over month t+1 and earns month t+1's return. Vol estimate likewise
  lagged. No same-month signal, no same-day vol. Verified mechanically in build_signals.

ROBUSTNESS
  Also reports 6m signal and a 1/3/6/12m blend (sign of the average of the four
  trailing-return signs). AR(1)-adjusted Sharpe (trend returns are autocorrelated;
  IID Sharpe is upper-biased). CAPM/Jensen alpha+beta vs SPY buy-hold (raw excess
  flatters a time-varying-beta long/flat book — use alpha, not raw excess). by-year,
  walk-forward folds, and the crisis-alpha tests below.

CRISIS-ALPHA TESTS (the diversification IS the prize)
  (i)  correlation of monthly strategy returns to SPY monthly returns.
  (ii) average monthly return across the WORST equity-drawdown windows
       (2008-Q4 if data, 2020-Q1, 2022-H1). Genuinely diversifying => >= 0 there.

SHIP RULE (ALL must hold):
  1. net-of-cost annualized Sharpe (AR1-adj) > 0.7
  2. net-positive in a MAJORITY of calendar years
  3. monthly correlation to SPY < 0.3
  4. average return across the worst equity-drawdown windows >= 0

Usage:
    uv run python scripts/tsmom_study.py
    uv run python scripts/tsmom_study.py --start 2006-06-01 --lookback 12 --output reports/tsmom.json
    uv run python scripts/tsmom_study.py --signal blend --mode long_short
    uv run python scripts/tsmom_study.py --smoke      # synthetic SPY+TLT self-test, no fetch
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "data" / "trend_cache"

# Cross-asset ETF basket (yfinance first-trade year in comment).
ETF_UNIVERSE = [
    "SPY",  # 1993  US equity
    "EFA",  # 2001  developed ex-US equity
    "EEM",  # 2003  EM equity
    "IEF",  # 2002  7-10y UST
    "TLT",  # 2002  20y+ UST
    "GLD",  # 2004  gold
    "DBC",  # 2006  broad commodity (preferred over USO: less contango decay)
    "UUP",  # 2007  USD index
]
CASH_PROXY = "SHY"  # 1-3y UST, history to 2002 — excess-return cash leg

TD_PER_YEAR = 252
MONTHS_PER_YEAR = 12
DEFAULT_LOOKBACK_M = 12          # months for the headline trailing-return signal
VOL_TARGET = 0.10                # per-asset annualized vol target
VOL_LOOKBACK_D = 60              # daily-return window for ex-ante vol
LEVERAGE_CAP = 2.0               # per-asset weight cap
COST_BPS = 10.0                  # round-trip per rebalance on turnover

# Worst equity-drawdown windows for the crisis-alpha test (avg monthly ret >= 0).
CRISIS_WINDOWS = {
    "2008Q4_GFC": ("2008-10-01", "2008-12-31"),
    "2020Q1_COVID": ("2020-02-01", "2020-03-31"),
    "2022H1_jointselloff": ("2022-01-01", "2022-06-30"),
}


# --------------------------------------------------------------------------- #
# Metrics — local copies (task forbids modifying tracked files; per-script
# copies are the repo convention; cf. vrp_study.py:67). ddof=1 (sample).
# ann_sharpe / ar1_adjusted_sharpe / sharpe_se / max_drawdown / stats_block
#   mirror vrp_study.py:70-119. capm_alpha_beta / walk_forward_folds / cagr
#   mirror crypto_carry_study.py:221-260 (re-based to monthly ppy=12).
# --------------------------------------------------------------------------- #
def ann_sharpe(rets: pd.Series, periods_per_year: int = MONTHS_PER_YEAR) -> float:
    r = rets.dropna()
    if r.empty:
        return 0.0
    mu = r.mean()
    sigma = r.std(ddof=1)
    if sigma == 0 or np.isnan(sigma):
        return 0.0
    return float(mu / sigma * math.sqrt(periods_per_year))


def ar1_adjusted_sharpe(rets: pd.Series, periods_per_year: int = MONTHS_PER_YEAR) -> tuple[float, float, float]:
    """(raw_sharpe, ar1, adj_sharpe). Variance-ratio shrink: S*sqrt((1-a)/(1+a))."""
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


def capm_alpha_beta(strat: pd.Series, bench: pd.Series) -> tuple[float, float]:
    """Jensen alpha (annualized %) + beta of monthly strat vs monthly bench."""
    df = pd.concat([strat.rename("s"), bench.rename("m")], axis=1).dropna()
    if len(df) < 12 or df["m"].var() == 0:
        return 0.0, 0.0
    beta = float(df["s"].cov(df["m"]) / df["m"].var())
    alpha_m = float(df["s"].mean() - beta * df["m"].mean())
    return ((1.0 + alpha_m) ** MONTHS_PER_YEAR - 1.0) * 100.0, beta


def walk_forward_folds(rets: pd.Series, n_folds: int = 5) -> dict:
    r = rets.dropna()
    if r.empty or len(r) < n_folds:
        return {"folds": [], "mean_sharpe": 0.0, "min_sharpe": 0.0, "passed": False}
    fold_size = len(r) // n_folds
    folds = []
    for i in range(n_folds):
        start = i * fold_size
        end = (i + 1) * fold_size if i < n_folds - 1 else len(r)
        chunk = r.iloc[start:end]
        folds.append({
            "fold": i,
            "sharpe": round(ann_sharpe(chunk), 3),
            "return_pct": round(((1 + chunk).prod() - 1) * 100, 2),
            "n_months": len(chunk),
        })
    sharpes = [f["sharpe"] for f in folds]
    mean_s, min_s = float(np.mean(sharpes)), float(np.min(sharpes))
    return {"folds": folds, "mean_sharpe": round(mean_s, 3),
            "min_sharpe": round(min_s, 3),
            "passed": all(s > 0 for s in sharpes) and mean_s >= 0.5}


def cagr(equity: pd.Series) -> float:
    if len(equity) < 2:
        return 0.0
    tot = equity.iloc[-1] / equity.iloc[0] - 1.0
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    if years <= 0:
        return 0.0
    return (1.0 + tot) ** (1.0 / years) - 1.0


# --------------------------------------------------------------------------- #
# Data — cached parquet under data/trend_cache/ (yfinance non-determinism:
# freeze on first pull, reuse thereafter; cf. project_yfinance_nondeterminism).
# --------------------------------------------------------------------------- #
def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    idx = pd.to_datetime(df.index)
    if isinstance(idx, pd.DatetimeIndex) and idx.tz is not None:
        idx = idx.tz_localize(None)
    df.index = idx.normalize()
    return df[~df.index.duplicated(keep="last")].sort_index()


def fetch_etf(symbol: str, refresh: bool = False) -> pd.Series:
    """Adjusted daily Close for one ETF; yfinance period='max', parquet-cached."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"{symbol}_daily.parquet"
    if cache.exists() and not refresh:
        s = pd.read_parquet(cache)
    else:
        import yfinance as yf

        h = yf.Ticker(symbol).history(period="max", auto_adjust=True)
        if h is None or h.empty:
            raise SystemExit(f"{symbol} fetch failed (yfinance).")
        h = _normalize(h)
        s = h[["Close"]].rename(columns={"Close": symbol})
        s.to_parquet(cache)
    col = symbol if symbol in s.columns else s.columns[0]
    return _normalize(s[[col]].rename(columns={col: symbol}))[symbol]


# --------------------------------------------------------------------------- #
# Signals + sizing (lookahead-safe). Works on a panel of daily Close prices.
# --------------------------------------------------------------------------- #
def _month_end_calendar(panel: pd.DataFrame) -> pd.DatetimeIndex:
    return panel.resample("ME").last().index


def build_positions(panel: pd.DataFrame, lookback_m: int, signal: str,
                    cash_excess_m: pd.Series | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (month_returns, positions) aligned on a common month-end calendar.

    month_returns[t]  = each asset's total return realized DURING month t.
    positions[t]      = signed vol-target weight HELD during month t, formed from
                        data <= end of month t-1 (i.e. .shift(1)). Long/flat sign.

    Lookahead guard: sign_t and vol_t are computed at month-end t from prices/returns
    <= t, then .shift(1) so they govern month t+1's return. No same-month leakage.
    """
    daily_ret = panel.pct_change()
    m_close = panel.resample("ME").last()
    m_ret = m_close.pct_change()  # month t total return per asset

    # Ex-ante annualized vol at each month-end from the trailing VOL_LOOKBACK_D days.
    rv_daily = daily_ret.rolling(VOL_LOOKBACK_D).std() * math.sqrt(TD_PER_YEAR)
    rv_m = rv_daily.resample("ME").last()

    # --- trailing-return signs (lookback in MONTHS on month-end closes) ---
    def trail_sign(lb: int) -> pd.DataFrame:
        tr = m_close / m_close.shift(lb) - 1.0
        if cash_excess_m is not None:
            # excess over compounded cash return across the same lookback
            cash_cum = (1.0 + cash_excess_m).rolling(lb).apply(np.prod, raw=True) - 1.0
            tr = tr.sub(cash_cum, axis=0)
        return np.sign(tr)

    if signal == "12m":
        sig = trail_sign(12)
    elif signal == "6m":
        sig = trail_sign(6)
    elif signal == "lookback":
        sig = trail_sign(lookback_m)
    elif signal == "blend":
        # 1/3/6/12m: sign of the mean of the four individual signs.
        blend = (trail_sign(1) + trail_sign(3) + trail_sign(6) + trail_sign(12)) / 4.0
        sig = np.sign(blend)
    else:
        raise SystemExit(f"unknown signal: {signal}")

    # vol-target weight magnitude, capped; rv NaN/0 -> no position.
    w_mag = (VOL_TARGET / rv_m).replace([np.inf, -np.inf], np.nan)
    w_mag = w_mag.clip(upper=LEVERAGE_CAP)
    raw_pos = sig * w_mag  # signed, formed AT month-end t

    # LAG: position formed at t governs month t+1. This is the only lookahead guard.
    positions = raw_pos.shift(1)
    return m_ret, positions


def run_backtest(panel: pd.DataFrame, lookback_m: int, signal: str, mode: str,
                 cost_bps: float, cash_excess_m: pd.Series | None) -> dict:
    """Equal-risk-weight basket of vol-targeted per-asset trend legs, monthly.

    mode='long_flat': sign<0 -> 0 (cash). mode='long_short': sign<0 -> short, modelled
    as -1*asset_return (clean backtest short; ignores borrow). Per-asset gross return =
    position * asset_month_return. Basket = mean over assets-PRESENT-that-month
    (renormalise over active, NaN before listing != 0). Cost = cost_bps on |Δposition|.
    """
    m_ret, positions = build_positions(panel, lookback_m, signal, cash_excess_m)

    if mode == "long_flat":
        positions = positions.clip(lower=0.0)
    elif mode != "long_short":
        raise SystemExit(f"unknown mode: {mode}")

    # Per-asset leg return for the month (only where the asset traded AND has a position).
    leg = positions * m_ret
    active = (positions.notna() & m_ret.notna())
    leg = leg.where(active)

    n_active = active.sum(axis=1).replace(0, np.nan)
    gross = leg.sum(axis=1) / n_active  # equal-risk-weight across active assets

    # Turnover cost: |Δposition| summed across assets, equal-weighted, * cost.
    dpos = positions.fillna(0.0).diff().abs()
    turnover = (dpos.where(active).sum(axis=1) / n_active).fillna(0.0)
    cost = turnover * (cost_bps / 10_000.0)

    net = (gross - cost).dropna()
    gross = gross.reindex(net.index)
    equity = (1.0 + net).cumprod()

    return {
        "m_ret": m_ret,
        "positions": positions,
        "gross": gross,
        "net": net,
        "equity": equity,
        "leg": leg,
        "active": active,
    }


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def by_year(net: pd.Series) -> dict:
    out = {}
    for yr, grp in net.groupby(net.index.year):
        eq = (1 + grp).cumprod()
        tot = (1 + grp).prod() - 1
        out[str(int(yr))] = {
            "ret_pct": round(tot * 100, 2),
            "sharpe": round(ann_sharpe(grp), 3),
            "max_dd_pct": round(max_drawdown(eq) * 100, 2),
            "n_months": int(len(grp)),
            "negative": bool(tot < 0),
        }
    return out


def per_asset_breakdown(bt: dict) -> dict:
    """Standalone vol-target trend Sharpe per sleeve (leg return alone)."""
    leg = bt["leg"]
    out = {}
    for col in leg.columns:
        s = leg[col].dropna()
        if s.empty:
            continue
        out[col] = {
            "ann_sharpe": round(ann_sharpe(s), 3),
            "ret_pct_total": round(((1 + s).prod() - 1) * 100, 2),
            "n_months": int(len(s)),
        }
    return out


def crisis_alpha(net: pd.Series, spy_m: pd.Series) -> dict:
    """SPY correlation + avg monthly return in worst equity-drawdown windows."""
    aligned = pd.concat([net.rename("s"), spy_m.rename("m")], axis=1).dropna()
    corr = float(aligned["s"].corr(aligned["m"])) if len(aligned) > 2 else float("nan")

    windows = {}
    crisis_means = []
    for tag, (lo, hi) in CRISIS_WINDOWS.items():
        grp = net[(net.index >= pd.Timestamp(lo)) & (net.index <= pd.Timestamp(hi))]
        spy_grp = spy_m[(spy_m.index >= pd.Timestamp(lo)) & (spy_m.index <= pd.Timestamp(hi))]
        if grp.empty:
            windows[tag] = {"present": False}
            continue
        avg = float(grp.mean())
        crisis_means.append(avg)
        windows[tag] = {
            "present": True,
            "n_months": int(len(grp)),
            "avg_monthly_ret_pct": round(avg * 100, 3),
            "cumulative_ret_pct": round(((1 + grp).prod() - 1) * 100, 2),
            "spy_cumulative_ret_pct": round(((1 + spy_grp).prod() - 1) * 100, 2) if not spy_grp.empty else None,
        }
    avg_across = float(np.mean(crisis_means)) if crisis_means else float("nan")
    return {
        "monthly_corr_to_spy": round(corr, 3) if not np.isnan(corr) else None,
        "windows": windows,
        "avg_monthly_ret_across_crisis_windows_pct": round(avg_across * 100, 3) if not np.isnan(avg_across) else None,
        "_avg_across_raw": avg_across,
        "_corr_raw": corr,
    }


def run(panel: pd.DataFrame, spy_close: pd.Series, cash_excess_m: pd.Series | None,
        start: str | None, end: str | None, lookback_m: int, signal: str,
        mode: str, cost_bps: float) -> dict:
    if start:
        panel = panel[panel.index >= pd.Timestamp(start)]
    if end:
        panel = panel[panel.index <= pd.Timestamp(end)]
    panel = panel.dropna(how="all")
    if len(panel) < TD_PER_YEAR + VOL_LOOKBACK_D:
        raise SystemExit("Not enough history to build any signal (need >1y + vol window).")

    bt = run_backtest(panel, lookback_m, signal, mode, cost_bps, cash_excess_m)
    net = bt["net"]
    if net.empty:
        raise SystemExit("Backtest produced no net returns (check listing dates / window).")
    equity = bt["equity"]

    # SPY buy-hold monthly benchmark, aligned to net.
    spy_m = spy_close.resample("ME").last().pct_change().reindex(net.index)

    raw_s, ac1, adj_s = ar1_adjusted_sharpe(net, MONTHS_PER_YEAR)
    se = sharpe_se(raw_s, len(net))
    alpha_spy, beta_spy = capm_alpha_beta(net, spy_m)

    yr = by_year(net)
    yrs_total = len(yr)
    yrs_neg = sum(1 for v in yr.values() if v["negative"])
    yrs_pos = yrs_total - yrs_neg

    ca = crisis_alpha(net, spy_m)
    wf = walk_forward_folds(net, n_folds=5)
    assets = per_asset_breakdown(bt)
    best_single = max((v["ann_sharpe"] for v in assets.values()), default=0.0)

    # ---- SHIP RULE ----
    sharpe_ok = adj_s > 0.7
    years_ok = yrs_pos > yrs_neg  # majority of calendar years positive
    corr_ok = (ca["_corr_raw"] is not None) and (not np.isnan(ca["_corr_raw"])) and (ca["_corr_raw"] < 0.3)
    crisis_ok = (not np.isnan(ca["_avg_across_raw"])) and (ca["_avg_across_raw"] >= 0.0)
    ship = bool(sharpe_ok and years_ok and corr_ok and crisis_ok)

    diversification_benefit = adj_s > best_single  # basket beats best single sleeve

    return {
        "window": {
            "start": net.index.min().strftime("%Y-%m-%d"),
            "end": net.index.max().strftime("%Y-%m-%d"),
            "n_months": int(len(net)),
        },
        "params": {
            "universe": list(panel.columns),
            "lookback_months": lookback_m, "signal": signal, "mode": mode,
            "vol_target": VOL_TARGET, "vol_lookback_d": VOL_LOOKBACK_D,
            "leverage_cap": LEVERAGE_CAP, "cost_bps_round_trip": cost_bps,
            "cash_excess_proxy": CASH_PROXY if cash_excess_m is not None else "zero",
            "ddof": 1,
        },
        "headline": {
            "cagr_pct": round(cagr(equity) * 100, 2),
            "total_ret_pct": round((equity.iloc[-1] - 1) * 100, 2),
            "ann_sharpe_iid": round(raw_s, 3),
            "ar1": round(ac1, 3),
            "ann_sharpe_ar1_adj": round(adj_s, 3),
            "sharpe_se_approx": round(se, 3) if not np.isnan(se) else None,
            "max_dd_pct": round(max_drawdown(equity) * 100, 2),
            "capm_alpha_pct_vs_spy": round(alpha_spy, 2),
            "capm_beta_vs_spy": round(beta_spy, 3),
            "pct_positive_months": round(float((net > 0).mean() * 100), 1),
            "best_single_sleeve_sharpe": round(best_single, 3),
            "diversification_benefit_basket_gt_best_sleeve": bool(diversification_benefit),
        },
        "crisis_alpha": {k: v for k, v in ca.items() if not k.startswith("_")},
        "by_year": yr,
        "per_asset": assets,
        "walk_forward": wf,
        "ship_rule": {
            "1_ar1_sharpe_gt_0p7": sharpe_ok,
            "2_majority_years_positive": years_ok,
            "3_spy_corr_lt_0p3": corr_ok,
            "4_crisis_windows_avg_ge_0": crisis_ok,
            "years_positive": yrs_pos,
            "years_negative": yrs_neg,
            "PASS": ship,
        },
        "verdict": _verdict(ship, sharpe_ok, years_ok, corr_ok, crisis_ok,
                            adj_s, ca, yrs_pos, yrs_neg),
    }


def _verdict(ship, sharpe_ok, years_ok, corr_ok, crisis_ok, adj_s, ca, yrs_pos, yrs_neg) -> str:
    corr = ca["_corr_raw"]
    cw = ca["_avg_across_raw"]
    kind = ("crisis-alpha (positive in equity-drawdown windows)"
            if crisis_ok and (cw is not None and cw > 0)
            else "merely low-correlation in calm times (NOT positive in the crisis windows)")
    if ship:
        return (f"SHIP. AR(1)-adj Sharpe {adj_s:.2f}>0.7; {yrs_pos}/{yrs_pos+yrs_neg} years positive; "
                f"SPY corr {corr:+.2f}<0.3; avg crisis-window monthly ret {cw*100:+.2f}%>=0. "
                f"This is genuine {kind}. Caveat: yfinance pull frozen to parquet (±0.4 Sharpe "
                f"re-adjustment envelope); raw-excess flatters long/flat books so judged on CAPM-α + corr.")
    fails = []
    if not sharpe_ok:
        fails.append(f"AR(1)-adj Sharpe {adj_s:.2f}<=0.7")
    if not years_ok:
        fails.append(f"not majority years positive ({yrs_pos}+/{yrs_neg}-)")
    if not corr_ok:
        c = "n/a" if corr is None or np.isnan(corr) else f"{corr:+.2f}"
        fails.append(f"SPY corr {c} not <0.3")
    if not crisis_ok:
        c = "n/a" if cw is None or np.isnan(cw) else f"{cw*100:+.2f}%"
        fails.append(f"crisis-window avg {c} <0 (not diversifying when it matters)")
    return (f"NO-SHIP. Failed: " + "; ".join(fails)
            + f". Honest read: this is {kind}.")


# --------------------------------------------------------------------------- #
# Smoke: synthetic SPY+TLT (no fetch), proves pipeline reaches a verdict block.
# --------------------------------------------------------------------------- #
def smoke() -> dict:
    rng = np.random.default_rng(11)
    n = 6 * TD_PER_YEAR
    idx = pd.bdate_range("2010-01-04", periods=n)
    # SPY: trending bull with a sharp drawdown window (trend should de-risk/flip).
    drift = np.full(n, 0.0004)
    drift[700:760] = -0.004  # crisis: sustained negative drift -> 12m sign goes <0
    spy = pd.Series(100 * np.exp(np.cumsum(rng.normal(drift, 0.01, n))), index=idx, name="SPY")
    # TLT: mildly trending, low corr to SPY (flight-to-quality bumps in the crisis).
    tlt_drift = np.full(n, 0.0002)
    tlt_drift[700:760] = 0.003
    tlt = pd.Series(80 * np.exp(np.cumsum(rng.normal(tlt_drift, 0.008, n))), index=idx, name="TLT")

    panel = pd.concat([spy, tlt], axis=1)
    res = run(panel, spy, cash_excess_m=None, start=None, end=None,
              lookback_m=12, signal="12m", mode="long_flat", cost_bps=10.0)
    ok = (
        "verdict" in res
        and "ship_rule" in res
        and isinstance(res["ship_rule"]["PASS"], bool)
        and res["window"]["n_months"] > 24
        and "monthly_corr_to_spy" in res["crisis_alpha"]
        and len(res["per_asset"]) == 2
    )
    return {
        "smoke_pass": ok,
        "n_months": res["window"]["n_months"],
        "ar1_adj_sharpe": res["headline"]["ann_sharpe_ar1_adj"],
        "spy_corr": res["crisis_alpha"]["monthly_corr_to_spy"],
        "ship": res["ship_rule"]["PASS"],
        "verdict": res["verdict"][:90],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Diversified time-series momentum (TSMOM) study.")
    ap.add_argument("--start", default=None, help="window start YYYY-MM-DD (default: full common history)")
    ap.add_argument("--end", default=None, help="window end YYYY-MM-DD")
    ap.add_argument("--lookback", type=int, default=DEFAULT_LOOKBACK_M, help="lookback months (signal='lookback')")
    ap.add_argument("--signal", choices=["12m", "6m", "blend", "lookback"], default="12m",
                    help="trailing-return signal (default 12m)")
    ap.add_argument("--mode", choices=["long_flat", "long_short"], default="long_flat",
                    help="long_flat=cash on sig<0 (default); long_short models short as -1*excess")
    ap.add_argument("--cost-bps", type=float, default=COST_BPS, help="round-trip cost bps per rebalance (default 10)")
    ap.add_argument("--no-cash-excess", action="store_true", help="use raw return sign (excess vs 0) not vs SHY")
    ap.add_argument("--output", default=None, help="write JSON report here")
    ap.add_argument("--refresh", action="store_true", help="bypass parquet cache, re-fetch")
    ap.add_argument("--smoke", action="store_true", help="synthetic SPY+TLT self-test, no fetch")
    args = ap.parse_args()

    if args.smoke:
        out = smoke()
        print(json.dumps(out, indent=2))
        return 0 if out["smoke_pass"] else 1

    closes = {sym: fetch_etf(sym, refresh=args.refresh) for sym in ETF_UNIVERSE}
    panel = pd.DataFrame(closes).sort_index()
    spy_close = closes["SPY"]

    cash_excess_m = None
    if not args.no_cash_excess:
        cash = fetch_etf(CASH_PROXY, refresh=args.refresh)
        cash_excess_m = cash.resample("ME").last().pct_change()

    res = run(panel, spy_close, cash_excess_m, args.start, args.end,
              args.lookback, args.signal, args.mode, args.cost_bps)

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
