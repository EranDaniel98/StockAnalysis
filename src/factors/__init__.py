"""Cross-sectional factor library.

Replaces the broken 6-analyzer composite (see
``project_final_edge_verdict``) with the well-documented academic
factor toolkit:

- Momentum (Jegadeesh-Titman 1993): 12-1 month return
- Trend regime (Faber 2007): SPY 200-day SMA filter
- Quality (deferred — needs EDGAR PIT fundamentals)
- Value (deferred — needs EDGAR PIT fundamentals)

Design rules
------------
1. Every factor takes ``(prices_dict, as_of_date)`` and uses ONLY data
   on or before ``as_of_date``. Anything later is a lookahead bug.
2. Factor output is a tidy DataFrame with columns
   ``ticker, raw, rank, z_score`` — uniform shape so the composite
   can rank-combine.
3. Cross-sectional rank, not absolute threshold. Rank is robust to
   distribution shifts; absolute thresholds drift across regimes.
4. Long-only by default. Long-short adds short-borrow + execution risk
   the user hasn't authorized.
"""

from src.factors.momentum import momentum_12_1
from src.factors.regime import is_risk_on, trend_state_series

__all__ = ["momentum_12_1", "is_risk_on", "trend_state_series"]
