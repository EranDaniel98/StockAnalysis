"""
StockNew contract layer — typed domain entities and repository protocols.

This package is the API contract every other module programs against. It contains:

  - `entities/`: pydantic v2 immutable domain models (frozen=True). These replace
    the untyped dicts that flow through scoring, backtest, and CLI today.
  - `protocols/`: structural-typing Protocol classes for repositories and the
    cache layer. Concrete implementations live in src/db/, src/cache/, src/storage/.
  - `errors`: typed exception hierarchy. Replaces ad-hoc ValueError/RuntimeError.

Stability contract: this package is frozen after Phase 0 pre-phase merges. Any
field change is a separate, user-approved task. Do not edit in implementation
work.
"""

from src.contracts.entities.analysis import AnalysisBundle, SubAnalysisResult
from src.contracts.entities.backtest import (
    BacktestResult,
    BacktestTrade,
    EquityPoint,
    RegimeSplit,
)
from src.contracts.entities.factor import FactorSnapshot, ICReport, QuantileSpread
from src.contracts.entities.fundamentals import FundamentalPanel, FundamentalSnapshot
from src.contracts.entities.market import MarketClock, MarketRegime
from src.contracts.entities.ohlcv import OHLCVBar, OHLCVSeries
from src.contracts.entities.recommendation import (
    OrderInstruction,
    Recommendation,
    RiskManagement,
)
from src.contracts.entities.score import (
    CompositeScore,
    ConsensusDiagnostic,
    ScoreBreakdownRow,
)
from src.contracts.entities.signal import Signal, SignalType
from src.contracts.entities.strategy import (
    StrategyConfig,
    StrategyThresholds,
    StrategyWeights,
)
from src.contracts.errors import (
    DataError,
    DomainError,
    ExternalAPIError,
    LookaheadGuardError,
    ValidationError,
)

__all__ = [
    "AnalysisBundle",
    "BacktestResult",
    "BacktestTrade",
    "CompositeScore",
    "ConsensusDiagnostic",
    "DataError",
    "DomainError",
    "EquityPoint",
    "ExternalAPIError",
    "FactorSnapshot",
    "FundamentalPanel",
    "FundamentalSnapshot",
    "ICReport",
    "LookaheadGuardError",
    "MarketClock",
    "MarketRegime",
    "OHLCVBar",
    "OHLCVSeries",
    "OrderInstruction",
    "QuantileSpread",
    "Recommendation",
    "RegimeSplit",
    "RiskManagement",
    "ScoreBreakdownRow",
    "Signal",
    "SignalType",
    "StrategyConfig",
    "StrategyThresholds",
    "StrategyWeights",
    "SubAnalysisResult",
    "ValidationError",
]
