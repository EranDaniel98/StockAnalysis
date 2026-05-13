"""Options-skew (IV-asymmetry) analyzer.

Implements a Bates (1991) / Bollen-Whaley (2004) / Xing-Zhang-Zhao
(2010) style read on the option chain: when at-the-money puts trade at
materially higher implied volatility than calls of the same expiry,
the market is paying up for downside protection and Xing et al. show
this predicts negative underlying returns over the next 1-3 months.
The symmetric (put-IV ~= call-IV) case is the neutral baseline; the
rare reverse-skew case (calls > puts) flags speculative call demand
and tends to be near-term bullish.

LIVE-ONLY NOTICE
================
This analyzer is intentionally NOT wired into the backtest engine.
yfinance — and every other free chain feed — exposes only the CURRENT
options snapshot. Historical chain data lives behind paid feeds
(CBOE DataShop, ORATS, OptionMetrics). Running this signal in
backtest would silently use a stale or look-ahead snapshot. It runs
in the live scan path only; ``src/scoring/engine.py`` wires it on
the scan side and explicitly excludes it on the backtest side.

Pure function over a caller-supplied ``OptionsChain`` so the unit
tests can hand-build synthetic chains with no yfinance dependency.
Same return-shape convention as the rest of the analyzer suite:

  ``analyze(options_chain, *, current_price, params=None) -> dict | None``

Return shape on signal:
  ``{"score": int 0-100, "signals": [...], "put_call_iv_ratio": float,
     "put_call_volume_ratio": float, "25_delta_skew": float | None,
     "indicators": {...}}``

Returns ``None`` (composite engine skips the sub-score) when the chain
is too thin to read — empty, missing IV on the ATM legs, no strikes
within 10% of the underlying, or no expiry at-least-21-days out.
Forcing a neutral 50 into the composite when we really have no read
would dilute every other signal; silence is the convention here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Optional


# ---------------------------------------------------------------------------
# Data contracts. Frozen so the analyzer can't mutate caller-owned state and
# so the test suite can rely on hashability / equality.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OptionContract:
    """A single option line. ``delta`` is optional because many free
    feeds (yfinance included) don't publish per-contract greeks — when
    deltas are present we compute a 25-delta skew, otherwise we omit
    that field rather than fabricating a synthetic delta."""

    strike: float
    expiry: date
    contract_type: Literal["call", "put"]
    implied_volatility: float
    volume: int
    open_interest: int
    delta: Optional[float] = None


@dataclass(frozen=True)
class OptionsChain:
    """A snapshot of an option chain across all expiries and strikes."""

    underlying: str
    snapshot_time: datetime
    contracts: tuple[OptionContract, ...]


@dataclass(frozen=True)
class OptionsSkewParams:
    """Tunable knobs.

    * ``min_days_to_expiry`` 21 — Xing et al. (2010) and the standard
      VIX construction skip the front week to avoid pin-risk noise and
      gamma-driven IV blowups. 21 calendar days is the conventional
      lower bound for "monthly" implied vol reads.
    * ``max_strike_distance_pct`` 0.10 — if no strike sits within +/-10%
      of spot we treat the chain as too sparse for an ATM read. Most
      liquid US single-name names have 1-2 strikes inside this window.
    * The IV-ratio bands match Bates (1991) skew taxonomy plus our own
      bias-toward-trend score convention so the composite weights
      don't have to special-case this analyzer.
    """

    min_days_to_expiry: int = 21
    max_strike_distance_pct: float = 0.10

    # Score thresholds on put-call IV ratio (atm_put_iv / atm_call_iv).
    reverse_skew_max: float = 0.95          # <= 0.95 = bullish band
    neutral_max: float = 1.05               # (0.95, 1.05) = neutral
    mild_skew_max: float = 1.20             # [1.05, 1.20) = mild bearish
    extreme_skew_min: float = 1.40          # >= 1.40 with vol >= 3.0 -> extreme

    # Score thresholds on put-call volume ratio (put_vol / call_vol).
    bullish_volume_max: float = 0.70        # < 0.70 reinforces bullish band
    neutral_volume_max: float = 1.50        # [0.70, 1.50) is neutral-ish
    mild_volume_max: float = 2.50           # [1.50, 2.50) = mild bearish
    extreme_volume_min: float = 3.00        # >= 3.00 with iv >= 1.40 -> extreme


# ---------------------------------------------------------------------------
# Internal helpers.
# ---------------------------------------------------------------------------


def _snapshot_date(chain: OptionsChain) -> date:
    """Pull the calendar date off the snapshot, tolerating either a
    ``datetime`` or a ``date`` (some upstream feeds normalize to one or
    the other)."""
    snap = chain.snapshot_time
    if isinstance(snap, datetime):
        return snap.date()
    return snap


def _pick_expiry(chain: OptionsChain, params: OptionsSkewParams) -> Optional[date]:
    """Return the NEAREST expiry that is at-least-``min_days_to_expiry``
    out from the snapshot. Returns None when no expiry qualifies — the
    chain is then too short-dated to read cleanly."""
    snap_d = _snapshot_date(chain)
    candidates = {
        c.expiry for c in chain.contracts
        if (c.expiry - snap_d).days >= params.min_days_to_expiry
    }
    if not candidates:
        return None
    return min(candidates)


def _closest_strike_contract(
    contracts: list[OptionContract],
    target_price: float,
) -> Optional[OptionContract]:
    """Pick the contract whose strike is closest to ``target_price``.
    Returns None on an empty input. The literal ``closest`` semantics
    matter: a naive "lowest strike >= price" would systematically pick
    OTM strikes and bias the ATM IV read upward in skewed chains."""
    if not contracts:
        return None
    return min(contracts, key=lambda c: abs(c.strike - target_price))


def _within_window(
    contracts: list[OptionContract],
    current_price: float,
    max_distance_pct: float,
) -> bool:
    """True if at least one contract has a strike within
    +/-``max_distance_pct`` of spot. Guards against the sparse-chain
    failure mode (e.g. a deep ITM-only or far-OTM-only listing)."""
    if not contracts or current_price <= 0:
        return False
    band = current_price * max_distance_pct
    return any(abs(c.strike - current_price) <= band for c in contracts)


def _twenty_five_delta_skew(
    calls: list[OptionContract],
    puts: list[OptionContract],
) -> Optional[float]:
    """IV at -25 delta put minus IV at +25 delta call. Returns None when
    deltas aren't populated on either side — we don't synthesize a
    delta from strike / IV here because the Black-Scholes inversion
    needs a risk-free rate and dividend yield we don't carry in the
    chain contract."""
    delta_calls = [c for c in calls if c.delta is not None]
    delta_puts = [p for p in puts if p.delta is not None]
    if not delta_calls or not delta_puts:
        return None
    call_25 = min(delta_calls, key=lambda c: abs((c.delta or 0.0) - 0.25))
    put_25 = min(delta_puts, key=lambda p: abs((p.delta or 0.0) + 0.25))
    return float(put_25.implied_volatility - call_25.implied_volatility)


def _score_skew(
    iv_ratio: float,
    vol_ratio: float,
    params: OptionsSkewParams,
) -> tuple[int, str, str]:
    """Map (iv_ratio, vol_ratio) to a (score, signal_type, detail).

    Band rationale (Bates 1991 + Xing et al. 2010 + our trend-bias):

    * Reverse skew (calls richer than puts) + light put volume =
      speculative call demand. 70-80 (bullish).
    * Symmetric IV and balanced volume = no read. 50 (neutral).
    * Mild put-IV premium = hedging demand starting. 40-45 (mild bear).
    * Heavy put-IV premium OR heavy put volume = clear bearish skew.
      25-30.
    * Extreme on both legs (IV ratio >= 1.40 AND volume ratio >= 3.0)
      is "fear-tape" territory. Academically this is a *contrarian*
      bullish setup in oversold regimes (the classic VIX-spike buy),
      but our system is daily-rebalance and trend-following — we
      score it bearish (15) for consistency with the rest of the
      stack. A standalone mean-reversion strategy that flips this
      sign is the right place to harvest the contrarian leg; doing
      it here would silently fight the composite trend tilt.
    """

    # Extreme fear — score bearish for trend-stack consistency.
    if iv_ratio >= params.extreme_skew_min and vol_ratio >= params.extreme_volume_min:
        return (
            15,
            "bearish",
            f"Extreme put skew (IV ratio {iv_ratio:.2f}, vol ratio "
            f"{vol_ratio:.2f}; fear tape, Xing et al.)",
        )

    # Heavy put skew on either leg.
    if iv_ratio >= params.mild_skew_max or vol_ratio >= params.mild_volume_max:
        score = 27 if (iv_ratio >= params.mild_skew_max
                       and vol_ratio >= params.mild_volume_max) else 30
        detail = (
            f"Heavy put skew (IV ratio {iv_ratio:.2f}, vol ratio "
            f"{vol_ratio:.2f}; hedging demand, Bates)"
        )
        return score, "bearish", detail

    # Reverse skew + bullish volume = call demand band.
    if iv_ratio <= params.reverse_skew_max and vol_ratio < params.bullish_volume_max:
        score = 78 if iv_ratio <= 0.90 else 72
        detail = (
            f"Reverse skew (IV ratio {iv_ratio:.2f}, vol ratio "
            f"{vol_ratio:.2f}; calls bid, Bollen-Whaley)"
        )
        return score, "bullish", detail

    # Mild put-IV premium without extreme volume.
    if iv_ratio >= params.neutral_max or vol_ratio >= params.neutral_volume_max:
        score = 42 if iv_ratio >= 1.10 else 45
        detail = (
            f"Mild put skew (IV ratio {iv_ratio:.2f}, vol ratio "
            f"{vol_ratio:.2f}; lean bearish)"
        )
        return score, "bearish", detail

    # Symmetric / neutral.
    return (
        50,
        "neutral",
        f"Symmetric IV (ratio {iv_ratio:.2f}, vol ratio {vol_ratio:.2f})",
    )


# ---------------------------------------------------------------------------
# Public entrypoint.
# ---------------------------------------------------------------------------


def analyze(
    options_chain: Optional[OptionsChain],
    *,
    current_price: float,
    params: Optional[OptionsSkewParams] = None,
) -> Optional[dict]:
    """Score a stock's option-skew posture on a 0-100 scale.

    Returns ``None`` when:
      * chain is None / empty;
      * ``current_price`` is missing or non-positive;
      * no expiry sits >= ``min_days_to_expiry`` out;
      * the selected expiry has no strikes within
        ``max_strike_distance_pct`` of spot (chain too sparse);
      * either the ATM call or ATM put has a non-positive IV (treated
        as a missing-data sentinel).

    The composite engine treats ``None`` as "skip this sub-score"
    rather than averaging in a fabricated 50 — same convention as
    insider_flow / alpha158 / RS / sector_flows.
    """
    params = params or OptionsSkewParams()

    if options_chain is None or not options_chain.contracts:
        return None
    if current_price is None or current_price <= 0:
        return None

    expiry = _pick_expiry(options_chain, params)
    if expiry is None:
        return None

    expiry_contracts = [c for c in options_chain.contracts if c.expiry == expiry]
    if not _within_window(
        expiry_contracts, current_price, params.max_strike_distance_pct,
    ):
        return None

    calls = [c for c in expiry_contracts if c.contract_type == "call"]
    puts = [c for c in expiry_contracts if c.contract_type == "put"]
    if not calls or not puts:
        return None

    atm_call = _closest_strike_contract(calls, current_price)
    atm_put = _closest_strike_contract(puts, current_price)
    if atm_call is None or atm_put is None:
        return None
    if atm_call.implied_volatility <= 0 or atm_put.implied_volatility <= 0:
        # Treat zero / negative IV as "data missing" rather than a real
        # quote. yfinance occasionally emits IV=0 on illiquid strikes.
        return None

    iv_ratio = float(atm_put.implied_volatility / atm_call.implied_volatility)

    total_call_volume = sum(int(c.volume or 0) for c in calls)
    total_put_volume = sum(int(p.volume or 0) for p in puts)
    if total_call_volume <= 0:
        # No call flow to normalize against — fall back to OI so the
        # ratio still has a meaningful denominator. If both are zero,
        # the chain is dead and we bail.
        total_call_volume = sum(int(c.open_interest or 0) for c in calls)
        total_put_volume = sum(int(p.open_interest or 0) for p in puts)
        if total_call_volume <= 0:
            return None
    vol_ratio = float(total_put_volume) / float(total_call_volume)

    score, signal_type, detail = _score_skew(iv_ratio, vol_ratio, params)

    delta_skew = _twenty_five_delta_skew(calls, puts)

    signals: list[dict] = []
    if signal_type != "neutral":
        signals.append({
            "type": signal_type,
            "source": "OptionsSkew",
            "detail": detail,
        })

    days_to_expiry = (expiry - _snapshot_date(options_chain)).days

    result: dict = {
        "score": int(score),
        "signals": signals,
        "put_call_iv_ratio": round(iv_ratio, 4),
        "put_call_volume_ratio": round(vol_ratio, 4),
        "indicators": {
            "expiry": expiry.isoformat(),
            "days_to_expiry": days_to_expiry,
            "atm_call_strike": atm_call.strike,
            "atm_put_strike": atm_put.strike,
            "atm_call_iv": round(float(atm_call.implied_volatility), 4),
            "atm_put_iv": round(float(atm_put.implied_volatility), 4),
            "total_call_volume": total_call_volume,
            "total_put_volume": total_put_volume,
            "num_call_strikes": len(calls),
            "num_put_strikes": len(puts),
        },
    }
    # Only emit the 25-delta key when we actually computed it — the
    # absence of the field is the documented signal that deltas weren't
    # in the feed (per the module contract).
    if delta_skew is not None:
        result["25_delta_skew"] = round(delta_skew, 4)
    return result
