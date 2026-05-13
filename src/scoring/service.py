"""ScoringService — the typed entry point for the scoring pipeline.

Wraps the analyzer modules (src/scoring/analyzers/*) and the dict-returning
`calculate_composite_score` to expose a CompositeScore-returning API. New
callers (FastAPI in Phase 1, ML feature store in Phase 4) program against
this service; legacy callers (CLI through Phase 0) keep using the dict-
returning path until Stream B's later commits migrate them.

This is the "compute_*" half of the cmd_* split called out in the plan —
the half that produces data. Rendering (`render_*`) lives in
src/presentation/.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Callable, Optional

import pandas as pd

from src.contracts.entities.score import (
    CompositeScore,
    ConsensusDiagnostic,
    ScoreBreakdownRow,
)
from src.contracts.entities.signal import Signal
from src.scoring.analyzers import (
    alpha158,
    fundamental,
    insider_flow,
    patterns,
    pead as pead_module,
    relative_strength,
    statistical,
    technical,
    trend_detector,
)
from src.scoring.analyzers.insider_flow import InsiderFlowParams
from src.scoring.analyzers.trend_detector import analyze_stock_trend
from src.scoring.engine import batch_score, calculate_composite_score
from src.scoring.recommender import generate_recommendation
from src.scoring.sector_stats import compute_sector_stats

logger = logging.getLogger(__name__)


AnalyzeEvent = dict[str, Any]
AnalyzeEventCallback = Callable[[AnalyzeEvent], None]


def _dict_to_composite_score(ticker: str, result: dict[str, Any]) -> CompositeScore:
    """Lift the dict returned by calculate_composite_score into the typed
    CompositeScore entity. Field-for-field correspondence per the contract
    docstring (src/contracts/entities/score.py:CompositeScore)."""
    signals_raw = result.get("all_signals", []) or []
    signals = tuple(
        Signal(
            type=s.get("type", "neutral"),
            source=str(s.get("source", "")),
            detail=str(s.get("detail", "")),
        )
        for s in signals_raw
        # filter out malformed entries (defensive — analyzer signals should
        # always have a type; if they don't, the typed Signal would reject)
        if s.get("type") in ("bullish", "bearish", "neutral")
    )

    breakdown_raw = result.get("breakdown", []) or []
    breakdown = tuple(
        ScoreBreakdownRow(
            category=row.get("category", ""),
            score=float(row.get("score", 0)),
            weight=str(row.get("weight", "")),
            contribution=float(row.get("contribution", 0)),
        )
        for row in breakdown_raw
    )

    consensus_raw = result.get("consensus", {}) or {}
    consensus = (
        ConsensusDiagnostic(
            confidence=float(consensus_raw.get("confidence", 1.0)),
            sub_score_std=float(consensus_raw.get("sub_score_std", 0.0)),
        )
        if consensus_raw
        else None
    )

    return CompositeScore(
        ticker=ticker,
        composite_score=float(result.get("composite_score", 50.0)),
        sub_scores=dict(result.get("sub_scores", {}) or {}),
        all_signals=signals,
        bullish_signals=int(result.get("bullish_signals", 0)),
        bearish_signals=int(result.get("bearish_signals", 0)),
        breakdown=breakdown,
        consensus=consensus,
        atr=result.get("_atr"),
        close=result.get("_close"),
    )


def compute_composite_score(
    ticker: str,
    technical_result: dict,
    fundamental_result: dict,
    pattern_result: dict,
    statistical_result: dict,
    trend_result: dict,
    strategy_config: dict,
    *,
    alpha158_result: dict | None = None,
    pead_result: dict | None = None,
    rel_strength_result: dict | None = None,
) -> CompositeScore:
    """Typed wrapper around calculate_composite_score.

    Same inputs, same composite math (delegates to the dict-returning
    legacy function), but returns a CompositeScore. The dict path stays
    available via src.scoring.engine.calculate_composite_score for
    not-yet-migrated callers.
    """
    raw = calculate_composite_score(
        technical_result,
        fundamental_result,
        pattern_result,
        statistical_result,
        trend_result,
        strategy_config,
        alpha158_result=alpha158_result,
        pead_result=pead_result,
        rel_strength_result=rel_strength_result,
    )
    return _dict_to_composite_score(ticker, raw)


class ScoringService:
    """The compute half of the scoring pipeline.

    Accepts a price DataFrame + fundamentals dict + strategy config and
    returns a CompositeScore. Wraps every analyzer call, plus the optional
    Alpha158 / PEAD additions.

    Phase 0 keeps the existing analyzer signatures (df, config) since
    parity with the legacy CLI is the priority. Phase 1+ will refine the
    signatures to accept typed OHLCVSeries directly.
    """

    def __init__(self, config) -> None:
        self._config = config

    def score_ticker(
        self,
        ticker: str,
        df: pd.DataFrame,
        fundamentals: dict | None,
        strategy_config: dict,
        *,
        earnings_history: Optional[pd.DataFrame] = None,
        as_of_date: Any = None,
        benchmark_df: Optional[pd.DataFrame] = None,
        sector_stats: Optional[dict] = None,
    ) -> CompositeScore | None:
        """Run all analyzers + composite + typed lift. Returns None when
        the price DataFrame is too short for any analyzer to fire — caller
        treats this as a soft miss, not an error.

        ``benchmark_df`` (typically SPY) enables the relative-strength
        analyzer; None disables it. ``sector_stats`` enables sector-
        relative valuation scoring.
        """
        if df is None or df.empty:
            return None

        tech = technical.analyze(df, self._config)
        fund = fundamental.analyze(
            fundamentals or {}, self._config, sector_stats=sector_stats,
        )
        pat = patterns.analyze(df, self._config)
        stat = statistical.analyze(df, self._config)
        trnd = trend_detector.analyze_stock_trend(df, fundamentals or {}, self._config)
        a158 = alpha158.analyze(df, self._config) if len(df) >= 260 else None
        peadr = None
        if earnings_history is not None and not earnings_history.empty:
            peadr = pead_module.analyze(
                ticker, earnings_history, as_of_date=as_of_date
            )
        rs_result = (
            relative_strength.analyze(df, benchmark_df, self._config)
            if benchmark_df is not None else None
        )

        return compute_composite_score(
            ticker=ticker,
            technical_result=tech,
            fundamental_result=fund,
            pattern_result=pat,
            statistical_result=stat,
            trend_result=trnd,
            strategy_config=strategy_config,
            alpha158_result=a158,
            pead_result=peadr,
            rel_strength_result=rs_result,
        )


def analyze_and_score(
    price_data_map: dict[str, pd.DataFrame],
    fundamentals_map: dict[str, dict],
    config,
    strategy: dict,
    *,
    on_event: AnalyzeEventCallback | None = None,
    benchmark_df: pd.DataFrame | None = None,
    as_of: date | None = None,
) -> list[dict[str, Any]]:
    """Run all analyzers, composite-score every ticker, generate recommendations.

    Single source of truth for the scan pipeline's analyze pass — both the
    CLI (``src/cli/main.py:cmd_scan``) and the API scan runner call into
    here. Returns the legacy recommendation dict shape; Phase 4 will lift
    to typed ``Recommendation`` once every reader is migrated.

    ``on_event`` (if supplied) fires per ticker so the SSE endpoint can
    emit live progress:
      - ``analyze_ticker_start`` {ticker, i, n}
      - ``analyze_ticker_done``  {ticker, i, n}
      - ``analyze_ticker_failed`` {ticker, i, n, error}   on analyzer crash
      - ``score_start`` {n_analyzed}                       composite begins
      - ``recommend_start`` {n_scored}                     recommend begins

    Per-ticker emit lives here (not in the analyzers) because the analyzers
    are intentionally framework-free; progress reporting is a pipeline
    concern, not an analyzer concern.
    """
    emit = on_event or (lambda _event: None)

    # Pre-compute per-sector quantile stats once for the whole batch
    # so each fundamental.analyze call can score valuation metrics on
    # within-sector percentile when the cohort is large enough.
    sector_cfg = config.get_sector_relative_scoring() if hasattr(config, "get_sector_relative_scoring") else {}
    sector_stats = None
    if sector_cfg.get("enabled", False):
        sector_stats = compute_sector_stats(
            fundamentals_map,
            min_cohort=int(sector_cfg.get("min_cohort", 5)),
        )

    # Relative-strength benchmark: prefer the explicit arg, fall back
    # to SPY in the price_data_map if the caller happened to fetch it.
    bench_df = benchmark_df
    if bench_df is None:
        bench_df = price_data_map.get("SPY")

    # Insider-flow pre-pass: if enabled, bulk-load Postgres rows + run
    # the cluster analyzer + optionally enrich with the nearest 8-K
    # excerpt from filings_corpus. Done once for the whole universe
    # before the per-ticker analyzer loop so each ticker just looks up
    # its result. Empty dict when the feature is off (default) — the
    # composite engine treats absent insider_flow_result as "no
    # sub-score," same as alpha158/PEAD/rel_strength.
    flow_cfg = config.get_insider_flow() if hasattr(config, "get_insider_flow") else {}
    insider_results: dict[str, dict[str, Any]] = {}
    if flow_cfg.get("enabled", False):
        from src.scoring.insider_narrative import compute_insider_flow_results_sync
        try:
            insider_results = compute_insider_flow_results_sync(
                list(price_data_map.keys()),
                as_of=as_of or date.today(),
                lookback_days=int(flow_cfg.get("lookback_days", 60)),
                flow_params=InsiderFlowParams(
                    window_days=int(flow_cfg.get("window_days", 30)),
                    min_cluster_insiders=int(flow_cfg.get("min_cluster_insiders", 2)),
                ),
                enrich_narrative=bool(flow_cfg.get("enrich_narrative", False)),
            )
        except Exception as e:
            # Don't fail the whole scan if Postgres/pgvector is offline.
            # Insider flow is an additive signal; the rest of the
            # pipeline should still produce output.
            logger.warning("insider_flow pre-pass failed: %s", e)
            insider_results = {}

    # Catalyst pre-pass: bulk-load the most recent narrative snapshot
    # per ticker and run the catalyst analyzer. Same opt-in posture as
    # insider_flow — default off (the day-5 ML A/B only yielded
    # +0.0053 Pearson IC). When enabled, the analyzer's signal is the
    # human-readable catalyst label that the recommender can carry into
    # its rationale.
    catalyst_cfg = (
        config.get_catalyst() if hasattr(config, "get_catalyst") else {}
    )
    catalyst_results: dict[str, dict[str, Any]] = {}
    if catalyst_cfg.get("enabled", False):
        from src.scoring.insider_narrative import compute_catalyst_results_sync
        try:
            catalyst_results = compute_catalyst_results_sync(
                list(price_data_map.keys()),
                as_of=as_of or date.today(),
                max_age_days=int(catalyst_cfg.get("max_age_days", 60)),
                min_sim=float(catalyst_cfg.get("min_sim", 0.30)),
            )
        except Exception as e:
            logger.warning("catalyst pre-pass failed: %s", e)
            catalyst_results = {}

    analysis_results: dict[str, dict[str, Any]] = {}
    total = len(price_data_map)

    for i, (ticker, df) in enumerate(price_data_map.items(), 1):
        emit({"stage": "analyze_ticker_start", "ticker": ticker, "i": i, "n": total})
        fund = fundamentals_map.get(ticker, {})

        try:
            analysis_results[ticker] = {
                "technical": technical.analyze(df, config),
                "alpha158": alpha158.analyze(df, config),
                "fundamental": fundamental.analyze(fund, config, sector_stats=sector_stats),
                "pattern": patterns.analyze(df, config),
                "statistical": statistical.analyze(df, config),
                "trend": analyze_stock_trend(df, fund, config),
                "rel_strength": (
                    relative_strength.analyze(df, bench_df, config)
                    if bench_df is not None else None
                ),
                "insider_flow": insider_results.get(ticker.upper()),
                "catalyst": catalyst_results.get(ticker.upper()),
            }
            emit(
                {"stage": "analyze_ticker_done", "ticker": ticker, "i": i, "n": total}
            )
        except Exception as e:
            logger.error("Error analyzing %s: %s", ticker, e)
            emit(
                {
                    "stage": "analyze_ticker_failed",
                    "ticker": ticker,
                    "i": i,
                    "n": total,
                    "error": str(e),
                }
            )

    emit({"stage": "score_start", "n_analyzed": len(analysis_results)})
    scored = batch_score(analysis_results, strategy)

    emit({"stage": "recommend_start", "n_scored": len(scored)})
    recommendations: list[dict[str, Any]] = []
    for ticker, score_result in scored:
        rec = generate_recommendation(
            ticker,
            score_result,
            price_data_map.get(ticker),
            fundamentals_map.get(ticker),
            config,
            strategy=strategy,
        )
        recommendations.append(rec)

    return recommendations
