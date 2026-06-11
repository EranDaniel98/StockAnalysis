"""SPX Deletion-Reversal event study (PRE-REGISTERED).

Tests one hypothesis: do S&P 500 DELETIONS (demoted-but-solvent names) earn
positive beta-adjusted forward returns once the forced indexer selling clears?
Mechanism: index deletion forces ~$13-15T of benchmarked capital to sell with
ZERO fundamental information content; demoted names are momentum losers and
institutionally shunned, so the dislocation corrects slowly. The decision rule
below is pre-registered (workflow run wf_ae576aed-ab6, merged rank-1 + rank-2
sibling specs) — this script BUILDS it exactly, it does not tune it.

EVENT: ticker removed from the S&P 500 (action == remove in the membership
changes log), effective date t_eff, 2018-01-02 onward, where:
  - reason does NOT match the M&A regex (acquisition/merger/take-private have
    no tradeable forward path), AND
  - the ticker still prints a bar at the entry date (structural demotion
    filter — acquired names stop trading; PIT-safe: observable at entry).

GRADED ARM (primary): entry at close of t_eff + 5 trading days, hold 126
trading days, SOLVENCY FLOOR: EDGAR-PIT TTM-EPS > 0 OR free_cash_flow > 0
as of entry (amputates the true-corporate-death left tail that produced the
distressed-insider fat tail). Delisting-aware: if the name stops trading
mid-hold, realize the last available close.

REPORTED (not graded): no-conditioning arm (no solvency floor), 21d and 63d
holds, 25bps cost arm, T+1/T+3 entry arms.

PRIMARY METRIC per event: alpha_126 = R_i[entry, exit] - beta_i * R_SPY[entry,
exit] - cost, beta from 252d trailing OLS vs SPY using ONLY data <= entry
(min 120 obs), cost = 50bps round-trip charged in full.

MATCHED CONTROLS per event: up to 3 same-sector, never-deleted (2018-2026)
S&P members nearest in (12-1 momentum, 63d dollar volume) z-distance at entry,
identical alpha computation over the same dates. The controls strip the
generic beaten-down-loser/value effect: the claim is the deletion CATALYST.

PERMUTATION NULL: within each calendar year, swap the "event" label with a
random one of its controls (n=1000) -> null distribution of the median
event-minus-control increment.

SHIP RULE (ALL must hold; any failure = NO-SHIP, log the null, stop):
  (1) N >= 50 qualifying events in the graded arm, else ABORT-underpowered
      (neither pass nor fail — do not grade an underpowered sample).
  (2) median alpha_126 >= +4% AND mean alpha_126 > 0 (delisted included).
  (3) matched-control increment >= +3pp median AND permutation p < 0.05.
  (4) win rate vs own matched-control median >= 55%.
  (5) calendar-year breadth: positive median event alpha in >= 6 of the 8
      years 2018-2025 with >= 3 events (date-pinned events: calendar-year
      breadth replaces the rebalance-phase envelope).
  (6) clauses 2-5 hold at the 50bps cost arm (25bps reported only).
  (7) orthogonality: median 12-1 momentum percentile of entered names vs the
      contemporaneous S&P cross-section < 30th pct (we buy what the momentum
      book shuns — not a clone).
  (8) entry-jitter sign stability: median alpha_126 > 0 at T+1, T+3 AND T+5
      (anti-phase-luck for an event book).
  Price-artifact guard: any event ticker tripping has_price_artifact over its
  event window is DROPPED and listed (META-stitch lesson); drops reported.

LOOKAHEAD DISCIPLINE: events come from the published changes log (historical
facts, effective dates precede entry by 5 sessions and announcements precede
effective by ~5 more); solvency floor reads fundamentals_pit.json with
valid_from <= entry; beta and matching features use only bars <= entry;
forward returns are strictly post-entry; all prices from frozen snapshots
(hash-verified), zero live fetches.

USAGE:
  rtk uv run python -m scripts.research.spx_deletion_reversal_study \
      --output reports/spx_deletion_reversal_2018_2026.json
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from src.factors.fundamentals_pit_loader import FundamentalsPITLoader
from src.factors.price_quality import has_price_artifact
from src.storage.snapshot import SNAPSHOT_ROOT, load_snapshot

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("spx_deletion_reversal")

# ---- pre-registered parameters (DO NOT TUNE) --------------------------------
START = pd.Timestamp("2018-01-02")
END = pd.Timestamp("2026-06-01")
ENTRY_LAG_PRIMARY = 5            # trading days after effective date
ENTRY_LAG_ARMS = (1, 3, 5)       # jitter arms; 5 is primary
HOLD_PRIMARY = 126               # trading days; graded
HOLD_ARMS = (21, 63, 126)
COST_PRIMARY = 0.0050            # 50bps round-trip, charged in full; graded
COST_ARMS = (0.0025, 0.0050)
BETA_WINDOW = 252
BETA_MIN_OBS = 120
N_CONTROLS = 3
PERMUTATION_N = 1000
MIN_EVENTS = 50                  # clause 1: below this -> ABORT, not a verdict
MIN_YEAR_EVENTS = 3              # a year needs >=3 events to count for clause 5
MOM_LOOKBACK, MOM_SKIP = 252, 21  # 12-1 momentum
DVOL_WINDOW = 63
MNA_REASON_RE = re.compile(
    r"acquir|merge|merging|take.?private|private equity|takeover|tender|"
    r"bought|purchas|combin", re.IGNORECASE,
)
# The 7 sp500_pit breadth snapshots, chronological. Each event is assigned to
# the earliest snapshot whose panel fully contains its entry + hold.
SNAPSHOT_IDS = [
    "acd1e7401c6484cf",  # 2018-2020
    "a36c9bfd0c353b53",  # 2019-2021
    "2c853f10c6638fc0",  # 2020-2022
    "57016c1293f136cd",  # 2021-2023
    "1c1c314850bb7368",  # 2022-2024
    "a347da6750f42939",  # 2023-2025
    "fe045eff04a15142",  # 2024-2026
]
CHANGES_CSV = Path("data/universe/sp500_changes.csv")


# ============================================================================
# Events
# ============================================================================
def load_events(changes_csv: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(candidate demotions, excluded-as-M&A) from the membership log."""
    df = pd.read_csv(changes_csv)
    df["date"] = pd.to_datetime(df["date"])
    removals = df[(df["action"] == "remove") & (df["date"] >= START) & (df["date"] <= END)].copy()
    reason = removals["reason"].fillna("")
    is_mna = reason.str.contains(MNA_REASON_RE)
    return removals[~is_mna].reset_index(drop=True), removals[is_mna].reset_index(drop=True)


