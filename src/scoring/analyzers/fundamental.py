"""
Fundamental analysis engine.
Scores stocks on valuation, growth, profitability, and financial health.
All thresholds come from config.
"""

import logging
import numpy as np

from src.scoring.sector_stats import percentile_bucket

logger = logging.getLogger(__name__)


# Sector-relative valuation scoring: map percentile bucket → score band.
# Lower-is-better orientation (cheap = bullish), so "low" bucket scores
# highest. Bands match the absolute-threshold path closely so the two
# scorers stay comparable when sector stats are missing.
_SECTOR_RELATIVE_BANDS: dict[str, int] = {
    "low": 80,
    "below_median": 65,
    "above_median": 50,
    "high": 30,
}


def analyze(fundamentals, config, *, sector_stats=None):
    """
    Score a stock's fundamental data.

    Args:
        fundamentals: dict of financial metrics from FundamentalsFetcher
        config: Config object
        sector_stats: optional ``{sector: {metric: {q1, median, q3}}}``
            from ``src.scoring.sector_stats.compute_sector_stats``. When
            present, valuation metrics are scored on percentile within
            the ticker's sector cohort instead of the absolute
            thresholds in this file. The fallback (None or sector
            missing) is the legacy behavior — same scores as before.

    Returns:
        dict with keys: scores (per category), signals, score (0-100)
    """
    if not fundamentals:
        return {"scores": {}, "signals": [], "score": 50, "error": "No fundamental data"}

    signals = []
    category_scores = {}

    # --- Valuation Score ---
    category_scores["valuation"] = _score_valuation(
        fundamentals, config, signals, sector_stats=sector_stats,
    )

    # --- Growth Score ---
    category_scores["growth"] = _score_growth(fundamentals, config, signals)

    # --- Profitability Score ---
    category_scores["profitability"] = _score_profitability(fundamentals, config, signals)

    # --- Financial Health Score ---
    category_scores["health"] = _score_health(fundamentals, config, signals)

    # --- Dividend Score (if applicable) ---
    category_scores["dividend"] = _score_dividend(fundamentals, config, signals)

    # --- Analyst Sentiment ---
    category_scores["analyst"] = _score_analyst(fundamentals, config, signals)

    # Composite: weighted average of categories
    weights = {
        "valuation": 0.25,
        "growth": 0.25,
        "profitability": 0.20,
        "health": 0.15,
        "dividend": 0.05,
        "analyst": 0.10,
    }

    valid_scores = {k: v for k, v in category_scores.items() if v is not None}
    if not valid_scores:
        return {"scores": category_scores, "signals": signals, "score": 50}

    # Redistribute weights for missing categories
    total_weight = sum(weights[k] for k in valid_scores)
    composite = sum(
        valid_scores[k] * weights[k] / total_weight for k in valid_scores
    )

    return {
        "scores": category_scores,
        "signals": signals,
        "score": round(float(composite), 2),
    }


def _sector_relative_lookup(sector_stats, sector, metric):
    """Return the per-metric quantile dict for this ticker's sector,
    or None when sector stats are absent / sector cohort too sparse /
    metric dropped (too few non-null values). Caller falls back to
    absolute thresholds on None."""
    if not sector_stats or not sector:
        return None
    sector_block = sector_stats.get(sector)
    if not sector_block:
        return None
    return sector_block.get(metric)


