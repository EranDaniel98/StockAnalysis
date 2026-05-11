"""OHLCV price bars."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class OHLCVBar(BaseModel):
    """A single OHLCV bar. Tz-aware UTC."""

    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    open: float = Field(ge=0)
    high: float = Field(ge=0)
    low: float = Field(ge=0)
    close: float = Field(ge=0)
    volume: float = Field(ge=0)


class OHLCVSeries(BaseModel):
    """A sequence of OHLCV bars for a single ticker.

    The current code passes DataFrames everywhere. We keep DataFrames as the
    workhorse for analyzers (numpy speed matters) but use this entity at
    repository boundaries so types are explicit.
    """

    model_config = ConfigDict(frozen=True)

    ticker: str
    interval: str
    """Bar interval. E.g. '1d', '1h', '5m'."""

    bars: tuple[OHLCVBar, ...]
