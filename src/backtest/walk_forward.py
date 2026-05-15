"""Walk-forward cross-validation report.

Review item #5. The existing engine.py:961 splits the backtest window
into a single train/test pair at ``oos_split_pct`` of the way through.
A single holdout produces ONE Sharpe estimate with no fold variance —
a strategy that earned its Sharpe entirely in fold-3 looks identical
to one that earned it evenly. Operators have no way to tell the
difference, and the headline number is statistically thin.

This module produces an N-fold rolling-window report on top of the
existing single pass. We don't re-run the strategy per fold (the engine
applies rules, not a trained model — no per-fold retraining needed).
Instead we slice the closed-trade timeline into N contiguous folds by
``entry_date``, compute per-fold Sharpe / return / max-DD, and report
the variance.

Acceptance gate (surfaced as ``walk_forward.passes_min_fold_gate``):
all folds must have Sharpe > 0 AND mean fold Sharpe > minimum_mean.
The operator can then read this single boolean instead of staring at
five numbers and guessing.
"""

from __future__ import annotations

import math
import logging
from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# Minimum trades per fold below which the per-fold Sharpe number is
# noise and the fold is reported as "insufficient" rather than included
# in the pass/fail gate.
_MIN_TRADES_PER_FOLD = 5


@dataclass(frozen=True)
class FoldMetrics:
    """One fold's headline metrics. ``status`` differentiates the
    "passed" case from "too few trades" so the operator doesn't read a
    Sharpe of 0.0 as a real result on a 1-trade fold."""

    fold_index: int
    """0-based fold number — fold 0 is the earliest."""

    start_date: str
    end_date: str
    n_trades: int

    status: str  # "ok" | "insufficient_trades"
    total_return_pct: float | None
    ann_sharpe: float | None
    max_drawdown_pct: float | None

    def to_dict(self) -> dict:
        return {
            "fold_index": self.fold_index,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "n_trades": self.n_trades,
            "status": self.status,
            "total_return_pct": self.total_return_pct,
            "ann_sharpe": self.ann_sharpe,
            "max_drawdown_pct": self.max_drawdown_pct,
        }


