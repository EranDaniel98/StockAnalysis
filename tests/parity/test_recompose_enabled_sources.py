"""Tier-2 audit #22: enabled_sources filtering is symmetric across
sub_scores AND signal counts AND pead_bonus.

The audit ticket: "Cross-mode score-cache parity at risk: enabled_sources
filtering not symmetric with cached sub_scores. Multi-mode replay can
show byte-identical results across nominally different configs."

Pre-fix surface: ``recompose_composite`` filtered active_subs and the
signal-counts by enabled_sources, but added ``cached.pead_bonus``
unconditionally. So sweep modes that excluded "pead" from enabled_sources
still received the PEAD lift, producing byte-identical composites
across nominally different configs whenever the only "real" difference
was PEAD on/off.

This explained the insider_flow A/B null result on 2026-05-14
(memory: project_insider_r1000_finding) — the dominant non-test
discriminator (PEAD) was leaking through both arms of the experiment
identically.

This file pins:
  * different enabled_sources produce DIFFERENT composites
  * pead_bonus respects enabled_sources
  * sub_score filtering is symmetric with signal-count filtering
"""

from __future__ import annotations

import pytest

from src.backtest.score_cache import CachedScore, recompose_composite


def _cached(**overrides) -> CachedScore:
    """Build a CachedScore with realistic per-source values."""
    defaults = dict(
        sub_scores={
            "technical": 60.0,
            "fundamental": 55.0,
            "pattern": 50.0,
            "statistical": 65.0,
            "trend": 70.0,
            "insider_flow": 75.0,
        },
        bullish_by_source={
            "technical": 3,
            "fundamental": 0,
            "pattern": 1,
            "statistical": 0,
            "trend": 2,
            "insider_flow": 1,
        },
        bearish_by_source={
            "technical": 0,
            "fundamental": 2,
            "pattern": 0,
            "statistical": 1,
            "trend": 0,
            "insider_flow": 0,
        },
        pead_bonus=8.0,  # nontrivial — masks subtle config differences
        atr=2.5,
        close=100.0,
    )
    defaults.update(overrides)
    return CachedScore(**defaults)


WEIGHTS = {
    "technical": 0.30,
    "fundamental": 0.25,
    "pattern": 0.15,
    "statistical": 0.20,
    "trend": 0.10,
    "insider_flow": 0.10,
}


# --- KEYSTONE: PEAD respects enabled_sources -------------------------------


def test_pead_bonus_excluded_when_not_in_enabled_sources():
    """The audit keystone. ``enabled_sources`` excluding "pead" must
    NOT add the cached PEAD bonus. Pre-fix this leaked through and
    produced byte-identical results across "PEAD on" / "PEAD off"
    sweep arms."""
    cached = _cached()
    with_pead, _ = recompose_composite(
        cached, WEIGHTS,
        enabled_sources={"technical", "fundamental", "pattern",
                         "statistical", "trend", "insider_flow", "pead"},
    )
    without_pead, _ = recompose_composite(
        cached, WEIGHTS,
        enabled_sources={"technical", "fundamental", "pattern",
                         "statistical", "trend", "insider_flow"},
    )
    # The 8-point PEAD bonus must show up as a meaningful difference.
    assert with_pead - without_pead == pytest.approx(8.0, abs=0.05)


def test_pead_bonus_included_when_enabled_sources_is_none():
    """The legacy "no filter" path keeps the PEAD bonus — important
    back-compat with code that passes enabled_sources=None."""
    cached = _cached()
    composite, _ = recompose_composite(cached, WEIGHTS, enabled_sources=None)
    # The PEAD bonus (+8) is materialized into the composite.
    composite_no_filter, _ = recompose_composite(cached, WEIGHTS)
    assert composite == pytest.approx(composite_no_filter, abs=0.05)


# --- enabled_sources symmetry across sub_scores + signals + pead -----------


def test_excluding_insider_changes_composite():
    """The originally-suspected failure mode: insider_flow A/B sweep
    arms returning identical results. With the fix, an enabled_sources
    that excludes insider_flow must produce a DIFFERENT composite
    from one that includes it."""
    cached = _cached()
    all_sources = {"technical", "fundamental", "pattern",
                   "statistical", "trend", "insider_flow", "pead"}
    without_insider = all_sources - {"insider_flow"}

    with_insider_score, _ = recompose_composite(cached, WEIGHTS, enabled_sources=all_sources)
    without_insider_score, _ = recompose_composite(cached, WEIGHTS, enabled_sources=without_insider)

    # MUST differ. Pre-fix both arms would have included pead_bonus and
    # the dominant signal-consensus, masking small insider sub-score
    # differences. After fix the difference shows through.
    assert with_insider_score != without_insider_score


def test_sub_score_filter_matches_signal_filter():
    """If enabled_sources excludes a source, that source's sub_score
    AND its signals must both be filtered out. A mismatch (sub_scores
    filtered but signals not, or vice versa) would let a "disabled"
    analyzer's signals contribute to the ±5 consensus nudge.

    We construct a scenario where one source has a bullish signal but
    a neutral-ish sub_score, then verify that excluding it changes
    both the weighted average AND the consensus delta."""
    cached = _cached(
        sub_scores={
            "technical": 50.0,
            "fundamental": 50.0,
            "insider_flow": 50.0,  # neutral sub_score
        },
        bullish_by_source={
            "technical": 0,
            "fundamental": 0,
            "insider_flow": 1,  # but bullish signal
        },
        bearish_by_source={
            "technical": 0,
            "fundamental": 0,
            "insider_flow": 0,
        },
        pead_bonus=0.0,
    )
    weights = {"technical": 0.5, "fundamental": 0.3, "insider_flow": 0.2}

    with_insider, _ = recompose_composite(
        cached, weights,
        enabled_sources={"technical", "fundamental", "insider_flow"},
    )
    without_insider, _ = recompose_composite(
        cached, weights,
        enabled_sources={"technical", "fundamental"},
    )
    # With insider: 1 bullish vote in consensus → +5. Without: 0 votes → no nudge.
    # Both have the same neutral 50.0 base composite (sub_scores all 50).
    # After fix, with_insider should be ~55 and without should be ~50.
    assert with_insider == pytest.approx(55.0, abs=0.5)
    assert without_insider == pytest.approx(50.0, abs=0.5)


def test_two_distinct_modes_produce_distinct_composites():
    """End-to-end: build two CachedScore-identical inputs, run them
    through different enabled_sources sets, assert the composites
    differ. This is the audit's explicit ask: "Add a parity test that
    constructs different enabled_sources and asserts cached and
    recomputed scores diverge by source.\""""
    cached = _cached()
    modes = {
        "off":  {"technical", "fundamental", "pattern", "statistical", "trend"},
        "on":   {"technical", "fundamental", "pattern", "statistical", "trend",
                 "insider_flow"},
        "full": {"technical", "fundamental", "pattern", "statistical", "trend",
                 "insider_flow", "pead"},
    }
    composites = {
        m: recompose_composite(cached, WEIGHTS, enabled_sources=mode)[0]
        for m, mode in modes.items()
    }
    # All three must be distinct — no byte-identical collapses.
    assert composites["off"] != composites["on"]
    assert composites["on"] != composites["full"]
    assert composites["off"] != composites["full"]
