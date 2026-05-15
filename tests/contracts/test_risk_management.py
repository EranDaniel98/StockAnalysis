"""Type-safety contract on RiskManagement / StopLossSpec / TakeProfitSpec.

Covers Tier-1 audit #6 (D#17 + T#5 + X#7): the legacy repository read
`stop_loss` via `isinstance(rm.stop_loss, dict)`. A future caller that
passed a typed Pydantic submodel bypassed the check and the paper trade
shipped with no stop loss. After this fix:

  * RiskManagement.stop_loss is StopLossSpec | None (typed)
  * model_validator coerces legacy dict input so the recommender's
    historical dict-returning shape still constructs cleanly
  * extract_stop_loss_price / extract_take_profit_price accept BOTH
    typed specs and legacy dicts, and raise on truly unrecognized shapes
"""

from __future__ import annotations

import pytest

from src.contracts.entities.recommendation import (
    RiskManagement,
    StopLossSpec,
    TakeProfitSpec,
    extract_stop_loss_price,
    extract_take_profit_price,
)


# --- StopLossSpec / TakeProfitSpec construction ----------------------------


def test_stop_loss_spec_round_trips():
    spec = StopLossSpec(
        method="atr",
        price=95.0,
        pct_from_current=-5.0,
        detail="ATR(2x): $95.00",
    )
    assert spec.method == "atr"
    assert spec.price == 95.0


def test_stop_loss_spec_rejects_zero_price():
    """A stop loss at $0 means "no stop" — never accept it silently."""
    with pytest.raises(Exception):  # noqa: BLE001 — pydantic raises ValidationError
        StopLossSpec(method="atr", price=0.0, pct_from_current=-100.0)


def test_stop_loss_spec_rejects_unknown_method():
    with pytest.raises(Exception):
        StopLossSpec(method="kelly", price=95.0, pct_from_current=-5.0)  # type: ignore[arg-type]


# --- RiskManagement validator coercion -------------------------------------


def test_risk_management_coerces_legacy_dict_stop_loss():
    """The recommender historically returned a dict; RiskManagement must
    accept it without an explicit conversion."""
    rm = RiskManagement(
        current_price=100.0,
        stop_loss={"method": "atr", "price": 95.0, "pct_from_current": -5.0, "detail": "ATR(2x)"},
        take_profit={"method": "risk_reward", "price": 115.0, "pct_from_current": 15.0, "detail": "R:R 3:1"},
    )
    assert isinstance(rm.stop_loss, StopLossSpec)
    assert rm.stop_loss.price == 95.0
    assert isinstance(rm.take_profit, TakeProfitSpec)


def test_risk_management_accepts_typed_specs():
    rm = RiskManagement(
        current_price=100.0,
        stop_loss=StopLossSpec(method="atr", price=95.0, pct_from_current=-5.0),
        take_profit=TakeProfitSpec(method="risk_reward", price=115.0, pct_from_current=15.0),
    )
    assert rm.stop_loss.price == 95.0


def test_risk_management_empty_dict_becomes_none():
    """Legacy callers occasionally hand back {} for stop_loss when the
    analyzer couldn't compute one. That's not a stop — it's a missing
    stop. Coerce to None so downstream gates skip the trade."""
    rm = RiskManagement(current_price=100.0, stop_loss={}, take_profit={})
    assert rm.stop_loss is None
    assert rm.take_profit is None


def test_risk_management_dict_without_price_becomes_none():
    """A dict that lacks a price (analyzer half-filled it) is not a
    usable stop. Coerce to None rather than letting the spec validator
    raise — that would crash the whole recommendation construction."""
    rm = RiskManagement(current_price=100.0, stop_loss={"method": "atr"})
    assert rm.stop_loss is None


def test_risk_management_rejects_garbage_stop_loss():
    """A non-dict, non-spec value is a real bug — raise loudly."""
    with pytest.raises(Exception):
        RiskManagement(current_price=100.0, stop_loss="not a stop")  # type: ignore[arg-type]


# --- extract_*_price helpers (the keystone) --------------------------------


def test_extract_stop_loss_price_from_typed_spec():
    """The bug fix in one assertion: a typed spec must yield the price,
    NOT silently return None as the old isinstance(dict) check did."""
    spec = StopLossSpec(method="atr", price=95.0, pct_from_current=-5.0)
    rm = RiskManagement(current_price=100.0, stop_loss=spec)
    assert extract_stop_loss_price(rm) == 95.0


def test_extract_stop_loss_price_from_legacy_dict():
    """Until the recommender emits typed specs natively, the repo will
    see RiskManagement instances built from legacy dicts. After the
    coercer fires, stop_loss is a StopLossSpec — but the helper must
    still work if a downstream test passes a raw dict directly."""
    raw = {"stop_loss": {"price": 95.0, "method": "atr"}}
    assert extract_stop_loss_price(raw) == 95.0


def test_extract_stop_loss_price_handles_none():
    assert extract_stop_loss_price(None) is None
    rm = RiskManagement(current_price=100.0)
    assert extract_stop_loss_price(rm) is None


def test_extract_stop_loss_price_raises_on_garbage():
    """Future divergence must be loud. If the shape changes again, the
    repository call site fails fast instead of writing a stop-less row."""
    raw = {"stop_loss": "not a spec or dict"}
    with pytest.raises(TypeError, match="stop_loss"):
        extract_stop_loss_price(raw)


def test_extract_take_profit_price_symmetry():
    spec = TakeProfitSpec(method="resistance", price=115.0, pct_from_current=15.0)
    rm = RiskManagement(current_price=100.0, take_profit=spec)
    assert extract_take_profit_price(rm) == 115.0


# --- Recommendation legacy_dict round-trip ---------------------------------


def test_recommendation_legacy_dict_emits_flat_subdicts():
    """Existing CLI / paper_trade_service code reads
    legacy_dict()["risk_management"]["stop_loss"]["price"] — that path
    must keep working after the typed-spec migration."""
    rm = RiskManagement(
        current_price=100.0,
        stop_loss={"method": "atr", "price": 95.0, "pct_from_current": -5.0, "detail": ""},
        take_profit={"method": "risk_reward", "price": 115.0, "pct_from_current": 15.0, "detail": ""},
    )

    from src.contracts.entities.recommendation import Recommendation
    rec = Recommendation(
        ticker="AAPL",
        action="BUY",
        composite_score=70.0,
        confidence="High",
        risk_management=rm,
    )
    legacy = rec.legacy_dict()
    assert legacy["risk_management"]["stop_loss"]["price"] == 95.0
    assert legacy["risk_management"]["take_profit"]["price"] == 115.0
    assert legacy["risk_management"]["stop_loss"]["method"] == "atr"
