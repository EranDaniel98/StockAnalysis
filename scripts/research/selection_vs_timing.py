# /// script
# dependencies = ["pandas", "numpy"]
# ///
"""Split the gated book's CAPM-alpha into SELECTION vs TIMING — two ways.

Red-team finding: CAPM single-beta alpha over-credits a regime-TIMER as alpha
(Treynor-Mazuy 1966), and the COVID +22.8% is plausibly a beta-estimation
artifact of sitting in cash through the crash. This isolates selection skill:

  1) GATE-OFF run (--no-regime-filter): always fully invested (beta~1, no
     timing). Its CAPM-alpha IS pure selection skill, cleanly specified.
  2) TREYNOR-MAZUY / HENRIKSSON-MERTON on the gate-ON daily returns:
       r_p = a + b*r_m + g*r_m^2 + e   (TM; g>0 = market-timing skill)
       r_p = a + b*r_m + g*max(0,r_m)  (HM)
     a = selection alpha NET of timing; g = the timing term the single-beta
     CAPM was mislabeling as alpha.

Both run at $100M starting cash (the $10k default sits in integer-share
rounding cash — audit #19 — which dampened every prior run this session).

Single rebalance offset per window (the timing/selection SPLIT is stable
across offsets even though magnitude is phase-luck-prone). Directional.

    uv run python -m scripts.research.selection_vs_timing "2020-22=2c853f10c6638fc0" ...
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

_BASE = ("--factor composite --composite-factors mqv --top-decile 0.05 --cost-bps 5.0 "
         "--asymmetric-trend --entry-sma 75 --regime-band-pct 0.03 --include-pead "
         "--sector-neutral-quality --hysteresis-bonus 0.75 --momentum-flavor raw "
         "--starting-cash 100000000").split()


def _run(snap: str, gate_on: bool) -> dict:
    out = ROOT / "reports" / f".svt_{snap}_{'on' if gate_on else 'off'}.json"
    gate = ["--daily-regime"] if gate_on else ["--no-regime-filter", "--no-daily-regime"]
    cmd = ([sys.executable, "-m", "scripts.run_factor_backtest", "--snapshot-id", snap,
            "--rebalance-days", "63", "--rebal-offset", "0", "--output", str(out)]
           + _BASE + gate)
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if p.returncode != 0:
        sys.exit(f"backtest failed ({snap}, gate={'on' if gate_on else 'off'}):\n{p.stderr[-1500:]}")
    d = json.loads(out.read_text())
    out.unlink(missing_ok=True)
    return d


def _strat_rets(d: dict) -> pd.Series:
    ec = pd.DataFrame(d["equity_curve"], columns=["date", "equity"])
    ec["date"] = pd.to_datetime(ec["date"])
    s = ec.set_index("date")["equity"].pct_change().dropna()
    return s


def _spy_rets(snap: str) -> pd.Series:
    # SPY lives in its own spy.parquet (NOT prices.parquet, which is the universe).
    df = pd.read_parquet(ROOT / "data" / "snapshots" / snap / "spy.parquet")
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")["Close"].pct_change().dropna()


def _ols(y: np.ndarray, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Returns (coefs, t_stats)."""
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    dof = max(1, len(y) - X.shape[1])
    s2 = (resid @ resid) / dof
    xtx_inv = np.linalg.pinv(X.T @ X)  # pinv: robust to ill-conditioning
    se = np.sqrt(np.diag(s2 * xtx_inv))
    return beta, beta / np.where(se > 0, se, np.nan)


def _timing_split(rp: pd.Series, rm: pd.Series) -> dict:
    m = pd.concat([rp, rm], axis=1, keys=["p", "m"]).dropna()
    y = m["p"].values
    rmv = m["m"].values
    one = np.ones_like(rmv)
    # Treynor-Mazuy: r_p = a + b*r_m + g*r_m^2
    tm_b, tm_t = _ols(y, np.column_stack([one, rmv, rmv**2]))
    # Henriksson-Merton: r_p = a + b*r_m + g*max(0,r_m)
    hm_b, hm_t = _ols(y, np.column_stack([one, rmv, np.maximum(0, rmv)]))
    return {
        "n": len(y),
        "tm_alpha_ann": tm_b[0] * 252 * 100, "tm_alpha_t": tm_t[0],
        "tm_gamma": tm_b[2], "tm_gamma_t": tm_t[2],
        "hm_alpha_ann": hm_b[0] * 252 * 100, "hm_alpha_t": hm_t[0],
        "hm_gamma": hm_b[2], "hm_gamma_t": hm_t[2],
    }


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: selection_vs_timing.py 'label=snap' ...")
        return 2
    rows = []
    for arg in argv:
        label, _, snap = arg.partition("=")
        on = _run(snap, gate_on=True)
        off = _run(snap, gate_on=False)
        tm = _timing_split(_strat_rets(on), _spy_rets(snap))
        rows.append({
            "label": label,
            "on_capm": on["capm_alpha_pct"], "on_beta": on["beta"],
            "off_capm": off["capm_alpha_pct"], "off_beta": off["beta"],
            "off_excess": off["alpha_vs_spy_pct"],
            **tm,
        })
        print(f"  {label}: gate-on CAPMa {on['capm_alpha_pct']:+.1f}% (b{on['beta']:.2f}) | "
              f"gate-OFF CAPMa {off['capm_alpha_pct']:+.1f}% (b{off['beta']:.2f}) | "
              f"TM a {tm['tm_alpha_ann']:+.1f}%(t{tm['tm_alpha_t']:+.1f}) g {tm['tm_gamma']:+.1f}(t{tm['tm_gamma_t']:+.1f})")

    print(f"\n{'window':9}{'on_CAPMa':>9}{'OFF_CAPMa':>10}{'OFF_excess':>11}"
          f"{'TM_alpha':>10}{'TM_g(t)':>10}{'HM_alpha':>10}{'HM_g(t)':>10}")
    for r in rows:
        print(f"{r['label']:9}{r['on_capm']:>+9.1f}{r['off_capm']:>+10.1f}{r['off_excess']:>+11.1f}"
              f"{r['tm_alpha_ann']:>+10.1f}{r['tm_gamma_t']:>+10.1f}"
              f"{r['hm_alpha_ann']:>+10.1f}{r['hm_gamma_t']:>+10.1f}")

    off = [r["off_capm"] for r in rows]
    tma = [r["tm_alpha_ann"] for r in rows]
    npos_off = sum(x > 0 for x in off)
    npos_tm = sum(x > 0 for x in tma)
    print(f"\n=== SELECTION-ONLY (gate-off CAPM-alpha, beta~1, $100M) ===")
    print(f"  positive in {npos_off}/{len(off)} windows | median {np.median(off):+.1f}% | mean {np.mean(off):+.1f}%")
    print(f"=== TM selection-alpha (timing removed) ===")
    print(f"  positive in {npos_tm}/{len(tma)} windows | median {np.median(tma):+.1f}% | mean {np.mean(tma):+.1f}%")
    print("  (gamma_t > ~2 = significant market-timing the single-beta CAPM was crediting as alpha)")
    print("\nCAVEAT: single offset (offset 0) per window — decomposition is directional, not "
          "phase-averaged. $100M cash (fixes the $10k rounding-dampening). rf~0.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