def _score_valuation_sector_relative(fund, sector_stats, signals):
    """Sector-relative scoring for valuation metrics.

    Returns ``(scores_list, used_keys_set)`` — used_keys lets the
    caller skip those metrics in the absolute-threshold pass so we
    don't double-count. Any metric without sector stats falls through
    to the absolute scorer.
    """
    sector = fund.get("sector")
    scored: list[float] = []
    used: set[str] = set()

    # P/E: trailing preferred, forward as fallback (matches absolute path).
    for key in ("pe_trailing", "pe_forward"):
        pe = fund.get(key)
        if pe is None or pe <= 0:
            continue
        stats = _sector_relative_lookup(sector_stats, sector, key)
        if stats is None:
            continue
        bucket = percentile_bucket(float(pe), stats)
        scored.append(_SECTOR_RELATIVE_BANDS[bucket])
        if bucket == "low":
            signals.append({
                "type": "bullish", "source": "P/E vs Sector",
                "detail": f"{pe:.1f} vs {sector} median {stats['median']:.1f}",
            })
        elif bucket == "high":
            signals.append({
                "type": "bearish", "source": "P/E vs Sector",
                "detail": f"{pe:.1f} vs {sector} Q3 {stats['q3']:.1f}",
            })
        used.add(key)
        used.add("pe_trailing")  # block fallback even if we scored forward
        used.add("pe_forward")
        break  # only score one P/E

    for key, label in (("peg_ratio", "PEG"), ("pb_ratio", "P/B"), ("ev_to_ebitda", "EV/EBITDA")):
        value = fund.get(key)
        if value is None or value <= 0:
            continue
        stats = _sector_relative_lookup(sector_stats, sector, key)
        if stats is None:
            continue
        bucket = percentile_bucket(float(value), stats)
        scored.append(_SECTOR_RELATIVE_BANDS[bucket])
        if bucket == "low":
            signals.append({
                "type": "bullish", "source": f"{label} vs Sector",
                "detail": f"{value:.2f} vs {sector} median {stats['median']:.2f}",
            })
        elif bucket == "high":
            signals.append({
                "type": "bearish", "source": f"{label} vs Sector",
                "detail": f"{value:.2f} vs {sector} Q3 {stats['q3']:.2f}",
            })
        used.add(key)

    return scored, used


def _score_valuation(fund, config, signals, *, sector_stats=None):
    """Score based on P/E, P/B, PEG, EV/EBITDA.

    When ``sector_stats`` is provided and a metric has a sector cohort,
    score that metric on within-sector percentile (cheaper than sector
    median = bullish). Metrics without sector coverage fall back to the
    absolute thresholds below. This means a partial rollout — some
    metrics sector-relative, others absolute — is supported in one pass.
    """
    filters = config.get("fundamental_filters", default={})

    sector_scores, sector_used = _score_valuation_sector_relative(
        fund, sector_stats, signals,
    ) if sector_stats else ([], set())
    scores: list[float] = list(sector_scores)

    # P/E Ratio (only if sector-relative didn't already score it)
    if "pe_trailing" not in sector_used:
        pe = fund.get("pe_trailing") or fund.get("pe_forward")
        if pe is not None and pe > 0:
            max_pe = filters.get("max_pe_ratio", 50)
            if pe < 15:
                scores.append(80)
                signals.append({"type": "bullish", "source": "P/E", "detail": f"Low P/E: {pe:.1f}"})
            elif pe < 25:
                scores.append(65)
            elif pe < max_pe:
                scores.append(50)
            else:
                scores.append(25)
                signals.append({"type": "bearish", "source": "P/E", "detail": f"High P/E: {pe:.1f}"})

    # PEG Ratio (P/E to Growth)
    if "peg_ratio" not in sector_used:
        peg = fund.get("peg_ratio")
        if peg is not None and peg > 0:
            if peg < 1:
                scores.append(85)
                signals.append({"type": "bullish", "source": "PEG", "detail": f"Undervalued PEG: {peg:.2f}"})
            elif peg < 1.5:
                scores.append(70)
            elif peg < 2:
                scores.append(55)
            else:
                scores.append(35)

    # Price-to-Book
    if "pb_ratio" not in sector_used:
        pb = fund.get("pb_ratio")
        if pb is not None and pb > 0:
            if pb < 1:
                scores.append(80)
                signals.append({"type": "bullish", "source": "P/B", "detail": f"Below book value: {pb:.2f}"})
            elif pb < 3:
                scores.append(65)
            elif pb < 10:
                scores.append(50)
            else:
                scores.append(30)

    # EV/EBITDA
    if "ev_to_ebitda" not in sector_used:
        ev_ebitda = fund.get("ev_to_ebitda")
        if ev_ebitda is not None and ev_ebitda > 0:
            if ev_ebitda < 10:
                scores.append(75)
            elif ev_ebitda < 20:
                scores.append(55)
            else:
                scores.append(35)

    return np.mean(scores) if scores else None


