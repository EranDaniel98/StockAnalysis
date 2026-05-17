"""Train a LightGBM composite as a replacement for the hand-tuned weighted sum.

Audit-driven Week-2 work: the current composite is a linear-weighted
average of 5-7 analyzer sub-scores. That can't capture interactions
("high momentum AND weak quality is a sell"). A LightGBM regressor over
the same features captures interactions for free.

This script:
  1. Reads a score panel (built by scripts/analyzer_ic_report.py with
     --panel-cache) — long-form: date, ticker, composite, technical,
     fundamental, statistical, pattern, trend, alpha158.
  2. Joins with forward returns at a configurable horizon (default 21
     trading days = ~one month).
  3. Time-series-cross-validates a LightGBM regressor predicting the
     forward return from the sub-score features.
  4. Writes a comparison report: per-fold IC + IR for the trained model
     vs the linear composite as control, plus the top-bottom spread.
  5. Persists the final model trained on the full panel for later
     inference at scan time.

The goal is NOT to beat random with the trained model — it's to beat
the LINEAR COMPOSITE on the same data. Anything less means the
problem is the features, not the composition.

Usage
-----
    uv run python -m scripts.train_ml_composite \\
        --panel data/ic_panel_2022_2024.csv \\
        --price-data data/price_matrix.parquet \\
        --horizon 21 \\
        --output reports/ml_composite_v1.md
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.model_selection import TimeSeriesSplit

from src.config_loader import Config
from src.data.cache import DataCache
from src.data.fetcher import DataFetcher
from src.research.diagnostic_service import build_price_matrix

logger = logging.getLogger("train_ml_composite")

# Match the analyzer-IC report's feature set so the comparison is fair.
FEATURE_COLUMNS = (
    "technical",
    "fundamental",
    "statistical",
    "pattern",
    "trend",
    "alpha158",
)
TARGET_LINEAR_BASELINE = "composite"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--panel", required=True,
        help="Path to the score panel CSV "
             "(built by analyzer_ic_report.py --panel-cache).",
    )
    p.add_argument(
        "--horizon", type=int, default=21,
        help="Forward-return horizon in trading days. Default 21 "
             "(~1 month — matches existing swing strategies).",
    )
    p.add_argument(
        "--n-splits", type=int, default=5,
        help="TimeSeriesSplit folds. Default 5.",
    )
    p.add_argument(
        "--output", default="reports/ml_composite_v1.md",
        help="Markdown report path.",
    )
    p.add_argument(
        "--model-output", default="data/models/ml_composite_v1.lgb",
        help="Trained model file path (LightGBM native format).",
    )
    p.add_argument(
        "--universe", default="russell_1000",
        choices=("russell_1000",),
        help="Universe used to build the panel. Drives price-matrix fetch.",
    )
    p.add_argument(
        "--start", default="2022-05-13",
        help="Panel start (must match panel cache).",
    )
    p.add_argument(
        "--end", default="2024-05-13",
        help="Panel end (must match panel cache).",
    )
    return p.parse_args()


def _load_panel(path: Path) -> pd.DataFrame:
    """Load + sanity-check the panel CSV."""
    df = pd.read_csv(path, parse_dates=["date"])
    required = {"date", "ticker", "composite", *FEATURE_COLUMNS}
    missing = required - set(df.columns)
    if missing:
        # 'pattern' is sometimes absent — the patterns analyzer doesn't
        # always produce a sub-score. Treat it as zero rather than failing.
        if missing == {"pattern"}:
            logger.warning(
                "Panel missing 'pattern' column; treating as zero throughout.",
            )
            df["pattern"] = 0.0
            missing.clear()
        else:
            raise ValueError(f"panel missing required columns: {missing}")
    return df


def _compute_forward_returns(
    prices: pd.DataFrame, horizon: int,
) -> pd.DataFrame:
    """Forward-return frame: (date, ticker) → forward return at horizon.

    Aligned to the panel's rebalance dates: for each date in the price
    matrix, the forward return is close(date + horizon) / close(date) - 1.
    """
    fwd = prices.shift(-horizon) / prices - 1.0
    # Long-form: stack tickers into one column.
    long = fwd.stack(future_stack=True).reset_index()
    long.columns = ["date", "ticker", f"fwd_return_{horizon}d"]
    return long


def _ic(predictions: np.ndarray, actuals: np.ndarray) -> float:
    """Spearman rank IC. nan-safe."""
    mask = np.isfinite(predictions) & np.isfinite(actuals)
    if mask.sum() < 10:
        return 0.0
    rho, _ = spearmanr(predictions[mask], actuals[mask])
    return float(rho) if np.isfinite(rho) else 0.0


def _quantile_spread(
    predictions: np.ndarray, actuals: np.ndarray, q: int = 5,
) -> float:
    """Top-quintile mean return minus bottom-quintile mean return, in pct."""
    mask = np.isfinite(predictions) & np.isfinite(actuals)
    if mask.sum() < q * 2:
        return 0.0
    preds = predictions[mask]
    rets = actuals[mask]
    quantile_bounds = np.quantile(preds, np.linspace(0, 1, q + 1))
    if quantile_bounds[0] == quantile_bounds[-1]:
        return 0.0
    bins = np.clip(
        np.digitize(preds, quantile_bounds[1:-1], right=False),
        0, q - 1,
    )
    top = rets[bins == q - 1]
    bot = rets[bins == 0]
    if len(top) == 0 or len(bot) == 0:
        return 0.0
    return float((top.mean() - bot.mean()) * 100.0)


def _fit_lightgbm(
    X_train: pd.DataFrame, y_train: pd.Series,
) -> lgb.LGBMRegressor:
    """Train a LightGBM regressor with conservative defaults — at this
    sample size aggressive defaults overfit. Settings chosen for shallow
    interaction capture, not deep memorization."""
    model = lgb.LGBMRegressor(
        n_estimators=200,
        learning_rate=0.03,
        max_depth=4,            # shallow — we want interactions, not memorization
        num_leaves=15,
        min_child_samples=200,  # generous — anti-overfit
        reg_alpha=0.1,
        reg_lambda=0.1,
        feature_fraction=0.9,
        bagging_fraction=0.8,
        bagging_freq=5,
        random_state=42,
        n_jobs=-1,
        verbose=-1,
    )
    model.fit(X_train, y_train)
    return model


def _cross_validate(
    panel: pd.DataFrame, horizon: int, n_splits: int,
) -> dict:
    """TimeSeriesSplit CV. For each fold, train on past, evaluate on
    future. Compare LightGBM IC vs linear-composite IC on the test
    fold so the comparison is on the same out-of-sample bars."""
    panel = panel.sort_values("date").reset_index(drop=True)
    unique_dates = panel["date"].drop_duplicates().sort_values().reset_index(drop=True)
    tscv = TimeSeriesSplit(n_splits=n_splits)

    fold_results: list[dict] = []
    feature_importance_acc: dict[str, float] = {f: 0.0 for f in FEATURE_COLUMNS}

    for fold_idx, (train_date_idx, test_date_idx) in enumerate(tscv.split(unique_dates)):
        train_dates = set(unique_dates.iloc[train_date_idx].tolist())
        test_dates = set(unique_dates.iloc[test_date_idx].tolist())
        train = panel[panel["date"].isin(train_dates)].dropna(
            subset=[*FEATURE_COLUMNS, f"fwd_return_{horizon}d"]
        )
        test = panel[panel["date"].isin(test_dates)].dropna(
            subset=[*FEATURE_COLUMNS, f"fwd_return_{horizon}d"]
        )
        if len(train) < 1000 or len(test) < 200:
            logger.warning(
                "Fold %d: train=%d, test=%d — skipping (insufficient data).",
                fold_idx, len(train), len(test),
            )
            continue

        X_train = train[list(FEATURE_COLUMNS)]
        y_train = train[f"fwd_return_{horizon}d"]
        X_test = test[list(FEATURE_COLUMNS)]
        y_test = test[f"fwd_return_{horizon}d"].values

        model = _fit_lightgbm(X_train, y_train)
        preds_ml = model.predict(X_test)
        preds_linear = test[TARGET_LINEAR_BASELINE].values

        ic_ml = _ic(preds_ml, y_test)
        ic_linear = _ic(preds_linear, y_test)
        spread_ml = _quantile_spread(preds_ml, y_test)
        spread_linear = _quantile_spread(preds_linear, y_test)

        # Accumulate normalized feature importance.
        importances = model.feature_importances_
        total = importances.sum()
        if total > 0:
            for feat, imp in zip(FEATURE_COLUMNS, importances):
                feature_importance_acc[feat] += float(imp) / total / n_splits

        fold_results.append({
            "fold": fold_idx,
            "train_n": int(len(train)),
            "test_n": int(len(test)),
            "train_start": str(train["date"].min().date()),
            "train_end": str(train["date"].max().date()),
            "test_start": str(test["date"].min().date()),
            "test_end": str(test["date"].max().date()),
            "ic_ml": ic_ml,
            "ic_linear": ic_linear,
            "ic_lift_ratio": (ic_ml / ic_linear) if ic_linear != 0 else float("nan"),
            "spread_ml_pct": spread_ml,
            "spread_linear_pct": spread_linear,
        })

    if not fold_results:
        return {"folds": [], "feature_importance": {}, "summary": {}}

    # Aggregate metrics.
    summary = {
        "mean_ic_ml": float(np.mean([f["ic_ml"] for f in fold_results])),
        "mean_ic_linear": float(np.mean([f["ic_linear"] for f in fold_results])),
        "mean_spread_ml": float(np.mean([f["spread_ml_pct"] for f in fold_results])),
        "mean_spread_linear": float(np.mean([f["spread_linear_pct"] for f in fold_results])),
        "ir_ml": (
            float(np.mean([f["ic_ml"] for f in fold_results]))
            / max(float(np.std([f["ic_ml"] for f in fold_results])), 1e-9)
        ),
        "ir_linear": (
            float(np.mean([f["ic_linear"] for f in fold_results]))
            / max(float(np.std([f["ic_linear"] for f in fold_results])), 1e-9)
        ),
    }
    summary["ic_lift_pct"] = (
        (summary["mean_ic_ml"] / summary["mean_ic_linear"] - 1.0) * 100.0
        if summary["mean_ic_linear"] > 0
        else float("nan")
    )

    return {
        "folds": fold_results,
        "feature_importance": feature_importance_acc,
        "summary": summary,
    }


def _verdict(cv: dict) -> str:
    """Decide whether the LightGBM beats the linear composite enough to
    justify production wiring. Per the audit plan: need ≥30% IC lift to
    consider 'real'. Lower than that means the problem is the features."""
    summary = cv.get("summary", {})
    mean_ml = summary.get("mean_ic_ml", 0.0)
    mean_linear = summary.get("mean_ic_linear", 0.0)
    if mean_linear <= 0:
        return "❓ INDETERMINATE — linear baseline has no positive IC; check feature pipeline"
    lift = mean_ml / mean_linear
    if mean_ml < 0:
        return "❌ FAIL — LightGBM mean IC is negative; do not ship"
    if lift >= 1.3:
        return f"✅ SHIP — LightGBM mean IC {mean_ml:+.4f} vs linear {mean_linear:+.4f} ({lift:.2f}× lift)"
    if lift >= 1.1:
        return f"⚠️  MARGINAL — {lift:.2f}× lift; below the 1.3× audit threshold"
    return f"❌ FAIL — lift {lift:.2f}× below 1.3×; problem is the features, not the model"


def _emit_markdown(
    *,
    output_path: Path,
    cv: dict,
    panel_rows: int,
    horizon: int,
    n_splits: int,
    window: dict,
    universe: str,
    ran_at: str,
) -> None:
    lines: list[str] = [
        "# ML Composite (LightGBM) — head-to-head vs linear",
        "",
        f"Generated {ran_at}.",
        "",
        f"- Window: {window['start']} → {window['end']}",
        f"- Universe: `{universe}`",
        f"- Forward horizon: {horizon} trading days",
        f"- CV: {n_splits}-fold TimeSeriesSplit",
        f"- Panel rows (after dropna): {panel_rows:,}",
        "",
        "## Verdict",
        "",
        _verdict(cv),
        "",
        "## Summary",
        "",
    ]
    summary = cv.get("summary", {})
    if summary:
        lines.extend([
            f"- Mean IC (LightGBM): {summary.get('mean_ic_ml', 0):+.4f}",
            f"- Mean IC (linear):   {summary.get('mean_ic_linear', 0):+.4f}",
            f"- IC lift:            {summary.get('ic_lift_pct', float('nan')):+.1f}%",
            f"- IR (LightGBM):      {summary.get('ir_ml', 0):+.2f}",
            f"- IR (linear):        {summary.get('ir_linear', 0):+.2f}",
            f"- Mean top-bot spread (LightGBM): {summary.get('mean_spread_ml', 0):+.3f}%",
            f"- Mean top-bot spread (linear):   {summary.get('mean_spread_linear', 0):+.3f}%",
        ])
    lines.append("")

    lines.append("## Per-fold")
    lines.append("")
    lines.append("| Fold | Train window | Test window | IC (ML) | IC (linear) | Lift | Spread ML% | Spread Lin% |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for f in cv.get("folds", []):
        lift = f.get("ic_lift_ratio", float("nan"))
        lift_str = f"{lift:.2f}×" if np.isfinite(lift) else "n/a"
        lines.append(
            f"| {f['fold']} | {f['train_start']}→{f['train_end']} | "
            f"{f['test_start']}→{f['test_end']} | "
            f"{f['ic_ml']:+.4f} | {f['ic_linear']:+.4f} | {lift_str} | "
            f"{f['spread_ml_pct']:+.3f} | {f['spread_linear_pct']:+.3f} |"
        )
    lines.append("")

    lines.append("## Feature importance (LightGBM, mean across folds)")
    lines.append("")
    lines.append("| Feature | Mean importance |")
    lines.append("|---|---|")
    feat_imp = cv.get("feature_importance", {})
    for feat, imp in sorted(feat_imp.items(), key=lambda x: -x[1]):
        lines.append(f"| {feat} | {imp:.3f} |")
    lines.append("")

    lines.append("## Notes")
    lines.append("")
    lines.extend([
        "- LightGBM hyperparameters are intentionally conservative "
        "(max_depth=4, num_leaves=15, min_child_samples=200). At this "
        "panel size aggressive tuning overfits; the goal is interaction "
        "capture, not memorization.",
        "- The verdict threshold (1.3× lift over linear) comes from the "
        "audit's edge-thickening plan: anything less means the problem "
        "is the features, not the model. Adding more sophisticated ML "
        "won't help — gather better features first.",
        "- This is OUT-of-sample IC. The TimeSeriesSplit prevents look-",
        "ahead leakage by always training on past and evaluating on "
        "future bars.",
    ])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    panel_path = Path(args.panel)
    if not panel_path.exists():
        logger.error(
            "Panel cache %s does not exist. Build it first with:\n"
            "  uv run python -m scripts.analyzer_ic_report "
            "--panel-cache %s ...",
            panel_path, panel_path,
        )
        return 2

    panel = _load_panel(panel_path)
    logger.info("Loaded panel: %d rows", len(panel))

    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end)

    # Fetch the price matrix to compute forward returns. The IC report
    # has its own price-matrix path; reuse the same fetcher so the
    # cache hits.
    config = Config()
    cache = DataCache(
        expiry_hours=config.get("data", "cache_expiry_hours", default=24),
        market_hours_expiry_minutes=config.get(
            "data", "market_hours_cache_minutes", default=5,
        ),
    )
    fetcher = DataFetcher(config, cache)
    tickers = sorted(panel["ticker"].unique().tolist())
    logger.info("Fetching price history for %d tickers...", len(tickers))
    price_data = fetcher.fetch_batch(tickers)
    runway = max(45, int(args.horizon * 2 + 14))
    prices = build_price_matrix(
        price_data, start, end + pd.Timedelta(days=runway),
    )
    if prices.empty:
        logger.error("Empty price matrix — aborting.")
        return 3

    fwd = _compute_forward_returns(prices, args.horizon)
    panel = panel.merge(fwd, on=["date", "ticker"], how="left")
    pre_drop = len(panel)
    panel = panel.dropna(subset=[f"fwd_return_{args.horizon}d"])
    logger.info(
        "Joined forward returns: %d → %d rows after dropna",
        pre_drop, len(panel),
    )

    logger.info("Running %d-fold time-series CV...", args.n_splits)
    cv = _cross_validate(panel, args.horizon, args.n_splits)

    # Train final model on the full panel for inference at scan time.
    X_full = panel[list(FEATURE_COLUMNS)]
    y_full = panel[f"fwd_return_{args.horizon}d"]
    final_model = _fit_lightgbm(X_full, y_full)
    Path(args.model_output).parent.mkdir(parents=True, exist_ok=True)
    final_model.booster_.save_model(args.model_output)
    logger.info("Saved final model to %s", args.model_output)

    ran_at = datetime.now(timezone.utc).isoformat()
    out_md = Path(args.output)
    _emit_markdown(
        output_path=out_md,
        cv=cv,
        panel_rows=len(panel),
        horizon=args.horizon,
        n_splits=args.n_splits,
        window={"start": str(start.date()), "end": str(end.date())},
        universe=args.universe,
        ran_at=ran_at,
    )

    out_json = out_md.with_suffix(".json")
    payload = {
        "ran_at": ran_at,
        "universe": args.universe,
        "horizon": args.horizon,
        "n_splits": args.n_splits,
        "panel_rows": int(len(panel)),
        "window": {"start": str(start.date()), "end": str(end.date())},
        "cv": cv,
        "model_path": args.model_output,
    }
    out_json.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    logger.info("Wrote %s + %s", out_md, out_json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