def never_deleted_pool(changes_csv: Path) -> set[str]:
    """Tickers never removed 2018-2026 — the matched-control eligibility set."""
    df = pd.read_csv(changes_csv)
    df["date"] = pd.to_datetime(df["date"])
    removed = set(df[(df["action"] == "remove") & (df["date"] >= START)]["ticker"])
    return removed  # callers EXCLUDE this set


# ============================================================================
# Per-snapshot machinery
# ============================================================================
class SnapPanel:
    """Lazy holder for one snapshot's prices/SPY/fundamentals."""

    def __init__(self, snapshot_id: str) -> None:
        self.snapshot_id = snapshot_id
        inputs = load_snapshot(snapshot_id, SNAPSHOT_ROOT)
        self.prices = inputs.price_data
        self.spy = inputs.spy_df["Close"].astype(float)
        self.calendar = self.spy.index  # trading calendar
        fund_path = Path(SNAPSHOT_ROOT) / snapshot_id / "fundamentals_pit.json"
        self.funds = FundamentalsPITLoader.from_json(fund_path) if fund_path.exists() else None
        self.window_start = self.calendar[0]
        self.window_end = self.calendar[-1]

    def trading_day_after(self, ts: pd.Timestamp, lag: int) -> pd.Timestamp | None:
        """The `lag`-th trading day strictly after ts, or None if off-panel."""
        idx = self.calendar.searchsorted(ts, side="right")
        target = idx + lag - 1
        if target >= len(self.calendar):
            return None
        return self.calendar[target]

    def close_series(self, ticker: str) -> pd.Series | None:
        df = self.prices.get(ticker)
        if df is None or "Close" not in df.columns:
            return None
        return df["Close"].astype(float)

    def dollar_volume(self, ticker: str, as_of: pd.Timestamp) -> float | None:
        df = self.prices.get(ticker)
        if df is None or "Volume" not in df.columns:
            return None
        sl = df.loc[:as_of].tail(DVOL_WINDOW)
        if len(sl) < DVOL_WINDOW // 2:
            return None
        return float((sl["Close"] * sl["Volume"]).mean())

    def mom_12_1(self, ticker: str, as_of: pd.Timestamp) -> float | None:
        s = self.close_series(ticker)
        if s is None:
            return None
        sl = s.loc[:as_of]
        if len(sl) < MOM_LOOKBACK + 1:
            return None
        p_now, p_skip, p_then = sl.iloc[-1], sl.iloc[-MOM_SKIP], sl.iloc[-MOM_LOOKBACK]
        if p_then <= 0 or p_skip <= 0:
            return None
        return float(p_skip / p_then - 1.0)

    def beta(self, ticker: str, as_of: pd.Timestamp) -> float | None:
        s = self.close_series(ticker)
        if s is None:
            return None
        r_t = s.loc[:as_of].pct_change().dropna().tail(BETA_WINDOW)
        r_m = self.spy.loc[:as_of].pct_change().dropna()
        joined = pd.concat([r_t, r_m], axis=1, join="inner").dropna()
        if len(joined) < BETA_MIN_OBS:
            return None
        x, y = joined.iloc[:, 1].values, joined.iloc[:, 0].values
        var = np.var(x)
        if var <= 0:
            return None
        return float(np.cov(y, x)[0, 1] / var)

    def forward_return(
        self, ticker: str, entry: pd.Timestamp, hold: int
    ) -> tuple[float, bool, pd.Timestamp] | None:
        """(simple return entry->exit close, delisted_mid_hold, exit_date).
        Delisting-aware: realize the last available close if the name stops
        trading mid-hold."""
        s = self.close_series(ticker)
        if s is None or entry not in s.index:
            return None
        target = self.trading_day_after(entry, hold)
        if target is None:
            return None  # hold runs off the panel — caller assigns a later snapshot
        fwd = s.loc[entry:target]
        if len(fwd) < 2:
            return None
        exit_px, exit_dt = float(fwd.iloc[-1]), fwd.index[-1]
        delisted = exit_dt < target and (s.index[-1] == exit_dt)
        entry_px = float(s.loc[entry])
        if entry_px <= 0:
            return None
        return exit_px / entry_px - 1.0, bool(delisted), exit_dt

    def spy_return(self, entry: pd.Timestamp, exit_dt: pd.Timestamp) -> float:
        return float(self.spy.loc[exit_dt] / self.spy.loc[entry] - 1.0)

    def solvent(self, ticker: str, as_of: pd.Timestamp) -> bool | None:
        """EPS-TTM > 0 OR FCF > 0, PIT. None = no fundamentals coverage."""
        if self.funds is None:
            return None
        dt = datetime(as_of.year, as_of.month, as_of.day, tzinfo=timezone.utc)
        eps = self.funds.compute_eps_ttm(ticker, dt)
        snap = self.funds.lookup(ticker, dt)
        fcf = snap.free_cash_flow if snap else None
        if eps is None and fcf is None:
            return None
        return bool((eps is not None and eps > 0) or (fcf is not None and fcf > 0))

    def sector(self, ticker: str, as_of: pd.Timestamp) -> str | None:
        if self.funds is None:
            return None
        dt = datetime(as_of.year, as_of.month, as_of.day, tzinfo=timezone.utc)
        return self.funds.lookup_sector(ticker, dt)

    def artifact_in_window(self, ticker: str, exit_dt: pd.Timestamp) -> bool:
        df = self.prices.get(ticker)
        if df is None:
            return False
        return has_price_artifact(df, exit_dt)

    def mom_percentile(self, ticker: str, as_of: pd.Timestamp) -> float | None:
        """Percentile of ticker's 12-1 momentum in the full panel cross-section."""
        own = self.mom_12_1(ticker, as_of)
        if own is None:
            return None
        moms = [m for t in self.prices if (m := self.mom_12_1(t, as_of)) is not None]
        if len(moms) < 100:
            return None
        return float(100.0 * np.mean([m < own for m in moms]))


