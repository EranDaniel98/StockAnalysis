"""
Typed exception hierarchy for StockNew.

Replaces ad-hoc ValueError/RuntimeError across the codebase. Caller code can
catch a specific subclass (DataError to retry; ValidationError to surface to
the user; LookaheadGuardError to abort a backtest) rather than string-matching
exception messages.
"""


class DomainError(Exception):
    """Base for all StockNew domain errors. Catch this to handle anything
    raised by our own code (vs. third-party exceptions like yfinance/Alpaca)."""


class ValidationError(DomainError):
    """A pydantic model validated but the *semantic* check failed. Example:
    strategy weights don't sum to 1.0; backtest start > end."""


class DataError(DomainError):
    """A repository call returned no data, partial data, or stale data.
    Retryable. Example: yfinance returned an empty DataFrame for a known
    valid ticker; Redis miss for a key that should have been warm."""


class ExternalAPIError(DomainError):
    """A third-party API (yfinance, Alpaca, EDGAR, Polygon) returned an
    error or timed out. Distinct from DataError so retry policy can differ."""


class LookaheadGuardError(DomainError):
    """A backtest or diagnostic refused to run because the strategy uses
    point-in-time-unsafe data (e.g. fundamentals weight > threshold against
    a current-snapshot fundamentals source). The guard exists to prevent
    silently invalid results. Bypass via --accept-lookahead flag."""
