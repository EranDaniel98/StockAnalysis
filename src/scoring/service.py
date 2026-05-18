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
            score=(
                float(row["score"])
                if row.get("score") is not None
                else None
            ),
            weight=str(row.get("weight", "")),
            contribution=float(row.get("contribution", 0)),
            status=str(row.get("status", "ok")),
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
        analyzer_status=dict(result.get("analyzer_status", {}) or {}),
        error_count=int(result.get("error_count", 0)),
        error_slots=tuple(result.get("error_slots", []) or []),
        score_valid=bool(result.get("score_valid", True)),
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


def _compute_sector_stats_if_enabled(config, fundamentals_map: dict[str, dict]):
    """Per-sector quantile stats for within-sector valuation scoring.

    Returns None when sector-relative scoring is disabled in config (the
    fundamental analyzer falls back to absolute percentiles).
    """
    sector_cfg = (
        config.get_sector_relative_scoring()
        if hasattr(config, "get_sector_relative_scoring")
        else {}
    )
    if not sector_cfg.get("enabled", False):
        return None
    return compute_sector_stats(
        fundamentals_map,
        min_cohort=int(sector_cfg.get("min_cohort", 5)),
    )


def _resolve_benchmark(
    explicit: pd.DataFrame | None,
    price_data_map: dict[str, pd.DataFrame],
) -> pd.DataFrame | None:
    """Prefer the explicit kwarg; fall back to SPY if the price map has it."""
    if explicit is not None:
        return explicit
    return price_data_map.get("SPY")


def _prepass_insider_flow(
    config,
    tickers: list[str],
    as_of: date | None,
) -> dict[str, dict[str, Any]]:
    """Bulk-load Postgres insider rows + run the cluster analyzer + (optionally)
    enrich with the nearest 8-K excerpt. Empty dict when feature is off or
    when Postgres/pgvector is unreachable — insider flow is an additive
    signal; the rest of the pipeline still produces output."""
    cfg = (
        config.get_insider_flow() if hasattr(config, "get_insider_flow") else {}
    )
    if not cfg.get("enabled", False):
        return {}
    from src.scoring.insider_narrative import compute_insider_flow_results_sync
    try:
        return compute_insider_flow_results_sync(
            tickers,
            as_of=as_of or date.today(),
            lookback_days=int(cfg.get("lookback_days", 60)),
            flow_params=InsiderFlowParams(
                window_days=int(cfg.get("window_days", 30)),
                min_cluster_insiders=int(cfg.get("min_cluster_insiders", 2)),
            ),
            enrich_narrative=bool(cfg.get("enrich_narrative", False)),
        )
    except Exception as e:
        logger.warning("insider_flow pre-pass failed: %s", e)
        return {}


def _prepass_catalyst(
    config,
    tickers: list[str],
    as_of: date | None,
) -> dict[str, dict[str, Any]]:
    """Catalyst analyzer pre-pass — bulk-load most recent narrative snapshots,
    label catalysts above the similarity threshold. Default off (the
    day-5 ML A/B only yielded +0.0053 Pearson IC)."""
    cfg = (
        config.get_catalyst() if hasattr(config, "get_catalyst") else {}
    )
    if not cfg.get("enabled", False):
        return {}
    from src.scoring.insider_narrative import compute_catalyst_results_sync
    try:
        return compute_catalyst_results_sync(
            tickers,
            as_of=as_of or date.today(),
            max_age_days=int(cfg.get("max_age_days", 60)),
            min_sim=float(cfg.get("min_sim", 0.30)),
        )
    except Exception as e:
        logger.warning("catalyst pre-pass failed: %s", e)
        return {}


def _prepass_analyst_revisions(
    analyst_revisions_data: dict[str, list] | None,
    as_of: date | None,
) -> dict[str, dict[str, Any]]:
    """LIVE-ONLY analyzer pre-pass — caller supplies analyst revision rows
    (typically from yfinance recommendations + upgrades_downgrades).
    Backtest path doesn't call this (no historical free data).

    Logs a WARN with the failure rate so a transient yfinance outage that
    silently degrades the sub-score for many tickers is visible per-scan.
    """
    if not analyst_revisions_data:
        return {}
    from src.scoring.analyzers import analyst_revisions as _ar
    ar_as_of = as_of or date.today()
    out: dict[str, dict[str, Any]] = {}
    failures = 0
    for ticker, rows in analyst_revisions_data.items():
        if not rows:
            continue
        try:
            res = _ar.analyze(rows, as_of=ar_as_of)
        except Exception as e:
            logger.debug("analyst_revisions failed for %s: %s", ticker, e)
            failures += 1
            continue
        if res is not None:
            out[ticker.upper()] = res
    if failures > 0:
        n_attempted = sum(1 for r in analyst_revisions_data.values() if r)
        logger.warning(
            "analyst_revisions: %d / %d tickers failed (%.0f%%); "
            "sub-score missing for those names",
            failures, n_attempted,
            100.0 * failures / max(1, n_attempted),
        )
    return out


