"""Portfolio bounded context.

Re-exports the holdings module's Portfolio class under the legacy import
location (`from src.portfolio import Portfolio`) so existing callers
(src/main.py, src/paper/bootstrap.py) keep working through Phase 0.

Stream B also moves the portfolio-level allocation and diversification
helpers here from src/scoring/recommender.py (see allocation.py).
"""

from src.portfolio.allocation import (
    allocate_portfolio,
    check_diversification,
    suggest_order_type,
)
from src.portfolio.holdings import Portfolio

__all__ = [
    "Portfolio",
    "allocate_portfolio",
    "check_diversification",
    "suggest_order_type",
]