def assign_snapshot(
    panels: dict[str, SnapPanel], t_eff: pd.Timestamp, lag: int, hold: int
) -> tuple[str, pd.Timestamp] | None:
    """Earliest snapshot whose calendar contains entry AND entry+hold."""
    for sid in SNAPSHOT_IDS:
        p = panels[sid]
        if not (p.window_start <= t_eff <= p.window_end):
            continue
        entry = p.trading_day_after(t_eff, lag)
        if entry is None:
            continue
        if p.trading_day_after(entry, hold) is None:
            continue
        return sid, entry
    return None


# ============================================================================
# Controls
# ============================================================================
def pick_controls(
    panel: SnapPanel, ticker: str, entry: pd.Timestamp, deleted_ever: set[str]
) -> list[str]:
    """Up to N_CONTROLS same-sector never-deleted names nearest in
    (12-1 momentum, log 63d dollar-volume) z-distance at entry."""
    sec = panel.sector(ticker, entry)
    ev_mom = panel.mom_12_1(ticker, entry)
    ev_dv = panel.dollar_volume(ticker, entry)
    if ev_mom is None or ev_dv is None or ev_dv <= 0:
        return []
    rows = []
    for cand in panel.prices:
        if cand == ticker or cand in deleted_ever:
            continue
        m = panel.mom_12_1(cand, entry)
        dv = panel.dollar_volume(cand, entry)
        if m is None or dv is None or dv <= 0:
            continue
        rows.append((cand, m, np.log(dv), panel.sector(cand, entry)))
    if not rows:
        return []
    cdf = pd.DataFrame(rows, columns=["ticker", "mom", "ldv", "sector"])
    same_sec = cdf[cdf["sector"] == sec] if sec else cdf
    pool = same_sec if len(same_sec) >= N_CONTROLS else cdf
    mom_sd = cdf["mom"].std() or 1.0
    ldv_sd = cdf["ldv"].std() or 1.0
    dist = ((pool["mom"] - ev_mom) / mom_sd) ** 2 + ((pool["ldv"] - np.log(ev_dv)) / ldv_sd) ** 2
    return pool.loc[dist.nsmallest(N_CONTROLS).index, "ticker"].tolist()


