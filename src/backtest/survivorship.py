"""Bessembinder-style survivorship-bias haircut model.

Tier-1 audit #5 follow-on. Every universe ticker list in the project
(``russell_1000_tickers.txt``, ``config/sectors.yaml`` themes,
watchlists) is a present-day snapshot. Stocks that delisted / went
bankrupt / were acquired before today are excluded entirely, so the
return distribution the backtester samples is right-truncated. Headline
Sharpe / CAGR are biased UPWARD by an unknown amount.

The proper fix is point-in-time index membership (CRSP / Norgate /
Sharadar — paid data). Until that's wired up, this module computes a
universe-aware HAIRCUT and adds adjusted-summary fields to the backtest
result. The headline numbers stay untouched (don't surprise consumers);
the adjusted numbers travel alongside in
``result.data_quality.survivorship_bias.adjusted_summary``.

Defaults sourced from:
  * Bessembinder 2018, "Do Stocks Outperform Treasury Bills?"
  * Brown/Goetzmann/Ross 1995, "Survival" (Journal of Finance)
  * Practitioner consensus: 1-3%/yr on large-cap, more on small-cap.

These are CONSERVATIVE central estimates. A truly hot/concentrated
basket (e.g. an AI-themes list curated in 2024) likely has more bias
than the default; bumping the haircut up is honest.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SurvivorshipHaircut:
    """Magnitude estimate of the upward bias in headline backtest metrics.

    ``annual_return_haircut_pct``: subtract from CAGR and from
    annualized return; multiplied by the period-in-years to get the
    total-return adjustment.

    ``sharpe_haircut``: subtract directly from headline Sharpe. This is
    a simplification — the underlying mechanism (delisting events with
    catastrophic returns) widens the return distribution AND lowers its
    mean, so a flat Sharpe haircut understates the effect at the tails.
    Conservative central estimates per BGR 1995 / Bessembinder 2018.
    """

    annual_return_haircut_pct: float
    sharpe_haircut: float
    rationale: str
    """Free-form one-liner: what universe + what literature this haircut
    is derived from, e.g. 'large-cap US, Bessembinder 2018'."""


# Conservative defaults. Operator can override via BacktestConfig.
_DEFAULTS: dict[str, SurvivorshipHaircut] = {
    # Large-cap broad indices. Bias is real but moderate — index
    # reconstitution churns ~5%/yr but most exits are by merger/buyout
    # rather than bankruptcy, and the merger returns are usually neutral
    # to mildly positive.
    "russell_1000": SurvivorshipHaircut(
        annual_return_haircut_pct=2.0,
        sharpe_haircut=0.20,
        rationale="large-cap broad index, Bessembinder 2018 / BGR 1995",
    ),
    "sp500": SurvivorshipHaircut(
        annual_return_haircut_pct=2.0,
        sharpe_haircut=0.20,
        rationale="large-cap broad index, Bessembinder 2018 / BGR 1995",
    ),
    # Small-cap. More frequent delisting, more bankruptcy-driven exits,
    # bigger left-tail mass that survivor-only data discards.
    "russell_2000": SurvivorshipHaircut(
        annual_return_haircut_pct=3.0,
        sharpe_haircut=0.30,
        rationale="small-cap broad index, BGR 1995 (small-cap survivor bias > large)",
    ),
    # Hand-curated baskets (themes, watchlist). These are MORE biased
    # than indexes because the operator picked the names with the
    # benefit of hindsight — selection bias compounds survivorship bias.
    # A "hot-tech themes" basket curated in 2024 implicitly excludes
    # every tech name that flamed out 2020-2023.
    "themes": SurvivorshipHaircut(
        annual_return_haircut_pct=3.0,
        sharpe_haircut=0.30,
        rationale="hand-curated basket, selection bias on top of survivor bias",
    ),
    "watchlist": SurvivorshipHaircut(
        annual_return_haircut_pct=3.0,
        sharpe_haircut=0.30,
        rationale="hand-curated basket, selection bias on top of survivor bias",
    ),
    "value_cohort": SurvivorshipHaircut(
        annual_return_haircut_pct=3.0,
        sharpe_haircut=0.30,
        rationale="hand-curated basket, selection bias on top of survivor bias",
    ),
}


# Used when the operator didn't specify a universe label. Tracks the
# WORST defensible haircut so an unknown universe doesn't quietly land
# at "best case" defaults.
_CONSERVATIVE_FALLBACK = SurvivorshipHaircut(
    annual_return_haircut_pct=3.0,
    sharpe_haircut=0.30,
    rationale="unknown universe; using conservative fallback (small-cap-level haircut)",
)


def default_haircut_for_universe(universe_label: str | None) -> SurvivorshipHaircut:
    """Return the canonical haircut for a universe label.

    Unknown / None labels return the conservative fallback rather than
    the most-optimistic default — an operator should HAVE to know what
    universe they're testing on to claim a smaller bias.
    """
    if not universe_label:
        return _CONSERVATIVE_FALLBACK
    key = universe_label.strip().lower()
    return _DEFAULTS.get(key, _CONSERVATIVE_FALLBACK)


def adjust_total_return_pct(headline_pct: float, years: float, haircut: SurvivorshipHaircut) -> float:
    """Apply the cumulative return haircut over the window.

    Done in arithmetic-percent space (matches how the existing summary
    reports total_return_pct). For a 2y themes backtest with a 3%/yr
    haircut: total return drops by 6 percentage points.
    """
    return headline_pct - haircut.annual_return_haircut_pct * years


def adjust_cagr_pct(headline_pct: float, haircut: SurvivorshipHaircut) -> float:
    """Subtract the annual haircut from CAGR directly."""
    return headline_pct - haircut.annual_return_haircut_pct


def adjust_sharpe(headline_sharpe: float, haircut: SurvivorshipHaircut) -> float:
    """Flat Sharpe haircut. Documented simplification (see docstring above)."""
    return headline_sharpe - haircut.sharpe_haircut


def adjusted_summary_block(
    *,
    total_return_pct: float | None,
    cagr_pct: float | None,
    ann_sharpe: float | None,
    years: float,
    haircut: SurvivorshipHaircut,
) -> dict:
    """Build a survivorship-adjusted version of ONE section's summary.

    Returns the adjusted metric values for that section (full OR OOS,
    not both — the caller picks which). Missing inputs propagate as None
    so the adjusted block never claims a number we didn't have.
    """

    def _maybe(fn, value, *args):
        return None if value is None else round(fn(value, *args), 2)

    return {
        "total_return_pct": _maybe(
            adjust_total_return_pct, total_return_pct, years, haircut,
        ),
        "cagr_pct": _maybe(adjust_cagr_pct, cagr_pct, haircut),
        "ann_sharpe": _maybe(adjust_sharpe, ann_sharpe, haircut),
        "haircut_applied": {
            "annual_return_haircut_pct": haircut.annual_return_haircut_pct,
            "sharpe_haircut": haircut.sharpe_haircut,
            "rationale": haircut.rationale,
        },
    }
