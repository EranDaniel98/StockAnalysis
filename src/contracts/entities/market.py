"""Market state entities — clock + regime."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class MarketClock(BaseModel):
    """Current market state. Mirrors what Alpaca's clock API returns."""

    model_config = ConfigDict(frozen=True)

    is_open: bool
    next_open: datetime
    next_close: datetime


VolatilityRegime = Literal["low", "normal", "high"]
"""VIX bands: low (<15), normal (15-25), high (>25)."""

TrendRegime = Literal["bull", "bear"]
"""SPY vs 200-day SMA. Bull = above, bear = below."""


class MarketRegime(BaseModel):
    """Headline market context for a point in time.

    Used by the regime-split analytics in the backtest report and by the
    future research agent to flag regime shifts.
    """

    model_config = ConfigDict(frozen=True)

    as_of: datetime
    vol_regime: VolatilityRegime
    trend_regime: TrendRegime
    vix: float
    spy_close: float
    spy_sma_200: float