# ============================================================================
# Study
# ============================================================================
def event_alpha(
    panel: SnapPanel, ticker: str, entry: pd.Timestamp, hold: int, cost: float
) -> dict | None:
    beta = panel.beta(ticker, entry)
    if beta is None:
        return None
    fwd = panel.forward_return(ticker, entry, hold)
    if fwd is None:
        return None
    ret, delisted, exit_dt = fwd
    alpha = ret - beta * panel.spy_return(entry, exit_dt) - cost
    return {"alpha": alpha, "ret": ret, "beta": beta, "delisted": delisted, "exit": str(exit_dt.date())}


def run_study(args: argparse.Namespace) -> dict:
    events, excluded_mna = load_events(Path(args.changes))
    deleted_ever = never_deleted_pool(Path(args.changes))
    logger.info("removals 2018+: %d candidates after M&A filter (%d excluded as M&A)",
                len(events), len(excluded_mna))

    panels = {sid: SnapPanel(sid) for sid in SNAPSHOT_IDS}
    logger.info("loaded %d snapshots", len(panels))

    rows, skipped = [], {"no_snapshot": 0, "no_bar_at_entry": 0, "no_beta_or_fwd": 0, "artifact": []}
    for _, ev in events.iterrows():
        t_eff, ticker = ev["date"], str(ev["ticker"]).upper()
        assigned = assign_snapshot(panels, t_eff, ENTRY_LAG_PRIMARY, HOLD_PRIMARY)
        if assigned is None:
            skipped["no_snapshot"] += 1
            continue
        sid, entry = assigned
        panel = panels[sid]
        s = panel.close_series(ticker)
        if s is None or entry not in s.index:
            skipped["no_bar_at_entry"] += 1  # acquired/halted -> not a demotion
            continue
        primary = event_alpha(panel, ticker, entry, HOLD_PRIMARY, COST_PRIMARY)
        if primary is None:
            skipped["no_beta_or_fwd"] += 1
            continue
        exit_ts = pd.Timestamp(primary["exit"])
        if panel.artifact_in_window(ticker, exit_ts):
            skipped["artifact"].append(ticker)
            continue

        row = {
            "ticker": ticker, "effective": str(t_eff.date()), "entry": str(entry.date()),
            "year": int(t_eff.year), "snapshot": sid, "reason": str(ev["reason"])[:120],
            "solvent": panel.solvent(ticker, entry),
            "mom_pct": panel.mom_percentile(ticker, entry),
            **{f"primary_{k}": v for k, v in primary.items()},
        }
        # hold read-outs (reported)
        for h in HOLD_ARMS:
            if h == HOLD_PRIMARY:
                continue
            r = event_alpha(panel, ticker, entry, h, COST_PRIMARY)
            row[f"alpha_{h}d"] = r["alpha"] if r else None
        # cost arm (reported)
        row["alpha_25bps"] = primary["alpha"] + (COST_PRIMARY - COST_ARMS[0])
        # entry-jitter arms (clause 8)
        for lag in ENTRY_LAG_ARMS:
            if lag == ENTRY_LAG_PRIMARY:
                row[f"alpha_T{lag}"] = primary["alpha"]
                continue
            aj = assign_snapshot(panels, t_eff, lag, HOLD_PRIMARY)
            r = event_alpha(panels[aj[0]], ticker, aj[1], HOLD_PRIMARY, COST_PRIMARY) if aj else None
            row[f"alpha_T{lag}"] = r["alpha"] if r else None
        # matched controls
        ctrl_alphas = []
        for c in pick_controls(panel, ticker, entry, deleted_ever):
            r = event_alpha(panel, c, entry, HOLD_PRIMARY, COST_PRIMARY)
            if r is not None:
                ctrl_alphas.append(r["alpha"])
        row["ctrl_alphas"] = ctrl_alphas
        row["ctrl_median"] = float(np.median(ctrl_alphas)) if ctrl_alphas else None
        rows.append(row)
        logger.info("%s %s entry=%s alpha126=%+.1f%% solvent=%s ctrls=%d",
                    ticker, row["effective"], row["entry"],
                    100 * primary["alpha"], row["solvent"], len(ctrl_alphas))

    all_df = pd.DataFrame(rows)
    return grade(all_df, skipped, len(events), len(excluded_mna))


