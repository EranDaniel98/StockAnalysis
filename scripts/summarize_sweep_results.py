"""Summarize sweep_battery results into a side-by-side delta vs. baseline.

Each sweep JSON is a list of cells (insider_flow modes — off / signal_only /
weighted). The post-silent-50-clean-pipeline re-baseline (data/
sweep_battery_post_status/) needs to be compared against the pre-fix
results (data/sweep_battery/) to answer:

  1. Does min_score=50 still win on the clean pipeline? (was 1.61 → ?)
  2. Did the silent-50 fix shift the cross-strategy ranking?
  3. Which strategies regressed and which improved?

Output is both a console table (for quick review) and a markdown block
suitable for dropping into a memory entry (project_sweep_results_clean.md).

Run after the sweep battery completes:

    uv run python -m scripts.summarize_sweep_results

Or point at custom directories:

    uv run python -m scripts.summarize_sweep_results \
        --new data/sweep_battery_post_status \
        --baseline data/sweep_battery
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# Cells we care about for the headline comparison. The third mode
# (weighted with insider_weight > 0) varies; we collapse to mode label.
HEADLINE_METRICS = (
    "oos_sharpe",
    "oos_return_pct",
    "full_sharpe",
    "full_return_pct",
    "max_dd_pct",
    "win_rate_pct",
    "n_oos_trades",
    "n_trades",
)


@dataclass
class CellResult:
    """One cell of one sweep — insider mode + the headline metrics."""

    mode: str
    insider_weight: float
    analyzer_active: bool
    n_trades: int
    n_oos_trades: int
    full_return_pct: float
    oos_return_pct: float
    full_sharpe: float
    oos_sharpe: float
    max_dd_pct: float
    win_rate_pct: float

    @classmethod
    def from_dict(cls, d: dict) -> "CellResult":
        return cls(
            mode=str(d.get("mode", "")),
            insider_weight=float(d.get("insider_weight", 0)),
            analyzer_active=bool(d.get("analyzer_active", False)),
            n_trades=int(d.get("n_trades", 0)),
            n_oos_trades=int(d.get("n_oos_trades", 0)),
            full_return_pct=float(d.get("full_return_pct", 0)),
            oos_return_pct=float(d.get("oos_return_pct", 0)),
            full_sharpe=float(d.get("full_sharpe", 0)),
            oos_sharpe=float(d.get("oos_sharpe", 0)),
            max_dd_pct=float(d.get("max_dd_pct", 0)),
            win_rate_pct=float(d.get("win_rate_pct", 0)),
        )

    def key(self) -> str:
        """Stable cell identifier for old↔new pairing. Mode + weight is
        sufficient because the sweep battery emits exactly one cell per
        (mode, insider_weight) combination."""
        return f"{self.mode}:{self.insider_weight:.2f}"


@dataclass
class StrategySweep:
    """All cells for one strategy file."""

    strategy: str
    file_path: Path
    cells: list[CellResult]

    def by_key(self) -> dict[str, CellResult]:
        return {c.key(): c for c in self.cells}


def load_sweep(path: Path) -> Optional[StrategySweep]:
    """Read one sweep file. Returns None if missing/malformed; the caller
    handles the absence as "no baseline" rather than crashing."""
    if not path.exists():
        return None
    try:
        with path.open() as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"  ⚠️  failed to load {path}: {e}")
        return None
    if not isinstance(data, list):
        print(f"  ⚠️  unexpected schema in {path}: top-level is {type(data).__name__}, expected list")
        return None
    strategy = _strategy_from_filename(path.name)
    cells = [CellResult.from_dict(c) for c in data]
    return StrategySweep(strategy=strategy, file_path=path, cells=cells)


def _strategy_from_filename(name: str) -> str:
    """``sweep_russell_1000_swing_trading_2y.json`` -> ``swing_trading``.
    Robust to other universes/years — strip the ``sweep_<universe>_`` prefix
    and the ``_Ny.json`` suffix."""
    stem = name.removesuffix(".json").removesuffix(".full")
    parts = stem.split("_")
    # Expected: ['sweep', <universe parts>, <strategy parts>, '<N>y']
    if parts and parts[0] == "sweep":
        parts = parts[1:]
    if parts and parts[-1].endswith("y") and parts[-1][:-1].replace(".", "").isdigit():
        parts = parts[:-1]
    # Strip known universe prefixes (russell_1000, russell_2000, themes, etc.).
    if parts[:2] == ["russell", "1000"] or parts[:2] == ["russell", "2000"]:
        parts = parts[2:]
    elif parts and parts[0] in {"themes", "watchlist", "value_cohort"}:
        parts = parts[1:]
    return "_".join(parts) if parts else stem


def fmt_delta(new: float, old: Optional[float], *, units: str = "", precision: int = 2) -> str:
    """Render ``NEW (Δ +X.XX)`` with sign + units, or ``NEW (new)`` if no baseline."""
    n_str = f"{new:.{precision}f}{units}"
    if old is None:
        return f"{n_str} (new)"
    delta = new - old
    sign = "+" if delta >= 0 else ""
    return f"{n_str} ({sign}{delta:.{precision}f})"


def print_strategy_table(new: StrategySweep, baseline: Optional[StrategySweep]) -> None:
    """Console-friendly side-by-side dump per cell."""
    print()
    print(f"=== {new.strategy} " + "=" * max(0, 60 - len(new.strategy)))
    if baseline is None:
        print("  (no pre-clean baseline — strategy is new in this battery)")

    base_by_key = baseline.by_key() if baseline else {}
    # Header
    print(f"  {'cell':<25} {'oos_sharpe':>16} {'oos_ret%':>14} {'win%':>12} {'n_oos':>8}")
    print(f"  {'-'*25} {'-'*16} {'-'*14} {'-'*12} {'-'*8}")
    for c in new.cells:
        old = base_by_key.get(c.key())
        cell_label = f"{c.mode}@{c.insider_weight:.2f}"
        print(
            f"  {cell_label:<25} "
            f"{fmt_delta(c.oos_sharpe, old.oos_sharpe if old else None, precision=2):>16} "
            f"{fmt_delta(c.oos_return_pct, old.oos_return_pct if old else None, units='%', precision=2):>14} "
            f"{fmt_delta(c.win_rate_pct, old.win_rate_pct if old else None, units='%', precision=1):>12} "
            f"{fmt_delta(c.n_oos_trades, old.n_oos_trades if old else None, precision=0):>8}"
        )


def find_best_mode(sweep: StrategySweep) -> CellResult:
    """The cell with the highest oos_sharpe wins. Tie-break on
    (oos_return_pct, n_oos_trades) so a more-trades winner beats a
    fluky few-trades one."""
    return max(
        sweep.cells,
        key=lambda c: (c.oos_sharpe, c.oos_return_pct, c.n_oos_trades),
    )


def build_markdown_summary(
    new_sweeps: list[StrategySweep],
    base_sweeps: dict[str, StrategySweep],
) -> str:
    """Memory-entry-ready markdown. One section per strategy, plus a
    cross-strategy leaderboard at the top."""
    lines: list[str] = []
    lines.append("# Sweep battery — post-clean-pipeline re-baseline")
    lines.append("")
    lines.append("**Generated:** by `scripts.summarize_sweep_results`")
    lines.append("")
    lines.append("**Question this answers:** does min_score=50 still win on the silent-50-clean pipeline?")
    lines.append("")
    lines.append("## Cross-strategy leaderboard (best cell per strategy)")
    lines.append("")
    lines.append("| Strategy | Best mode | OOS Sharpe | OOS Ret% | Win% | n_oos | Δ Sharpe vs pre-clean |")
    lines.append("|---|---|---|---|---|---|---|")

    leaderboard: list[tuple[StrategySweep, CellResult, Optional[float]]] = []
    for s in new_sweeps:
        best = find_best_mode(s)
        base = base_sweeps.get(s.strategy)
        old_best_sharpe = find_best_mode(base).oos_sharpe if base else None
        leaderboard.append((s, best, old_best_sharpe))

    leaderboard.sort(key=lambda x: x[1].oos_sharpe, reverse=True)
    for s, best, old in leaderboard:
        delta_str = (
            f"{'+' if best.oos_sharpe - old >= 0 else ''}{best.oos_sharpe - old:.2f}"
            if old is not None else "new"
        )
        lines.append(
            f"| `{s.strategy}` | {best.mode}@{best.insider_weight:.2f} | "
            f"{best.oos_sharpe:.2f} | {best.oos_return_pct:.1f}% | "
            f"{best.win_rate_pct:.1f}% | {best.n_oos_trades} | {delta_str} |"
        )

    lines.append("")
    lines.append("## Per-strategy detail")
    for s in new_sweeps:
        base = base_sweeps.get(s.strategy)
        lines.append("")
        lines.append(f"### `{s.strategy}`")
        if base is None:
            lines.append("")
            lines.append("_No pre-clean baseline — strategy is new in this battery._")
        lines.append("")
        lines.append("| Cell | oos_sharpe | oos_ret% | win% | n_oos | max_dd% |")
        lines.append("|---|---|---|---|---|---|")
        base_by_key = base.by_key() if base else {}
        for c in s.cells:
            old = base_by_key.get(c.key())
            lines.append(
                f"| {c.mode}@{c.insider_weight:.2f} | "
                f"{fmt_delta(c.oos_sharpe, old.oos_sharpe if old else None)} | "
                f"{fmt_delta(c.oos_return_pct, old.oos_return_pct if old else None, units='%')} | "
                f"{fmt_delta(c.win_rate_pct, old.win_rate_pct if old else None, units='%', precision=1)} | "
                f"{fmt_delta(c.n_oos_trades, old.n_oos_trades if old else None, precision=0)} | "
                f"{fmt_delta(c.max_dd_pct, old.max_dd_pct if old else None, units='%', precision=1)} |"
            )

    return "\n".join(lines) + "\n"


def main() -> int:
    # Windows consoles default to cp1252 which can't render em-dashes / box-
    # drawing in script output. Force utf-8 so the output looks the same on
    # Windows + macOS + Linux. errors="replace" keeps the script from
    # crashing on a future surprising character.
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--new",
        type=Path,
        default=Path("data/sweep_battery_post_status"),
        help="Directory of post-clean-pipeline sweep results",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=Path("data/sweep_battery"),
        help="Directory of pre-clean sweep results for delta computation",
    )
    parser.add_argument(
        "--markdown",
        type=Path,
        help="If set, write a markdown summary here (otherwise console-only)",
    )
    args = parser.parse_args()

    if not args.new.exists():
        print(f"ERROR: --new directory does not exist: {args.new}")
        return 2

    # Pair new files with baselines by strategy name.
    new_files = sorted(
        p for p in args.new.glob("sweep_*.json")
        if not p.name.endswith(".full.json")
    )
    if not new_files:
        print(f"ERROR: no sweep JSON files found under {args.new}")
        return 2

    print(f"Found {len(new_files)} new sweep result(s) in {args.new}")
    if args.baseline.exists():
        print(f"Pre-clean baseline directory: {args.baseline}")
    else:
        print(f"No baseline directory at {args.baseline} — deltas will be 'new'")

    new_sweeps: list[StrategySweep] = []
    base_sweeps: dict[str, StrategySweep] = {}
    for new_path in new_files:
        sweep = load_sweep(new_path)
        if sweep is None:
            continue
        new_sweeps.append(sweep)
        base_path = args.baseline / new_path.name if args.baseline.exists() else None
        base = load_sweep(base_path) if base_path else None
        if base is not None:
            base_sweeps[sweep.strategy] = base
        print_strategy_table(sweep, base)

    # Cross-strategy leaderboard last, for the eye to land on after detail.
    print()
    print("=" * 60)
    print("Cross-strategy leaderboard (best cell per strategy, ranked by OOS Sharpe)")
    print("=" * 60)
    leaderboard = sorted(
        ((s, find_best_mode(s)) for s in new_sweeps),
        key=lambda x: x[1].oos_sharpe,
        reverse=True,
    )
    for s, best in leaderboard:
        base = base_sweeps.get(s.strategy)
        old_sharpe = find_best_mode(base).oos_sharpe if base else None
        delta = f" ({best.oos_sharpe - old_sharpe:+.2f} vs pre-clean)" if old_sharpe is not None else " (new)"
        print(
            f"  {s.strategy:<25} {best.mode}@{best.insider_weight:.2f}  "
            f"Sharpe={best.oos_sharpe:.2f}  Ret={best.oos_return_pct:.1f}%  "
            f"Win={best.win_rate_pct:.1f}%  n_oos={best.n_oos_trades}{delta}"
        )

    if args.markdown:
        md = build_markdown_summary(new_sweeps, base_sweeps)
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(md, encoding="utf-8")
        print()
        print(f"Markdown summary written: {args.markdown}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