def _prepass_options_skew(
    options_chains: dict[str, Any] | None,
    price_data_map: dict[str, pd.DataFrame],
) -> dict[str, dict[str, Any]]:
    """LIVE-ONLY analyzer pre-pass — caller supplies option chains. Per-
    ticker current_price is read from the latest close of the matching
    price-data row. Skipped silently when chain or price is unavailable."""
    if not options_chains:
        return {}
    from src.scoring.analyzers import options_skew as _os
    out: dict[str, dict[str, Any]] = {}
    failures = 0
    for ticker, chain in options_chains.items():
        df = price_data_map.get(ticker)
        if df is None or df.empty or chain is None:
            continue
        try:
            current_price = float(df["Close"].iloc[-1])
            res = _os.analyze(chain, current_price=current_price)
        except Exception as e:
            logger.debug("options_skew failed for %s: %s", ticker, e)
            failures += 1
            continue
        if res is not None:
            out[ticker.upper()] = res
    if failures > 0:
        n_attempted = sum(
            1 for t, c in options_chains.items()
            if c is not None and price_data_map.get(t) is not None
            and not price_data_map[t].empty
        )
        logger.warning(
            "options_skew: %d / %d tickers failed (%.0f%%); "
            "sub-score missing for those names",
            failures, n_attempted,
            100.0 * failures / max(1, n_attempted),
        )
    return out


def _prepass_sector_flows(
    sector_etfs: dict[str, pd.DataFrame] | None,
    fundamentals_map: dict[str, dict],
    as_of: date | None,
) -> dict[str, dict[str, Any]]:
    """Sector ETF momentum pre-pass. Caller passes the 11 SPDR sector ETFs;
    each ticker's fundamentals.sector field maps to one ETF via SECTOR_TO_ETF.
    Returns ticker -> sector_flows_score dict."""
    if not sector_etfs:
        return {}
    from src.scoring.analyzers import sector_flows as _sf
    from src.scoring.analyzers.sector_flows import SECTOR_TO_ETF as _SECTOR_TO_ETF
    as_of_ts = pd.Timestamp(as_of) if as_of else pd.Timestamp.now().normalize()
    out: dict[str, dict[str, Any]] = {}
    failures = 0
    attempted = 0
    for ticker, fund in fundamentals_map.items():
        sec = (fund.get("sector") or "").strip()
        if not sec or sec not in _SECTOR_TO_ETF:
            continue
        etf_symbol = _SECTOR_TO_ETF[sec]
        etf_df = sector_etfs.get(etf_symbol)
        if etf_df is None or etf_df.empty:
            continue
        attempted += 1
        try:
            res = _sf.analyze(etf_df, as_of=as_of_ts, etf_symbol=etf_symbol)
        except Exception as e:
            logger.debug("sector_flows analyze failed for %s: %s", ticker, e)
            failures += 1
            continue
        if res is not None:
            out[ticker.upper()] = res
    if failures > 0:
        logger.warning(
            "sector_flows: %d / %d tickers failed (%.0f%%); "
            "sub-score missing for those names",
            failures, attempted,
            100.0 * failures / max(1, attempted),
        )
    return out


def _build_analyzer_error_result(error_msg: str) -> dict[str, Any]:
    """Sentinel analyzer-result dict for a ticker whose analyzer chain
    crashed. Every REQUIRED analyzer is marked as error so the composite
    engine sets score_valid=False, the recommender forces HOLD/Low, and
    the FE renders a Data-Quality warning instead of a 404."""
    return {
        "technical": {"score": None, "error": error_msg},
        "alpha158": None,
        "fundamental": {"score": None, "error": error_msg},
        "pattern": {"score": None, "error": error_msg},
        "statistical": {"score": None, "error": error_msg},
        "trend": {"score": None, "error": error_msg},
    }