def _score_growth(fund, config, signals):
    """Score based on revenue and earnings growth."""
    scores = []
    filters = config.get("fundamental_filters", default={})
    min_rev_growth = filters.get("min_revenue_growth_pct", 10) / 100

    # Revenue growth
    rg = fund.get("revenue_growth")
    if rg is not None:
        if rg > 0.5:
            scores.append(90)
            signals.append({"type": "bullish", "source": "Revenue", "detail": f"Strong growth: {rg*100:.1f}%"})
        elif rg > 0.2:
            scores.append(75)
            signals.append({"type": "bullish", "source": "Revenue", "detail": f"Good growth: {rg*100:.1f}%"})
        elif rg > min_rev_growth:
            scores.append(60)
        elif rg > 0:
            scores.append(45)
        else:
            scores.append(20)
            signals.append({"type": "bearish", "source": "Revenue", "detail": f"Declining: {rg*100:.1f}%"})

    # Earnings growth
    eg = fund.get("earnings_growth")
    if eg is not None:
        if eg > 0.5:
            scores.append(85)
        elif eg > 0.2:
            scores.append(70)
        elif eg > 0:
            scores.append(55)
        else:
            scores.append(25)
            signals.append({"type": "bearish", "source": "Earnings", "detail": f"Declining: {eg*100:.1f}%"})

    return np.mean(scores) if scores else None


def _score_profitability(fund, config, signals):
    """Score based on margins and return metrics."""
    scores = []
    filters = config.get("fundamental_filters", default={})

    # Return on Equity
    roe = fund.get("roe")
    min_roe = filters.get("min_roe_pct", 10) / 100
    if roe is not None:
        if roe > 0.25:
            scores.append(85)
            signals.append({"type": "bullish", "source": "ROE", "detail": f"Excellent: {roe*100:.1f}%"})
        elif roe > min_roe:
            scores.append(65)
        elif roe > 0:
            scores.append(40)
        else:
            scores.append(15)
            signals.append({"type": "bearish", "source": "ROE", "detail": f"Negative: {roe*100:.1f}%"})

    # Profit Margin
    pm = fund.get("profit_margin")
    min_pm = filters.get("min_profit_margin_pct", 5) / 100
    if pm is not None:
        if pm > 0.3:
            scores.append(85)
        elif pm > 0.15:
            scores.append(70)
        elif pm > min_pm:
            scores.append(55)
        elif pm > 0:
            scores.append(35)
        else:
            scores.append(15)

    # Operating Margin
    om = fund.get("operating_margin")
    if om is not None:
        if om > 0.3:
            scores.append(80)
        elif om > 0.15:
            scores.append(65)
        elif om > 0:
            scores.append(45)
        else:
            scores.append(20)

    # Gross Margin
    gm = fund.get("gross_margins")
    if gm is not None:
        if gm > 0.6:
            scores.append(80)
        elif gm > 0.4:
            scores.append(65)
        elif gm > 0.2:
            scores.append(45)
        else:
            scores.append(25)

    return np.mean(scores) if scores else None


