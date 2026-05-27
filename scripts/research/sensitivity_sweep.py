"""Parameter-sensitivity sweep around the PRODUCTION config.

Is the edge a PLATEAU (robust) or a KNIFE-EDGE (overfit)? Varies one knob at a
time, holds the rest at production, and reports the phase-averaged CAPM-alpha
envelope for each value. A free overfitting test on existing data — no new
windows, no $79 tier. If CAPM-alpha collapses one notch off the production
value, the config is fit to noise; if it holds across neighbours, it's real.

Production config (daily_factor_picks): top_n=24 (~top-decile 0.048), mqv,
sector-neutral-quality ON, PEAD ON, hysteresis 0.75, 75-SMA asymmetric gate.

Usage:
  uv run python scripts/research/sensitivity_sweep.py --snapshot-id fe045eff04a15142
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Production values (the held-constant baseline for every one-at-a-time sweep).
PROD = {"top_decile": 0.048, "entry_sma": 75, "hysteresis_bonus": 0.75, "cost_bps": 5.0}

# Always-on production flags + factor selection.
FIXED = ["--factor", "composite", "--composite-factors", "mqv", "--momentum-flavor", "raw",
         "--asymmetric-trend", "--include-pead", "--sector-neutral-quality"]

# One-at-a-time grid. Each list includes the production value so the base shows
# up in-line with its neighbours.
# Trimmed to the two OVERFIT-PRONE knobs (the d03/d05 concentration saga + the
# regime-gate whipsaw saga). cost_bps is a known plateau (prior cost sweep) and
# hysteresis was separately validated, so they're skipped here for runtime
# (~82s/backtest * 9 phases each). Add them back by extending this dict.
GRID = {
    "top_decile": [0.03, 0.048, 0.07, 0.10],      # ~top-15 / 24 / 35 / 50 (concentration)
    "entry_sma": [50, 75, 100, 200],              # regime-gate trend window
}


def _build_args(param: str, value: float) -> list[str]:
    vals = dict(PROD)
    vals[param] = value
    return FIXED + [
        "--top-decile", str(vals["top_decile"]),
        "--entry-sma", str(int(vals["entry_sma"])),
        "--hysteresis-bonus", str(vals["hysteresis_bonus"]),
        "--cost-bps", str(vals["cost_bps"]),
    ]


def _run_envelope(snap: str, base_args: list[str]) -> dict:
    cmd = [sys.executable, "scripts/phase_envelope.py", "--snapshot-id", snap,
           "--base-args", " ".join(base_args)]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"envelope failed for {base_args}:\n{proc.stderr[-1500:]}")
    rep = json.loads((ROOT / "reports" / f"phase_envelope_{snap}.json").read_text())
    return rep["envelope"]["capm_alpha"] | {"verdict": rep["verdict"]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshot-id", required=True)
    args = ap.parse_args()

    print(f"sensitivity sweep | snap={args.snapshot_id} | production held at {PROD}\n")
    print(f"{'param':18}{'value':>8}{'capmA med':>11}{'mean':>8}{'%pos':>6}  verdict")
    out_rows = []
    for param, values in GRID.items():
        for v in values:
            e = _run_envelope(args.snapshot_id, _build_args(param, v))
            is_base = abs(float(v) - float(PROD[param])) < 1e-9
            tag = "  <-PROD" if is_base else ""
            short = "ROBUST" if e["verdict"].startswith("ROBUST") else "fragile"
            print(f"{param:18}{v:>8}{e['median']:>+11.2f}{e['mean']:>+8.2f}"
                  f"{e['pct_phases_positive']:>5.0f}%  {short}{tag}")
            out_rows.append({"param": param, "value": v, "is_base": is_base, **e})
        print()

    out = ROOT / "reports" / f"sensitivity_{args.snapshot_id}.json"
    out.write_text(json.dumps({"snapshot": args.snapshot_id, "production": PROD,
                               "rows": out_rows}, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
