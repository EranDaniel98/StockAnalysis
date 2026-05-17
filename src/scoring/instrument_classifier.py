"""Detect non-stock instruments + insufficient history before scoring.

Two safety gates the analyzer chain doesn't currently enforce:

1. **Leveraged / inverse ETFs.** Instruments like ``Tradr 2X Long WDC
   Daily ETF`` (ticker WDCX) or ``Direxion Daily Semiconductor Bull 3X``
   are not buy-and-hold candidates. Daily-rebalanced leveraged ETFs
   decay exponentially under volatility (volatility drag) — holding
   them long-term loses money even when the underlying drifts
   sideways. The factor strategy assumes quarterly rebalancing on
   regular equities; leveraged ETFs violate that assumption and the
   composite score is meaningless for them.

2. **Insufficient price history.** Recent IPOs (or any ticker with
   fewer than ~1 year of daily bars) can't satisfy the technical /
   statistical / alpha158 analyzers' 50–252-bar history requirements.
   Those analyzers silently return "insufficient data" status and the
   composite is built from a smaller analyzer set — which the audit
   refactor surfaces via ``score_valid``, but the human-readable
   reason is buried in per-analyzer status fields.

This module centralizes both detection rules so the recommender can
gate on a single function call and the API can surface one boolean
each.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Literal, Optional

import pandas as pd

# Closed set of warning kinds the classifier can emit. Updating this
# Literal forces a refactor of every reader (recommender, FE) — that's
# the point: a new warning category should be a visible PR-wide change,
# not a stringly-typed surprise.
InstrumentWarning = Literal[
    "leveraged_or_inverse_etf",
    "non_stock_instrument",
]

logger = logging.getLogger(__name__)


# Patterns that almost-certainly identify a leveraged or inverse ETF
# from its longName / shortName. Case-insensitive. Matched as whole
# words / token boundaries to avoid false positives on company names
# that happen to contain "Bull" or "Long" (e.g. "Bull Run Brewing").
_LEVERAGE_PATTERNS: tuple[tuple[str, str], ...] = (
    # Multiplier markers — the strongest signal. "2X Long" / "-3X" /
    # "1.5X Long" / "3x Daily Bear" are all leveraged-ETF tells.
    # \d+(\.\d+)? catches integer AND fractional multipliers
    # (Tradr's 1.5X-Long family). The leading -? catches inverse.
    (r"-?\b\d+(\.\d+)?x\b", "leverage_multiplier"),
    # "Daily" combined with a directional word — the canonical
    # ProShares / Direxion / Tradr naming convention.
    (r"\bDaily\b.*\b(Bull|Bear|Long|Short|Inverse)\b", "daily_directional_etf"),
    (r"\b(Bull|Bear|Long|Short|Inverse)\b.*\bDaily\b", "daily_directional_etf"),
    # Inverse / short tells from the canonical-issuer naming. ProShares
    # uses "Short", "UltraShort", "UltraPro Short", "Ultra"; Direxion
    # uses "Daily ... Bull/Bear". Catch both family conventions.
    (r"\bProShares\b.*\b(Short|Ultra)\b", "proshares_leveraged_or_inverse"),
    (r"\bDirexion Daily\b", "directional_etf"),
    # Bare "Leveraged" / "Levered" tokens — last-resort catch-all for
    # smaller issuers (GraniteShares, MicroSectors, etc.) that don't
    # match the multiplier or daily-directional patterns above.
    (r"\b(Leveraged|Levered)\b", "leveraged_token"),
)


@dataclass(frozen=True, slots=True)
class InstrumentClassification:
    """Result of classifying one (ticker, name) pair.

    Invariants:
      * ``warning is None`` iff ``reason is None`` — the two are
        always paired or both absent.
      * ``warning`` is one of the closed-set ``InstrumentWarning``
        Literal values (or None).
    Frozen so callers can't mutate the result after the fact, which
    has bitten elsewhere when warnings were "cleared" by downstream
    code that shouldn't have.
    """

    ticker: str
    warning: Optional[InstrumentWarning]
    reason: Optional[str]

    def __post_init__(self) -> None:
        # Coupled-Optional check: warning and reason must agree on
        # presence. Anything else means a caller built an inconsistent
        # classification (e.g. set warning but forgot the reason).
        if (self.warning is None) != (self.reason is None):
            raise ValueError(
                f"InstrumentClassification: warning and reason must both "
                f"be set or both None — got warning={self.warning!r}, "
                f"reason={self.reason!r}"
            )


def classify_instrument(
    ticker: str,
    name: Optional[str],
    fundamentals: Optional[dict] = None,
) -> InstrumentClassification:
    """Return an InstrumentClassification for the (ticker, name) pair.

    Detection signals, in priority order:

    1. Name pattern match for leveraged / inverse / daily ETFs (the
       strongest signal — these instruments self-identify in their
       long name).
    2. Missing market_cap AND missing sector AND name contains
       "ETF" / "Fund" / "Trust" — generic ETF / mutual fund tell.

    A regular stock returns ``warning=None``.
    """
    name_str = (name or "").strip()
    if not name_str:
        return InstrumentClassification(
            ticker=ticker, warning=None, reason=None,
        )

    for pattern, label in _LEVERAGE_PATTERNS:
        if re.search(pattern, name_str, flags=re.IGNORECASE):
            return InstrumentClassification(
                ticker=ticker,
                warning="leveraged_or_inverse_etf",
                reason=(
                    f"Name '{name_str}' matched leveraged/inverse ETF "
                    f"pattern ({label}). These instruments decay under "
                    "volatility and aren't suitable for quarterly-"
                    "rebalance strategies."
                ),
            )

    # Generic ETF / fund detection. Real stocks have a sector and a
    # market cap; ETFs typically lack both in yfinance's fundamentals.
    fund = fundamentals or {}
    has_sector = bool((fund.get("sector") or "").strip())
    has_market_cap = fund.get("market_cap") is not None
    name_lower = name_str.lower()
    looks_like_fund = any(
        token in name_lower for token in ("etf", "fund", "trust", "etn")
    )
    if looks_like_fund and not has_sector and not has_market_cap:
        return InstrumentClassification(
            ticker=ticker,
            warning="non_stock_instrument",
            reason=(
                f"'{name_str}' appears to be an ETF / fund / trust "
                "(no sector or market cap reported by yfinance). The "
                "composite scoring is calibrated for individual "
                "equities and is not directly applicable."
            ),
        )

    return InstrumentClassification(
        ticker=ticker, warning=None, reason=None,
    )


# Threshold below which the analyzer chain can't reliably produce
# technical/statistical/alpha158 sub-scores. 252 ≈ one trading year —
# comfortably above the longest indicator window (200-SMA) with a
# buffer for warmup bars. Recent-IPO tickers trip this gate until they
# accumulate enough history.
MIN_HISTORY_DAYS = 252


def evaluate_history(
    price_data: Optional[pd.DataFrame],
    min_days: int = MIN_HISTORY_DAYS,
) -> tuple[bool, int]:
    """Return ``(insufficient, bars_available)``.

    ``insufficient`` is True when the price frame is non-empty but
    shorter than ``min_days`` — meaning the technical / statistical /
    alpha158 analyzers couldn't reliably produce sub-scores.

    ``price_data=None`` is treated as "untested" (insufficient=False,
    bars=0), NOT "insufficient" — the caller didn't measure history,
    so we don't have evidence to flag. The composite engine's
    ``score_valid`` flag already catches the "no analyzer fired" case
    in that path. Empty DataFrames, by contrast, ARE flagged because
    we DID measure and found zero bars.
    """
    if price_data is None:
        return False, 0
    if price_data.empty:
        return True, 0
    bars = len(price_data)
    return (bars < min_days, bars)
