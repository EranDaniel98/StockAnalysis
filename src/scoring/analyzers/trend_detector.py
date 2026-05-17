"""
Trend detection engine.
Identifies trending sectors and themes by analyzing cross-stock momentum
and volume patterns.
"""

import numpy as np
import logging

logger = logging.getLogger(__name__)


def analyze_stock_trend(df, fundamentals, config):
    """
    Score how 'trendy' a stock is based on its sector/theme alignment
    and current market momentum.

    Args:
        df: Price DataFrame for the stock
        fundamentals: dict of fundamental data for the stock
        config: Config object

    Returns:
        dict with keys: trend_score, trending_themes, signals, score (0-100)
    """
    if df is None or not fundamentals:
        return {"trending_themes": [], "signals": [], "score": 50}

    signals = []
    scores = []

    # ``or ""`` (not the .get default) because the fundamentals stub
    # for name-only-known instruments (leveraged ETFs, unrecognized
    # tickers) carries explicit ``None`` values rather than missing
    # keys — and downstream code does ``.lower()`` which crashes on
    # None.
    stock_sector = fundamentals.get("sector") or ""
    stock_industry = fundamentals.get("industry") or ""
    stock_description = (fundamentals.get("description") or "").lower()
    ticker = fundamentals.get("ticker") or ""

    focused_sectors = config.get_focused_sectors()
    themes = config.get_all_themes()

    # --- Sector Focus Alignment ---
    sector_score = _score_sector_alignment(
        stock_sector, stock_industry, focused_sectors, config, signals
    )
    scores.append(sector_score)

    # --- Theme Matching ---
    matching_themes = _match_themes(
        ticker, stock_industry, stock_description, themes, signals
    )

    if matching_themes:
        # More theme matches = higher trend score
        theme_score = min(90, 50 + len(matching_themes) * 15)
        scores.append(theme_score)
    else:
        scores.append(40)

    # --- Price Momentum as Trend Confirmation ---
    if df is not None and len(df) >= 21:
        close = df["Close"]
        ret_1m = (close.iloc[-1] / close.iloc[-21] - 1) * 100
        volume = df["Volume"]
        vol_ratio = volume.tail(5).mean() / volume.tail(20).mean() if volume.tail(20).mean() > 0 else 1

        # Rising price + rising volume = strong trend
        if ret_1m > 10 and vol_ratio > 1.5:
            signals.append({
                "type": "bullish",
                "source": "TrendConfirm",
                "detail": f"Price +{ret_1m:.1f}% with {vol_ratio:.1f}x volume",
            })
            scores.append(80)
        elif ret_1m > 5:
            scores.append(65)
        elif ret_1m > 0:
            scores.append(55)
        else:
            scores.append(40)

    composite = np.mean(scores) if scores else 50

    return {
        "trending_themes": matching_themes,
        "signals": signals,
        "score": round(float(composite), 2),
    }


def detect_trending_sectors(price_data_map, fundamentals_map, config):
    """
    Analyze all stocks to find which sectors are trending.

    Args:
        price_data_map: dict of {ticker: DataFrame}
        fundamentals_map: dict of {ticker: fundamentals_dict}
        config: Config object

    Returns:
        list of dicts with sector name, momentum, volume change, stock count
    """
    sector_stats = {}

    for ticker, df in price_data_map.items():
        fund = fundamentals_map.get(ticker, {})
        sector = fund.get("sector", "Unknown")

        if sector not in sector_stats:
            sector_stats[sector] = {
                "tickers": [],
                "returns_1m": [],
                "returns_3m": [],
                "vol_ratios": [],
            }

        close = df["Close"]
        volume = df["Volume"]

        if len(close) >= 21:
            ret_1m = (close.iloc[-1] / close.iloc[-21] - 1) * 100
            sector_stats[sector]["returns_1m"].append(ret_1m)

        if len(close) >= 63:
            ret_3m = (close.iloc[-1] / close.iloc[-63] - 1) * 100
            sector_stats[sector]["returns_3m"].append(ret_3m)

        if len(volume) >= 20:
            vol_ratio = volume.tail(5).mean() / volume.tail(20).mean()
            sector_stats[sector]["vol_ratios"].append(float(vol_ratio))

        sector_stats[sector]["tickers"].append(ticker)

    # Compute sector-level metrics
    results = []
    for sector, stats in sector_stats.items():
        result = {
            "sector": sector,
            "stock_count": len(stats["tickers"]),
            "avg_return_1m": round(np.mean(stats["returns_1m"]), 2) if stats["returns_1m"] else 0,
            "avg_return_3m": round(np.mean(stats["returns_3m"]), 2) if stats["returns_3m"] else 0,
            "avg_vol_ratio": round(np.mean(stats["vol_ratios"]), 2) if stats["vol_ratios"] else 1.0,
            "pct_positive_1m": round(
                sum(1 for r in stats["returns_1m"] if r > 0) / len(stats["returns_1m"]) * 100, 1
            ) if stats["returns_1m"] else 0,
        }

        # Trend score: combine momentum and breadth
        momentum_score = min(100, max(0, 50 + result["avg_return_1m"] * 2))
        breadth_score = result["pct_positive_1m"]
        result["trend_score"] = round((momentum_score + breadth_score) / 2, 1)

        results.append(result)

    # Sort by trend score
    results.sort(key=lambda x: x["trend_score"], reverse=True)
    return results


def _score_sector_alignment(sector, industry, focused_sectors, config, signals):
    """Score how well a stock's sector aligns with focus areas."""
    if not focused_sectors:
        return 50  # No focus = all sectors equal

    # Check direct sector match
    for fs in focused_sectors:
        if fs.lower() in sector.lower() or fs.lower() in industry.lower():
            signals.append({
                "type": "bullish",
                "source": "SectorFocus",
                "detail": f"In focused sector: {sector}",
            })
            return 75

    # Not in a focused sector
    return 40


def _match_themes(ticker, industry, description, themes, signals):
    """Check which themes a stock matches."""
    matched = []

    for theme_key, theme in themes.items():
        display_name = theme.get("display_name", theme_key)

        # Check known tickers
        if ticker in theme.get("known_tickers", []):
            matched.append(display_name)
            signals.append({
                "type": "bullish",
                "source": "Theme",
                "detail": f"Known {display_name} stock",
            })
            continue

        # Check keywords against industry and description
        keywords = theme.get("keywords", [])
        for keyword in keywords:
            kw_lower = keyword.lower()
            if kw_lower in industry.lower() or kw_lower in description:
                matched.append(display_name)
                signals.append({
                    "type": "bullish",
                    "source": "Theme",
                    "detail": f"Matches '{display_name}' theme (keyword: {keyword})",
                })
                break

    return matched