def _clause(df: pd.DataFrame) -> dict:
    """Clauses 2-5 on one arm's frame (alpha col = primary_alpha)."""
    a = df["primary_alpha"].astype(float)
    inc_df = df.dropna(subset=["ctrl_median"])
    inc = inc_df["primary_alpha"] - inc_df["ctrl_median"]
    years = {}
    for y, g in df.groupby("year"):
        if len(g) >= MIN_YEAR_EVENTS:
            years[int(y)] = float(g["primary_alpha"].median())
    yrs_eval = {y: m for y, m in years.items() if 2018 <= y <= 2025}
    return {
        "n": int(len(df)),
        "median_alpha": float(a.median()) if len(a) else None,
        "mean_alpha": float(a.mean()) if len(a) else None,
        "n_with_controls": int(len(inc_df)),
        "ctrl_increment_median": float(inc.median()) if len(inc) else None,
        "win_rate_vs_ctrl": float((inc > 0).mean()) if len(inc) else None,
        "year_medians": years,
        "years_positive": sum(1 for m in yrs_eval.values() if m > 0),
        "years_evaluable": len(yrs_eval),
        "n_delisted_in_hold": int(df["primary_delisted"].sum()),
    }


def permutation_p(df: pd.DataFrame, rng: np.random.Generator) -> float | None:
    """Within-year label swap: pseudo-event = random control. p = fraction of
    permuted median increments >= observed."""
    inc_df = df.dropna(subset=["ctrl_median"])
    inc_df = inc_df[inc_df["ctrl_alphas"].map(len) > 0]
    if len(inc_df) < 10:
        return None
    observed = float((inc_df["primary_alpha"] - inc_df["ctrl_median"]).median())
    stats = []
    for _ in range(PERMUTATION_N):
        vals = []
        for _, r in inc_df.iterrows():
            pool = [r["primary_alpha"], *r["ctrl_alphas"]]
            pseudo = pool.pop(rng.integers(len(pool)))
            vals.append(pseudo - float(np.median(pool)))
        stats.append(np.median(vals))
    return float(np.mean([s >= observed for s in stats]))


