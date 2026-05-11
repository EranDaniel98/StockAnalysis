"""Trading signals emitted by analyzers."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

SignalType = Literal["bullish", "bearish", "neutral"]


class Signal(BaseModel):
    """A single trading signal from an analyzer.

    Today's analyzers emit signals as dicts: {"type", "source", "detail"}.
    This entity is the typed replacement.
    """

    model_config = ConfigDict(frozen=True)

    type: SignalType
    source: str
    """Where the signal came from. E.g. 'Technical/RSI', 'Alpha158/KMID'."""

    detail: str
    """Human-readable description. E.g. 'RSI=72, overbought'."""
