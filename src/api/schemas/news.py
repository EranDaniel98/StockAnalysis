"""Schemas for /api/news -- market-moving news feed.

Aggregates Polygon ticker-tagged news across a set of broad-market
bellwethers (index ETFs + mega-cap movers) plus our live holdings, then
dedupes into one reverse-chronological market feed with per-ticker
sentiment. Read-only; Polygon is the only source (we already pay for it).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

Sentiment = Literal["positive", "negative", "neutral"]


class NewsInsight(BaseModel):
    """Polygon's per-ticker sentiment call on one article."""
    ticker: str
    sentiment: Sentiment
    reasoning: Optional[str] = None


class NewsArticle(BaseModel):
    id: str
    title: str
    publisher: str
    author: Optional[str] = None
    published_utc: str
    url: str
    image_url: Optional[str] = None
    description: Optional[str] = None
    tickers: list[str] = Field(default_factory=list)
    # Article-level tilt = majority of its per-ticker insights. None when
    # Polygon attaches no sentiment.
    sentiment: Optional[Sentiment] = None
    insights: list[NewsInsight] = Field(default_factory=list)


class NewsResponse(BaseModel):
    generated_at: datetime
    lookback_days: int
    tickers_covered: list[str]
    n_articles: int = Field(ge=0)
    # How many articles tilt each way -- a crude market-mood gauge.
    sentiment_counts: dict[str, int]
    articles: list[NewsArticle]