def _split_window_into_folds(
    start: pd.Timestamp,
    end: pd.Timestamp,
    n_folds: int,
) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Divide ``[start, end]`` into ``n_folds`` contiguous halves.

    Boundaries land on the linear interpolation of the window — same
    semantics as the engine's single-split ``start + (end - start) * f``
    so the math is auditable. Each fold's range is half-open:
    ``[fold_start, fold_end)``, except the last which is closed on both
    sides so we don't drop trades exactly on ``end``.
    """
    if n_folds < 2:
        raise ValueError(f"n_folds must be >= 2 (got {n_folds})")
    total = end - start
    out: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for i in range(n_folds):
        fold_start = start + total * (i / n_folds)
        fold_end = start + total * ((i + 1) / n_folds)
        out.append((fold_start, fold_end))
    return out


def _fold_equity_curve_stats(
    equity_curve: Sequence[dict],
    fold_start: pd.Timestamp,
    fold_end: pd.Timestamp,
    *,
    is_last_fold: bool,
) -> dict:
    """Compute Sharpe + drawdown for a fold-restricted equity curve.

    Annualizer mirrors ``equity_curve_stats`` from metrics.py: empirical
    ``periods_per_year`` derived from elapsed days, ``sqrt`` factor.

    Caller carries the responsibility of slicing the curve to the fold
    range — we just compute. Half-open semantics for non-final folds
    (``< fold_end``); closed for the last fold so the final equity sample
    is included.
    """
    slice_curve = [
        e for e in equity_curve
        if (
            pd.Timestamp(e["date"]) >= fold_start
            and (
                pd.Timestamp(e["date"]) < fold_end
                if not is_last_fold
                else pd.Timestamp(e["date"]) <= fold_end
            )
        )
    ]
    if len(slice_curve) < 2:
        return {
            "total_return_pct": None,
            "ann_sharpe": None,
            "max_drawdown_pct": None,
        }
    equities = np.array([e["equity"] for e in slice_curve], dtype=float)
    weekly_returns = equities[1:] / equities[:-1] - 1
    weekly_returns = weekly_returns[np.isfinite(weekly_returns)]

    running_max = np.maximum.accumulate(equities)
    drawdown = equities / running_max - 1
    max_dd = float(drawdown.min()) if len(drawdown) else 0.0

    if len(weekly_returns) == 0:
        return {
            "total_return_pct": None,
            "ann_sharpe": None,
            "max_drawdown_pct": round(max_dd * 100, 2),
        }

    mean_w = float(weekly_returns.mean())
    std_w = float(weekly_returns.std(ddof=1)) if len(weekly_returns) > 1 else 0.0
    first_date = pd.Timestamp(slice_curve[0]["date"])
    last_date = pd.Timestamp(slice_curve[-1]["date"])
    elapsed_days = max(1, (last_date - first_date).days)
    years_elapsed = elapsed_days / 365.25
    periods_per_year = (
        len(weekly_returns) / years_elapsed if years_elapsed > 0 else 52.0
    )
    ann_factor = math.sqrt(periods_per_year)
    ann_sharpe = (mean_w / std_w) * ann_factor if std_w > 0 else 0.0

    total_return = float(equities[-1] / equities[0] - 1)

    return {
        "total_return_pct": round(total_return * 100, 2),
        "ann_sharpe": round(ann_sharpe, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
    }


def compute_walk_forward_report(
    closed_trades: Iterable,
    equity_curve: Sequence[dict],
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    n_folds: int,
    min_mean_sharpe: float = 0.5,
) -> dict:
    """Build the full walk-forward report.

    Returns a dict with:
      * ``n_folds``: number of folds attempted
      * ``folds``: list of per-fold dicts (see ``FoldMetrics.to_dict``)
      * ``mean_sharpe`` / ``min_sharpe`` / ``max_sharpe``: aggregates
        across ``status=="ok"`` folds only
      * ``passes_min_fold_gate``: True iff every "ok" fold has
        ann_sharpe > 0 AND mean_sharpe >= ``min_mean_sharpe``.
        Any fold with ``status=="insufficient_trades"`` is treated as
        "unknown" and DOES NOT pass the gate (operators want a strict
        signal — sparse evidence is failing evidence).

    The gate is intentionally strict: review item #7 lists "all folds > 0"
    as an acceptance criterion before risking capital. Treating an
    insufficient-evidence fold as "fine" undermines that.
    """
    trades = list(closed_trades)
    folds_range = _split_window_into_folds(start, end, n_folds)
    folds: list[FoldMetrics] = []

    for i, (fold_start, fold_end) in enumerate(folds_range):
        is_last = i == n_folds - 1
        fold_trades = [
            t for t in trades
            if (
                pd.Timestamp(t.entry_date) >= fold_start
                and (
                    pd.Timestamp(t.entry_date) < fold_end
                    if not is_last
                    else pd.Timestamp(t.entry_date) <= fold_end
                )
            )
        ]

        if len(fold_trades) < _MIN_TRADES_PER_FOLD:
            folds.append(FoldMetrics(
                fold_index=i,
                start_date=fold_start.strftime("%Y-%m-%d"),
                end_date=fold_end.strftime("%Y-%m-%d"),
                n_trades=len(fold_trades),
                status="insufficient_trades",
                total_return_pct=None,
                ann_sharpe=None,
                max_drawdown_pct=None,
            ))
            continue

        stats = _fold_equity_curve_stats(
            equity_curve, fold_start, fold_end, is_last_fold=is_last,
        )
        folds.append(FoldMetrics(
            fold_index=i,
            start_date=fold_start.strftime("%Y-%m-%d"),
            end_date=fold_end.strftime("%Y-%m-%d"),
            n_trades=len(fold_trades),
            status="ok",
            total_return_pct=stats["total_return_pct"],
            ann_sharpe=stats["ann_sharpe"],
            max_drawdown_pct=stats["max_drawdown_pct"],
        ))

    ok_folds = [f for f in folds if f.status == "ok" and f.ann_sharpe is not None]
    insufficient_folds = [f for f in folds if f.status != "ok"]

    if not ok_folds:
        # No folds had enough trades — the report exists but the gate
        # can't pass. This is itself a signal: the strategy doesn't trade
        # densely enough for walk-forward CV at this fold count.
        return {
            "n_folds": n_folds,
            "folds": [f.to_dict() for f in folds],
            "mean_sharpe": None,
            "min_sharpe": None,
            "max_sharpe": None,
            "min_mean_sharpe_threshold": min_mean_sharpe,
            "passes_min_fold_gate": False,
            "gate_reason": (
                f"no folds had >= {_MIN_TRADES_PER_FOLD} trades "
                f"(min trades required per fold). Strategy trades too "
                f"sparsely for {n_folds}-fold walk-forward."
            ),
        }

    sharpes = [f.ann_sharpe for f in ok_folds]
    mean_s = float(np.mean(sharpes))
    min_s = float(np.min(sharpes))
    max_s = float(np.max(sharpes))

    # Gate: every "ok" fold must be positive AND mean must clear the
    # threshold AND no fold is insufficient. Each failure surfaces its
    # own reason so the operator sees exactly why the gate failed.
    gate_reasons: list[str] = []
    if insufficient_folds:
        gate_reasons.append(
            f"{len(insufficient_folds)} fold(s) had fewer than "
            f"{_MIN_TRADES_PER_FOLD} trades — coverage too sparse"
        )
    if min_s <= 0:
        gate_reasons.append(
            f"min fold Sharpe {min_s:.2f} <= 0 — at least one fold lost money"
        )
    if mean_s < min_mean_sharpe:
        gate_reasons.append(
            f"mean fold Sharpe {mean_s:.2f} < threshold {min_mean_sharpe:.2f}"
        )
    passes = not gate_reasons

    return {
        "n_folds": n_folds,
        "folds": [f.to_dict() for f in folds],
        "mean_sharpe": round(mean_s, 2),
        "min_sharpe": round(min_s, 2),
        "max_sharpe": round(max_s, 2),
        "min_mean_sharpe_threshold": min_mean_sharpe,
        "passes_min_fold_gate": passes,
        "gate_reason": "; ".join(gate_reasons) if gate_reasons else None,
    }