def _score_health(fund, config, signals):
    """Score based on debt, cash flow, and liquidity."""
    scores = []
    filters = config.get("fundamental_filters", default={})

    # Debt-to-Equity
    de = fund.get("debt_to_equity")
    max_de = filters.get("max_debt_to_equity", 2.0)
    if de is not None:
        # yfinance reports D/E as percentage (e.g., 150 = 1.5x)
        de_ratio = de / 100 if de > 10 else de
        if de_ratio < 0.3:
            scores.append(85)
            signals.append({"type": "bullish", "source": "Debt", "detail": f"Low debt: {de_ratio:.2f}x"})
        elif de_ratio < 1.0:
            scores.append(70)
        elif de_ratio < max_de:
            scores.append(50)
        else:
            scores.append(20)
            signals.append({"type": "bearish", "source": "Debt", "detail": f"High debt: {de_ratio:.2f}x"})

    # Current Ratio
    cr = fund.get("current_ratio")
    min_cr = filters.get("min_current_ratio", 1.0)
    if cr is not None:
        if cr > 2.0:
            scores.append(80)
        elif cr > min_cr:
            scores.append(65)
        elif cr > 0.5:
            scores.append(35)
        else:
            scores.append(15)
            signals.append({"type": "bearish", "source": "Liquidity", "detail": f"Low current ratio: {cr:.2f}"})

    # Free Cash Flow
    fcf = fund.get("free_cash_flow")
    if fcf is not None:
        if fcf > 1_000_000_000:
            scores.append(80)
        elif fcf > 0:
            scores.append(65)
        else:
            scores.append(25)
            signals.append({"type": "bearish", "source": "FCF", "detail": "Negative free cash flow"})

    return np.mean(scores) if scores else None


def _score_dividend(fund, config, signals):
    """Score dividend metrics (optional, many growth stocks don't pay dividends)."""
    div_yield = fund.get("dividend_yield")
    if div_yield is None or div_yield == 0:
        return None  # Not applicable, won't affect composite

    # Sanity check: yfinance sometimes returns bad data
    # Valid dividend yields are typically 0-20% (0.0 to 0.20)
    if div_yield > 0.25:
        return None  # Bad data, skip

    payout = fund.get("payout_ratio")
    scores = []

    if div_yield > 0.05:
        scores.append(75)
        signals.append({"type": "bullish", "source": "Dividend", "detail": f"High yield: {div_yield*100:.2f}%"})
    elif div_yield > 0.02:
        scores.append(65)
    elif div_yield > 0:
        scores.append(55)

    if payout is not None:
        if 0.2 < payout < 0.6:
            scores.append(75)  # Sustainable payout
        elif payout < 0.2:
            scores.append(60)  # Room to grow
        elif payout > 0.8:
            scores.append(30)  # Unsustainable
            signals.append({"type": "bearish", "source": "Dividend", "detail": f"High payout ratio: {payout*100:.0f}%"})

    return np.mean(scores) if scores else None


def _score_analyst(fund, config, signals):
    """Score based on analyst recommendations."""
    rec = fund.get("recommendation")
    num_analysts = fund.get("num_analyst_opinions", 0)

    if not rec:
        return None

    score_map = {
        "strongBuy": 85,
        "buy": 75,
        "hold": 50,
        "sell": 25,
        "strongSell": 10,
    }

    score = score_map.get(rec, 50)

    # More analysts = more confidence in the score
    if num_analysts and num_analysts > 10:
        signals.append({"type": "neutral", "source": "Analyst", "detail": f"{rec} ({num_analysts} analysts)"})
    elif num_analysts and num_analysts > 0:
        # Less coverage -> regress toward 50
        score = 50 + (score - 50) * 0.7

    # Target price comparison
    target = fund.get("target_mean_price")
    current_approx = fund.get("fifty_day_avg")
    if target and current_approx and current_approx > 0:
        upside = (target / current_approx - 1) * 100
        if upside > 20:
            signals.append({"type": "bullish", "source": "Target", "detail": f"Upside: {upside:.0f}%"})
            score = min(score + 10, 95)
        elif upside < -10:
            signals.append({"type": "bearish", "source": "Target", "detail": f"Downside: {upside:.0f}%"})
            score = max(score - 10, 5)

    return score