def grade(all_df: pd.DataFrame, skipped: dict, n_candidates: int, n_mna: int) -> dict:
    rng = np.random.default_rng(42)  # deterministic permutation
    out: dict = {
        "study": "spx_deletion_reversal", "generated": "see git log",
        "preregistered": "workflow wf_ae576aed-ab6 merged rank-1+2; this script encodes the bar verbatim",
        "n_removals_candidates": n_candidates, "n_excluded_mna": n_mna,
        "skipped": {k: (v if not isinstance(v, list) else v) for k, v in skipped.items()},
    }
    if all_df.empty:
        out["verdict"] = "ABORT — zero usable events"
        return out

    graded = all_df[all_df["solvent"] == True]  # noqa: E712 — the pre-registered arm
    no_cond = all_df                            # reported arm
    out["graded_arm"] = _clause(graded)
    out["no_conditioning_arm"] = _clause(no_cond)
    out["no_fundamentals_coverage"] = int((all_df["solvent"].isna()).sum())

    g = out["graded_arm"]
    out["events"] = all_df.drop(columns=["ctrl_alphas"]).to_dict(orient="records")
    # clause 1 — power
    if g["n"] < MIN_EVENTS:
        out["verdict"] = (f"ABORT-UNDERPOWERED — {g['n']} qualifying events in the graded "
                          f"(solvency-floor) arm < pre-registered minimum {MIN_EVENTS}. "
                          "Not graded pass/fail per spec.")
        out["clauses"] = {"1_min_events": False}
        return out

    p = permutation_p(graded, rng)
    jitter = {f"T{lag}": (float(graded[f"alpha_T{lag}"].dropna().median())
                          if f"alpha_T{lag}" in graded else None)
              for lag in ENTRY_LAG_ARMS}
    mom_pct = graded["mom_pct"].dropna()
    holds = {f"{h}d": (float(graded[f"alpha_{h}d"].dropna().median())
                       if f"alpha_{h}d" in graded else None)
             for h in HOLD_ARMS if h != HOLD_PRIMARY}
    out["permutation_p"] = p
    out["entry_jitter_medians"] = jitter
    out["hold_readouts_median"] = holds
    out["alpha_25bps_median"] = float(graded["alpha_25bps"].median())
    out["mom_pct_median"] = float(mom_pct.median()) if len(mom_pct) else None

    clauses = {
        "1_min_events": g["n"] >= MIN_EVENTS,
        "2_median_ge_4pct_and_mean_pos": (g["median_alpha"] is not None
                                          and g["median_alpha"] >= 0.04 and g["mean_alpha"] > 0),
        "3_ctrl_increment_ge_3pp_p_lt_05": (g["ctrl_increment_median"] is not None
                                            and g["ctrl_increment_median"] >= 0.03
                                            and p is not None and p < 0.05),
        "4_winrate_ge_55": g["win_rate_vs_ctrl"] is not None and g["win_rate_vs_ctrl"] >= 0.55,
        "5_year_breadth_6_of_8": g["years_positive"] >= 6,
        "6_survives_50bps": True,  # all graded numbers already charged at 50bps
        "7_anti_momentum_lt_30pct": out["mom_pct_median"] is not None and out["mom_pct_median"] < 30,
        "8_entry_jitter_all_positive": all(v is not None and v > 0 for v in jitter.values()),
    }
    out["clauses"] = clauses
    out["verdict"] = "PASS — all clauses hold" if all(clauses.values()) else (
        "NO-SHIP (NULL) — failed: " + ", ".join(k for k, v in clauses.items() if not v))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--changes", default=str(CHANGES_CSV))
    ap.add_argument("--output", default="reports/spx_deletion_reversal_2018_2026.json")
    args = ap.parse_args()

    result = run_study(args)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

    tickers_path = out_path.parent / "spx_deletion_event_tickers.txt"
    if "events" in result:
        tickers_path.write_text(
            "\n".join(sorted({e["ticker"] for e in result["events"]})), encoding="utf-8")

    print("\n" + "=" * 72)
    print("SPX DELETION-REVERSAL — PRE-REGISTERED VERDICT")
    print("=" * 72)
    for arm in ("graded_arm", "no_conditioning_arm"):
        if arm in result:
            a = result[arm]
            print(f"{arm}: n={a['n']}  median={a['median_alpha']:+.2%}  mean={a['mean_alpha']:+.2%}  "
                  f"ctrl_inc={a['ctrl_increment_median']:+.2%}  win={a['win_rate_vs_ctrl']:.0%}  "
                  f"years+ {a['years_positive']}/{a['years_evaluable']}  "
                  f"delisted_in_hold={a['n_delisted_in_hold']}"
                  if a["median_alpha"] is not None else f"{arm}: n={a['n']} (insufficient)")
    if "permutation_p" in result:
        print(f"permutation_p={result['permutation_p']}  "
              f"jitter={result['entry_jitter_medians']}  holds={result['hold_readouts_median']}  "
              f"mom_pct_median={result['mom_pct_median']}")
    if "clauses" in result:
        for k, v in result["clauses"].items():
            print(f"  clause {k}: {'PASS' if v else 'FAIL'}")
    print(f"\nVERDICT: {result['verdict']}")
    print(f"output: {out_path}")


if __name__ == "__main__":
    main()
