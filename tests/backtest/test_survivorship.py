"""Survivorship-bias haircut contract.

Tier-1 audit #5 follow-on. The headline flag was already surfaced; this
module ships the QUANTITATIVE adjustment so operators see a credible
lower bound (haircut-adjusted Sharpe / CAGR) alongside the headline
biased number.

Haircut magnitudes come from Bessembinder 2018 / BGR 1995; the
``rationale`` field on each haircut documents the citation.
"""

from __future__ import annotations

from src.backtest.survivorship import (
    SurvivorshipHaircut,
    adjust_cagr_pct,
    adjust_sharpe,
    adjust_total_return_pct,
    adjusted_summary_block,
    default_haircut_for_universe,
)


# --- default_haircut_for_universe -----------------------------------------


def test_known_large_cap_universe_gets_modest_haircut():
    h = default_haircut_for_universe("russell_1000")
    assert h.annual_return_haircut_pct == 2.0
    assert h.sharpe_haircut == 0.20
    assert "large-cap" in h.rationale.lower()


def test_small_cap_universe_gets_larger_haircut_than_large_cap():
    large = default_haircut_for_universe("russell_1000")
    small = default_haircut_for_universe("russell_2000")
    assert small.annual_return_haircut_pct > large.annual_return_haircut_pct
    assert small.sharpe_haircut > large.sharpe_haircut


def test_curated_basket_gets_extra_haircut_for_selection_bias():
    """Themes / watchlist / value_cohort are operator-curated baskets.
    They suffer both survivorship AND selection bias, so the default
    haircut should match small-cap-level, not large-cap."""
    themes = default_haircut_for_universe("themes")
    large = default_haircut_for_universe("russell_1000")
    assert themes.annual_return_haircut_pct > large.annual_return_haircut_pct
    assert "selection bias" in themes.rationale.lower()


def test_unknown_universe_falls_back_to_conservative():
    """An unspecified universe must NOT fall through to the smallest
    haircut — that would let an operator silently claim the optimistic
    case. Default to the small-cap-level haircut for the unknown case."""
    fallback = default_haircut_for_universe("ye-olde-mystery-universe")
    large = default_haircut_for_universe("russell_1000")
    assert fallback.annual_return_haircut_pct >= large.annual_return_haircut_pct


def test_none_universe_falls_back_to_conservative():
    fallback = default_haircut_for_universe(None)
    assert fallback.annual_return_haircut_pct >= 2.0


def test_universe_label_is_case_insensitive():
    """An operator typing 'Russell_1000' (capitalized) must get the
    right haircut, not the conservative fallback. Otherwise the
    'specify a universe' rule has a usability pothole."""
    assert (
        default_haircut_for_universe("russell_1000").rationale
        == default_haircut_for_universe("Russell_1000").rationale
    )


# --- adjustment math -------------------------------------------------------


def test_total_return_haircut_scales_with_window_length():
    """A 3y backtest at 2%/yr haircut should drop total return by 6pp,
    not 2pp."""
    haircut = SurvivorshipHaircut(2.0, 0.20, rationale="test")
    assert adjust_total_return_pct(40.0, years=3.0, haircut=haircut) == 34.0


def test_cagr_haircut_is_flat():
    """CAGR is already annualized; the haircut subtracts directly."""
    haircut = SurvivorshipHaircut(2.0, 0.20, rationale="test")
    assert adjust_cagr_pct(12.0, haircut) == 10.0


def test_sharpe_haircut_is_flat():
    import pytest as _pt
    haircut = SurvivorshipHaircut(2.0, 0.20, rationale="test")
    assert adjust_sharpe(1.84, haircut) == _pt.approx(1.64)


# --- adjusted_summary_block ------------------------------------------------


def test_adjusted_summary_propagates_haircut_metadata():
    haircut = default_haircut_for_universe("themes")
    block = adjusted_summary_block(
        total_return_pct=40.0,
        cagr_pct=12.0,
        ann_sharpe=1.84,
        years=3.0,
        haircut=haircut,
    )
    # 3y * 3%/yr haircut = -9pp on total return.
    assert block["total_return_pct"] == 31.0
    assert block["cagr_pct"] == 9.0  # 12 - 3
    assert block["ann_sharpe"] == 1.54  # 1.84 - 0.30
    # Magnitudes embed in the block so a dashboard can render them
    # without having to know the haircut model.
    applied = block["haircut_applied"]
    assert applied["annual_return_haircut_pct"] == 3.0
    assert applied["sharpe_haircut"] == 0.30
    assert applied["rationale"]


def test_adjusted_summary_handles_missing_inputs():
    """A section with only some headline metrics (e.g. early in the
    walk where Sharpe wasn't computable yet) must NOT fabricate numbers
    for the missing fields."""
    haircut = default_haircut_for_universe("russell_1000")
    block = adjusted_summary_block(
        total_return_pct=20.0,
        cagr_pct=None,
        ann_sharpe=None,
        years=1.0,
        haircut=haircut,
    )
    assert block["total_return_pct"] == 18.0
    assert block["cagr_pct"] is None
    assert block["ann_sharpe"] is None