def _analyze_one_ticker(
    ticker: str,
    df: pd.DataFrame,
    fund: dict[str, Any],
    config,
    *,
    sector_stats,
    bench_df: pd.DataFrame | None,
    insider_results: dict[str, dict[str, Any]],
    catalyst_results: dict[str, dict[str, Any]],
    sector_flows_results: dict[str, dict[str, Any]],
    analyst_revisions_results: dict[str, dict[str, Any]],
    options_skew_results: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Run every per-ticker analyzer + stitch in the bulk pre-pass results.

    Pre-pass results (insider/catalyst/sector_flows/analyst_revisions/
    options_skew) are looked up by ticker, not re-computed.
    """
    upper = ticker.upper()
    return {
        "technical": technical.analyze(df, config),
        "alpha158": alpha158.analyze(df, config),
        "fundamental": fundamental.analyze(
            fund, config, sector_stats=sector_stats,
        ),
        "pattern": patterns.analyze(df, config),
        "statistical": statistical.analyze(df, config),
        "trend": analyze_stock_trend(df, fund, config),
        "rel_strength": (
            relative_strength.analyze(df, bench_df, config)
            if bench_df is not None else None
        ),
        "insider_flow": insider_results.get(upper),
        "catalyst": catalyst_results.get(upper),
        "sector_flows": sector_flows_results.get(upper),
        "analyst_revisions": analyst_revisions_results.get(upper),
        "options_skew": options_skew_results.get(upper),
    }


def _score_and_recommend(
    analysis_results: dict[str, dict[str, Any]],
    price_data_map: dict[str, pd.DataFrame],
    fundamentals_map: dict[str, dict],
    config,
    strategy: dict,
    *,
    emit: AnalyzeEventCallback,
) -> list[dict[str, Any]]:
    """Composite-score the analysis results, then run the recommender on
    each scored ticker. Emits ``score_start`` and ``recommend_start``
    pipeline events for the SSE progress endpoint."""
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


def analyze_and_score(
    price_data_map: dict[str, pd.DataFrame],
    fundamentals_map: dict[str, dict],
    config,
    strategy: dict,
    *,
    on_event: AnalyzeEventCallback | None = None,
    benchmark_df: pd.DataFrame | None = None,
    as_of: date | None = None,
    sector_etfs: dict[str, pd.DataFrame] | None = None,
    analyst_revisions_data: dict[str, list] | None = None,
    options_chains: dict[str, Any] | None = None,
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

    sector_stats = _compute_sector_stats_if_enabled(config, fundamentals_map)
    bench_df = _resolve_benchmark(benchmark_df, price_data_map)

    universe = list(price_data_map.keys())
    insider_results = _prepass_insider_flow(config, universe, as_of)
    catalyst_results = _prepass_catalyst(config, universe, as_of)
    analyst_revisions_results = _prepass_analyst_revisions(
        analyst_revisions_data, as_of,
    )
    options_skew_results = _prepass_options_skew(
        options_chains, price_data_map,
    )
    sector_flows_results = _prepass_sector_flows(
        sector_etfs, fundamentals_map, as_of,
    )

    analysis_results: dict[str, dict[str, Any]] = {}
    total = len(price_data_map)
    for i, (ticker, df) in enumerate(price_data_map.items(), 1):
        emit({"stage": "analyze_ticker_start", "ticker": ticker, "i": i, "n": total})
        fund = fundamentals_map.get(ticker, {})
        try:
            analysis_results[ticker] = _analyze_one_ticker(
                ticker, df, fund, config,
                sector_stats=sector_stats,
                bench_df=bench_df,
                insider_results=insider_results,
                catalyst_results=catalyst_results,
                sector_flows_results=sector_flows_results,
                analyst_revisions_results=analyst_revisions_results,
                options_skew_results=options_skew_results,
            )
            emit({"stage": "analyze_ticker_done", "ticker": ticker, "i": i, "n": total})
        except Exception as e:
            logger.error("Error analyzing %s: %s", ticker, e)
            analysis_results[ticker] = _build_analyzer_error_result(
                f"analyzer crashed: {e}"
            )
            emit({
                "stage": "analyze_ticker_failed",
                "ticker": ticker, "i": i, "n": total,
                "error": str(e),
            })

    return _score_and_recommend(
        analysis_results, price_data_map, fundamentals_map,
        config, strategy, emit=emit,
    )
