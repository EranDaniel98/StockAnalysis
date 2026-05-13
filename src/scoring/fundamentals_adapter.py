"""Bridge typed PIT `FundamentalSnapshot` rows into the dict shape that
``src.scoring.analyzers.fundamental.analyze`` consumes.

The analyzer was written against the yfinance dict (keys like ``pe_trailing``,
``revenue_growth``, ``gross_margins``). EDGAR rows arrive as typed
``FundamentalSnapshot`` instances with slightly different names and a narrower
field set. This module owns the mapping.

What's intentionally NOT here:
- PE / PB / PS / EV-EBITDA: EDGAR has no price; these need a price-at-as_of
  multiplier on top of EPS / book / sales. See ``snapshot_to_analyzer_dict``
  signature — it accepts an optional ``price`` and computes ``pe_trailing``
  on the fly when both EPS and price are available.
- Dividend yield: needs trailing-12mo dividends per share / price, not in
  EDGAR concept_map yet.
- Analyst recommendation/target_price: yfinance-only fields with no PIT
  analog. The caller may layer those in by merging a current-snapshot dict
  on top of this output.
- Sector/industry/market_cap: same story — current-snapshot fields.
"""

from __future__ import annotations

from typing import Any

from src.contracts.entities.fundamentals import FundamentalSnapshot

# Overlay keys that are safe to carry from a current-snapshot dict into a PIT
# backtest. These are either truly time-invariant (sector, industry, name) or
# information that EDGAR doesn't expose at all and that backtest paths choose
# to accept as "approximate snapshot" rather than omit (analyst sentiment,
# dividend metadata). Time-varying numeric fields like ``pe_trailing``,
# ``debt_to_equity``, ``profit_margin`` MUST NOT be overlaid — they would
# reintroduce the look-ahead leak EDGAR exists to eliminate.
PIT_SAFE_OVERLAY_KEYS: frozenset[str] = frozenset({
    "sector",
    "industry",
    "name",
    "market_cap",      # changes daily with price but isn't used by the analyzer's score path
    "dividend_yield",  # yfinance-only; no EDGAR concept yet
    "payout_ratio",    # yfinance-only
    "recommendation",
    "num_analyst_opinions",
    "target_mean_price",
    "target_high_price",
    "target_low_price",
    "fifty_day_avg",   # analyst-score uses this for upside math
    "two_hundred_day_avg",
    "beta",
    "eps_ttm",         # adapter hint, not an analyzer field
})


def snapshot_to_analyzer_dict(
    snapshot: FundamentalSnapshot | None,
    *,
    price: float | None = None,
    overlay: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Translate one PIT snapshot to the analyzer's dict shape.

    Args:
        snapshot: PIT row (or None — returns just the overlay).
        price: as-of close price for PE computation. When supplied alongside
            ``eps_diluted``, ``pe_trailing = price / eps_diluted``. The
            value here is a single-quarter EPS — strictly the PE should use
            trailing-twelve-months EPS, but with a 4-quarter rolling sum we'd
            need cross-row state. Quarterly PE is a reasonable first pass;
            callers building the PIT lookup can sum 4 quarters and pass the
            TTM EPS via ``overlay={"eps_ttm": ...}`` if they want strict TTM.
        overlay: extra fields layered on top of the snapshot — typically a
            current-snapshot dict carrying sector / industry / analyst data
            that have no PIT analog. Overlay wins on key collision so the
            caller can deliberately replace stale numeric fields.

    Returns:
        A dict with the keys ``analyze`` consumes. Missing fields stay
        absent (not None) so the analyzer's ``fund.get(...)`` returns None
        and that category skips cleanly.
    """
    out: dict[str, Any] = {}
    if snapshot is not None:
        # --- profitability ---
        if snapshot.roe is not None:
            out["roe"] = snapshot.roe
        if snapshot.roa is not None:
            out["roa"] = snapshot.roa
        if snapshot.profit_margin is not None:
            out["profit_margin"] = snapshot.profit_margin
        if snapshot.operating_margin is not None:
            out["operating_margin"] = snapshot.operating_margin
        if snapshot.gross_margin is not None:
            # analyzer reads `gross_margins` (plural) — yfinance naming
            out["gross_margins"] = snapshot.gross_margin

        # --- growth ---
        if snapshot.revenue_growth_yoy is not None:
            out["revenue_growth"] = snapshot.revenue_growth_yoy
        if snapshot.earnings_growth_yoy is not None:
            out["earnings_growth"] = snapshot.earnings_growth_yoy

        # --- balance sheet / health ---
        if snapshot.debt_to_equity is not None:
            out["debt_to_equity"] = snapshot.debt_to_equity
        if snapshot.current_ratio is not None:
            out["current_ratio"] = snapshot.current_ratio
        if snapshot.free_cash_flow is not None:
            out["free_cash_flow"] = snapshot.free_cash_flow
        if snapshot.total_cash is not None:
            out["total_cash"] = snapshot.total_cash
        if snapshot.total_debt is not None:
            out["total_debt"] = snapshot.total_debt

        # --- valuation: only computable with price + EPS ---
        if (
            price is not None
            and snapshot.eps_diluted is not None
            and snapshot.eps_diluted > 0
        ):
            # Quarterly EPS produces a PE 4x the TTM PE. Multiply by 4 for a
            # rough TTM approximation when caller hasn't supplied eps_ttm.
            eps_ttm = (overlay or {}).get("eps_ttm")
            if eps_ttm is None or eps_ttm <= 0:
                eps_ttm = float(snapshot.eps_diluted) * 4
            out["pe_trailing"] = float(price) / eps_ttm

        # --- categorical (present when EDGAR has them) ---
        if snapshot.sector:
            out["sector"] = snapshot.sector
        if snapshot.industry:
            out["industry"] = snapshot.industry
        if snapshot.market_cap is not None:
            out["market_cap"] = snapshot.market_cap
        if snapshot.name:
            out["name"] = snapshot.name

        # --- dividend (currently never populated from EDGAR concept_map) ---
        if snapshot.dividend_yield is not None:
            out["dividend_yield"] = snapshot.dividend_yield
        if snapshot.payout_ratio is not None:
            out["payout_ratio"] = snapshot.payout_ratio

    if overlay:
        # Overlay last so caller-supplied current-snapshot fields (sector,
        # analyst recommendation, etc.) win over EDGAR's blanks.
        for k, v in overlay.items():
            if k == "eps_ttm":
                continue  # internal hint, not an analyzer field
            if v is None:
                continue
            out[k] = v

    return out
