"""/api/news -- aggregated market-moving news feed (Polygon-sourced).

Polygon's news endpoint is ticker-tagged (no market-wide feed), so we fan
out across a set of bellwethers -- broad index ETFs + mega-cap movers --
plus today's live picks and the AI book's holdings, then dedupe by article
id into one reverse-chronological feed. Cached in-process for a few minutes
so the page is snappy and we don't hammer Polygon's rate limit.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Query

from src.api.dependencies import get_config
from src.api.schemas.news import NewsArticle, NewsInsight, NewsResponse
from src.config_loader import Config
from src.market_data.polygon import PolygonClient, PolygonError

logger = logging.getLogger(__name__)
router = APIRouter()

# Fallback bellwethers if config/settings.yaml::market_news.bellwethers is
# missing — index/sector ETFs + mega-cap movers. News tagged to these covers
# macro + market-structure stories (Polygon tags market-wide pieces to SPY/QQQ).
_BELLWETHERS_FALLBACK = [
    "SPY", "QQQ", "DIA", "IWM", "SMH",
    "NVDA", "AAPL", "MSFT", "AMZN", "GOOGL",
    "META", "AVGO", "TSLA", "JPM",
]


def _bellwethers(config: Config) -> list[str]:
    vals = config.get("market_news", "bellwethers", default=None)
    if not isinstance(vals, list) or not vals:
        return list(_BELLWETHERS_FALLBACK)
    return [str(t).upper() for t in vals]

PICKS_DIR = Path("data/daily_picks")
AI_BOOK_STATE = Path("reports") / "trend_forward_paper_ai_state.json"

# Per-ticker article cap and how many tickers to fan out over. Keep the fan-out
# bounded so one page load stays well under Polygon's rate limit.
_PER_TICKER = 10
_MAX_ARTICLES = 60

# In-process cache: news doesn't change second-to-second and the fan-out is
# ~20 HTTP calls, so serve a few-minutes-stale feed rather than refetch per load.
_CACHE_TTL_S = 300
_cache: dict[tuple, tuple[float, NewsResponse]] = {}


def _today_holdings_tickers() -> list[str]:
    """Fold today's live picks + AI-book holdings into the fan-out so the feed
    is relevant to what we actually hold, not just the index. Best-effort."""
    extra: set[str] = set()
    today = datetime.now(timezone.utc).date().isoformat()
    picks = PICKS_DIR / f"{today}.json"
    if picks.exists():
        try:
            data = json.loads(picks.read_text(encoding="utf-8"))
            for p in data.get("picks", []):
                t = (p.get("ticker") or "").upper()
                if t:
                    extra.add(t)
        except (OSError, json.JSONDecodeError):
            pass
    if AI_BOOK_STATE.exists():
        try:
            data = json.loads(AI_BOOK_STATE.read_text(encoding="utf-8"))
            extra.update(t.upper() for t in data.get("holdings", {}))
        except (OSError, json.JSONDecodeError):
            pass
    return sorted(extra)


def _article_sentiment(insights: list[NewsInsight]) -> str | None:
    if not insights:
        return None
    counts = Counter(i.sentiment for i in insights)
    # Majority tilt; ties fall back to neutral.
    top, n = counts.most_common(1)[0]
    second = counts.most_common(2)
    if len(second) > 1 and second[1][1] == n:
        return "neutral"
    return top


def _to_article(raw: dict, focus: set[str]) -> NewsArticle | None:
    """Map one Polygon news item → NewsArticle. Returns None if it lacks the
    id/title/url we need to render or link it."""
    aid = raw.get("id")
    title = raw.get("title")
    url = raw.get("article_url")
    if not (aid and title and url):
        return None
    pub = raw.get("publisher") or {}
    # Keep insights for tickers we care about first, then any others, capped.
    raw_insights = raw.get("insights") or []
    insights = [
        NewsInsight(
            ticker=i.get("ticker", ""),
            sentiment=i.get("sentiment", "neutral"),
            reasoning=i.get("sentiment_reasoning"),
        )
        for i in raw_insights
        if i.get("ticker") and i.get("sentiment") in ("positive", "negative", "neutral")
    ]
    insights.sort(key=lambda i: (i.ticker not in focus, i.ticker))
    tickers = [t for t in (raw.get("tickers") or []) if t]
    return NewsArticle(
        id=str(aid),
        title=title,
        publisher=pub.get("name") or "Unknown",
        author=raw.get("author") or None,
        published_utc=raw.get("published_utc") or "",
        url=url,
        image_url=raw.get("image_url") or None,
        description=(raw.get("description") or None),
        tickers=tickers[:12],
        sentiment=_article_sentiment(insights[:8]),
        insights=insights[:8],
    )


def _gather_news(tickers: list[str], lookback_days: int) -> list[NewsArticle]:
    """Concurrent per-ticker fan-out → deduped, reverse-chronological feed."""
    client = PolygonClient()
    since = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).date().isoformat()
    focus = set(tickers)

    def _one(t: str) -> list[dict]:
        try:
            return client.news(t, limit=_PER_TICKER, published_gte=since)
        except PolygonError as e:
            logger.warning("Polygon news failed for %s: %s", t, e)
            return []

    by_id: dict[str, NewsArticle] = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for raws in ex.map(_one, tickers):
            for raw in raws:
                art = _to_article(raw, focus)
                if art and art.id not in by_id:
                    by_id[art.id] = art
    articles = sorted(by_id.values(), key=lambda a: a.published_utc, reverse=True)
    return articles[:_MAX_ARTICLES]


@router.get("", response_model=NewsResponse)
async def get_market_news(
    lookback_days: int = Query(default=4, ge=1, le=30),
    include_holdings: bool = Query(
        default=True,
        description="Fold today's picks + AI-book holdings into the fan-out.",
    ),
    config: Config = Depends(get_config),
) -> NewsResponse:
    tickers = _bellwethers(config)
    if include_holdings:
        seen = set(tickers)
        for t in _today_holdings_tickers():
            if t not in seen:
                tickers.append(t)
                seen.add(t)

    cache_key = (tuple(tickers), lookback_days)
    now = time.time()
    cached = _cache.get(cache_key)
    if cached and now - cached[0] < _CACHE_TTL_S:
        return cached[1]

    articles = await asyncio.to_thread(_gather_news, tickers, lookback_days)
    counts = Counter(a.sentiment for a in articles if a.sentiment)
    resp = NewsResponse(
        generated_at=datetime.now(timezone.utc),
        lookback_days=lookback_days,
        tickers_covered=tickers,
        n_articles=len(articles),
        sentiment_counts={
            "positive": counts.get("positive", 0),
            "negative": counts.get("negative", 0),
            "neutral": counts.get("neutral", 0),
        },
        articles=articles,
    )
    _cache[cache_key] = (now, resp)
    return resp
