"""Point-in-time universe membership.

The current universe (e.g., today's S&P 500) suffers survivorship bias
when used to backtest historical dates: it omits stocks that were in
the index at date D but have since been removed (often because they
underperformed, were delisted, or went bankrupt). Tying every backtest
to ``as_of(D)`` reconstructs the universe the strategy could actually
have traded.

See ``src.universe.sp500_pit.SP500Membership``.
"""

from src.universe.sp500_pit import SP500Membership, load_default_sp500

__all__ = ["SP500Membership", "load_default_sp500"]
