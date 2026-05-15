"""Data-quality block contract on the backtest result.

Covers Tier-1 audit finding #5 (Q#3 / Q-cross): the survivorship-bias
warning used to live only in a free-text `warnings` list, which
dashboards and sweep history quietly dropped. The structured
`data_quality.survivorship_bias` block makes the bias impossible to
ignore visually until we adopt point-in-time index membership.

Tests target the helper directly so they don't depend on a full
run_backtest invocation (which needs price history + fundamentals).
"""

from __future__ import annotations

from src.backtest.engine import (
    PIPELINE_VERSION,
    _build_data_quality_block,
)


def test_survivorship_bias_flag_is_present_and_uncorrected():
    block = _build_data_quality_block(n_tickers_traded=12)
    sb = block["survivorship_bias"]
    assert sb["applies"] is True
    assert sb["severity"] == "uncorrected"
    # Magnitude hint must mention a numeric range so a downstream dashboard
    # can't pretend the bias is unquantifiable.
    assert any(c.isdigit() for c in sb["magnitude_hint_annual_pct"])
    # Remediation must name a PIT source so future-me knows the fix path.
    assert "point-in-time" in sb["remediation"].lower()


def test_data_quality_has_pipeline_version():
    """Every result must stamp the pipeline version so memory entries can
    say 'this number came from commit X' instead of just 'this number
    came from a sweep'. The string must include the date stamp so
    operators can sort sweep runs by pipeline epoch."""
    block = _build_data_quality_block(n_tickers_traded=0)
    assert block["pipeline_version"] == PIPELINE_VERSION
    # Anchored to a YYYY-MM-DD prefix so the stamp is sortable.
    assert PIPELINE_VERSION.startswith("2026-")


def test_n_tickers_traded_propagates():
    block = _build_data_quality_block(n_tickers_traded=37)
    assert block["n_tickers_traded"] == 37
    assert isinstance(block["n_tickers_traded"], int)


def test_block_shape_is_stable():
    """Frontend / dashboard contracts depend on these keys staying put.
    Renaming a key is a breaking change — bump PIPELINE_VERSION and
    update consumers if you ever flip this."""
    block = _build_data_quality_block(n_tickers_traded=1)
    assert set(block.keys()) == {
        "pipeline_version",
        "survivorship_bias",
        "n_tickers_traded",
    }
    assert set(block["survivorship_bias"].keys()) == {
        "applies", "severity", "magnitude_hint_annual_pct",
        "source", "details", "remediation",
    }
