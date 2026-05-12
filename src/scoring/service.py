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
    patterns,
    pead as pead_module,
    statistical,
    technical,
    trend_detector,
)
from src.scoring.analyzers.trend_detector import analyze_stock_trend
from src.scoring.engine import batch_score, calculate_composite_score
from src.scoring.recommender import generate_recommendation

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
    ) -> CompositeScore | None:
        """Run all analyzers + composite + typed lift. Returns None when
        the price DataFrame is too short for any analyzer to fire — caller
        treats this as a soft miss, not an error.
        """
        if df is None or df.empty:
            return None

        tech = technical.analyze(df, self._config)
        fund = fundamental.analyze(fundamentals or {}, self._config)
        pat = patterns.analyze(df, self._config)
        stat = statistical.analyze(df, self._config)
        trnd = trend_detector.analyze_stock_trend(df, fundamentals or {}, self._config)
        a158 = alpha158.analyze(df, self._config) if len(df) >= 260 else None
        peadr = None
        if earnings_history is not None and not earnings_history.empty:
            peadr = pead_module.analyze(
                ticker, earnings_history, as_of_date=as_of_date
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
        )


def analyze_and_score(
    price_data_map: dict[str, pd.DataFrame],
    fundamentals_map: dict[str, dict],
    config,
    strategy: dict,
    *,
    on_event: AnalyzeEventCallback | None = None,
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

    analysis_results: dict[str, dict[str, Any]] = {}
    total = len(price_data_map)

    for i, (ticker, df) in enumerate(price_data_map.items(), 1):
        emit({"stage": "analyze_ticker_start", "ticker": ticker, "i": i, "n": total})
        fund = fundamentals_map.get(ticker, {})

        try:
            analysis_results[ticker] = {
                "technical": technical.analyze(df, config),
                "alpha158": alpha158.analyze(df, config),
                "fundamental": fundamental.analyze(fund, config),
                "pattern": patterns.analyze(df, config),
                "statistical": statistical.analyze(df, config),
                "trend": analyze_stock_trend(df, fund, config),
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
