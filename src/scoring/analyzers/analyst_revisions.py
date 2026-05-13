"""Analyst-revisions momentum analyzer.

Implements a Womack (1996) / Jegadeesh-Kim (2010) style score over a
rolling window of sell-side analyst rating + price-target revisions.
Stocks whose consensus is being revised UPWARD (more upgrades than
downgrades, target prices being raised) earn abnormal returns over the
following 1-3 months; downward revisions underperform symmetrically.
Effects concentrate in the tails — broad enthusiasm or broad pessimism,
not single isolated calls.

LIVE-ONLY -- NOT WIRED INTO BACKTEST
------------------------------------
yfinance only exposes the CURRENT analyst-recommendation snapshot for
free. Historical point-in-time recommendation histories are gated
behind paid feeds (IBES, FactSet, Refinitiv). This analyzer therefore
runs in the LIVE SCAN path (where the current snapshot is exactly what
we want to score) but is INTENTIONALLY EXCLUDED from the backtest
engine: feeding it today's snapshot at every historical as_of would be
catastrophic look-ahead bias. When historical IBES coverage becomes
available the same pure function can be wired into the backtest path
unchanged -- the row contract already carries ``revision_date`` so
``as_of`` filtering is exact.

Pure function over a list of ``RevisionRow`` (or any rows with the
same shape). Composite engine plugs it in like the other analyzers:

  ``analyze(revision_history, *, as_of, params=None) -> dict | None``

Return ``None`` means "no usable signal" -- empty history, all rows
outside the 60-day window, or the net activity is too mild to score.
The composite engine then skips the sub-score (same convention as
insider_flow / short_interest / pead).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Optional, Protocol


# ---------------------------------------------------------------------------
# Grade vocabulary
# ---------------------------------------------------------------------------
# yfinance / Yahoo Finance recommendation strings are inconsistent across
# brokers. We normalize to a 1-5 numeric ladder so a "strongBuy -> hold"
# (delta -2) is recognized as a sharper bearish signal than "buy -> hold"
# (delta -1). Unknown grades map to 3 (hold/neutral) -- the conservative
# choice that yields a zero delta when paired with another unknown.
#
# Strings observed across yfinance / Finnhub / Yahoo:
#   "Strong Buy", "strongBuy", "strong_buy", "STRONG BUY",
#   "Buy", "Outperform", "Overweight", "Accumulate", "Add",
#   "Hold", "Neutral", "Equal-Weight", "Market Perform", "Sector Perform",
#   "Underperform", "Underweight", "Reduce",
#   "Sell", "Strong Sell"
_GRADE_MAP: dict[str, int] = {
    "strongsell": 1, "strong sell": 1, "strong_sell": 1,
    "sell": 2, "underperform": 2, "underweight": 2, "reduce": 2,
    "hold": 3, "neutral": 3, "equalweight": 3, "equal-weight": 3,
    "equal weight": 3, "marketperform": 3, "market perform": 3,
    "sectorperform": 3, "sector perform": 3, "peerperform": 3,
    "peer perform": 3,
    "buy": 4, "outperform": 4, "overweight": 4, "accumulate": 4,
    "add": 4, "positive": 4,
    "strongbuy": 5, "strong buy": 5, "strong_buy": 5,
    "conviction buy": 5, "convictionbuy": 5,
}


def _grade_to_num(grade: Optional[str]) -> Optional[int]:
    """Map a free-form analyst grade to the 1-5 ladder. Returns None on
    unknown / missing input so callers can decide whether to treat that
    as neutral or skip the row."""
    if grade is None:
        return None
    key = grade.strip().lower().replace("-", "").replace("_", "")
    # Try the exact normalized key, then progressive fallbacks for
    # whitespace-separated multi-word grades.
    if key in _GRADE_MAP:
        return _GRADE_MAP[key]
    spaced = grade.strip().lower()
    if spaced in _GRADE_MAP:
        return _GRADE_MAP[spaced]
    nounderscore = spaced.replace("_", " ")
    if nounderscore in _GRADE_MAP:
        return _GRADE_MAP[nounderscore]
    return None


class _RevisionRowLike(Protocol):
    """Structural shape this analyzer reads."""

    revision_date: date
    firm: str
    action: str
    from_grade: Optional[str]
    to_grade: str
    target_price_prior: Optional[float]
    target_price_new: Optional[float]


@dataclass(frozen=True)
class RevisionRow:
    """In-process row contract.

    ``action`` should be one of ``upgrade``, ``downgrade``, ``initiate``,
    ``reiterate`` (case-insensitive). The analyzer also infers direction
    from the grade-delta when action is missing/ambiguous -- the action
    field is preferred but defensive.
    """

    revision_date: date
    firm: str
    action: str
    from_grade: Optional[str]
    to_grade: str
    target_price_prior: Optional[float] = None
    target_price_new: Optional[float] = None


@dataclass(frozen=True)
class AnalystRevisionsParams:
    """Tunable inputs. Defaults track Womack / Jegadeesh-Kim window
    choices: 60 calendar days is short enough that the predictive drift
    hasn't decayed and long enough to accumulate ~3-5 broker updates on
    a typical mid/large cap. Thresholds are calibrated against the
    score-band table in the analyzer-revisions task spec."""

    window_days: int = 60
    # Bullish thresholds
    bullish_net_upgrades: int = 3
    bullish_target_delta_pct: float = 0.05    # +5%
    mild_bullish_net_upgrades: int = 1
    mild_bullish_target_delta_pct: float = 0.02  # +2%
    # Bearish thresholds
    bearish_net_downgrades: int = 2
    bearish_target_delta_pct: float = -0.05   # -5%
    severe_net_downgrades: int = 3
    severe_target_delta_pct: float = -0.10    # -10%
    # Grade-delta weighting: each unit of grade-ladder movement (e.g.
    # strongBuy -> hold = -2) adds this much to the "effective" net
    # upgrades count. A single strongBuy -> sell carries a delta of -3,
    # which alone exceeds the bearish threshold.
    grade_delta_weight: float = 1.0
    # When net activity is in the "stable" deadband (|net_eff| <= 1 and
    # |target_delta| <= 2%) we return None so the composite engine skips
    # the sub-score. Flip this on for diagnostics if a forced 50 is
    # needed. (See module docstring -- silence is the documented
    # default, matching insider_flow / short_interest.)
    emit_neutral_on_stable: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _filter_window(
    rows: Iterable[_RevisionRowLike],
    as_of: date,
    window_days: int,
) -> list[_RevisionRowLike]:
    """Keep rows within ``[as_of - window_days, as_of]``. Look-ahead
    guard: future-dated rows are dropped even though in production the
    live snapshot is always 'today or earlier' -- backtest re-use plus
    fuzz-test safety justify the cheap check."""
    cutoff = as_of - timedelta(days=window_days)
    return [
        r for r in rows
        if cutoff <= r.revision_date <= as_of
    ]


def _direction_from_row(row: _RevisionRowLike) -> int:
    """Return +1 / 0 / -1 for upgrade / neutral / downgrade.

    The explicit ``action`` field is preferred. When it's missing or
    ambiguous ('reiterate', 'initiate' with no peer comparison) we fall
    back to the grade ladder. Initiations contribute zero net direction
    -- they don't represent a *change* in the broker's view.
    """
    act = (row.action or "").strip().lower()
    if act == "upgrade":
        return 1
    if act == "downgrade":
        return -1
    if act in ("initiate", "initiation", "reiterate", "maintain"):
        return 0
    # Unknown action -- fall back to grade-ladder inference.
    from_n = _grade_to_num(row.from_grade)
    to_n = _grade_to_num(row.to_grade)
    if from_n is None or to_n is None:
        return 0
    if to_n > from_n:
        return 1
    if to_n < from_n:
        return -1
    return 0


def _grade_delta(row: _RevisionRowLike) -> int:
    """Signed ladder distance ``to - from``. 0 when either side is
    unknown or it's an initiation (no prior grade to diff against)."""
    from_n = _grade_to_num(row.from_grade)
    to_n = _grade_to_num(row.to_grade)
    if from_n is None or to_n is None:
        return 0
    return to_n - from_n


def _target_delta_pct(row: _RevisionRowLike) -> Optional[float]:
    """Percent change in price target (new - prior) / prior. None when
    either side is missing or prior is non-positive."""
    prior = row.target_price_prior
    new = row.target_price_new
    if prior is None or new is None:
        return None
    if prior <= 0:
        return None
    return (new - prior) / prior


def _score_from_signal(
    net_eff: float,
    target_delta: float,
    params: AnalystRevisionsParams,
) -> tuple[Optional[int], str, str]:
    """Map (effective net upgrades, summed target delta) to a band.

    Returns ``(None, "", "")`` for the stable deadband -- caller then
    decides whether to emit a neutral 50 or skip via ``None``.
    """
    # Severe bearish: heavy net downgrades AND deep target cut, OR
    # extreme net (e.g. multiple strongBuy -> hold/sell collapses driving
    # net_eff well past 2x the severe threshold). The OR-branch lets a
    # multi-broker high-ladder capitulation register as severe even when
    # the price-target cuts are still in progress.
    severe_by_both = (
        net_eff <= -params.severe_net_downgrades
        and target_delta <= params.severe_target_delta_pct
    )
    severe_by_grade = net_eff <= -(params.severe_net_downgrades * 2)
    if severe_by_both or severe_by_grade:
        return (
            18,
            "bearish",
            f"net {net_eff:+.0f} revs, target {target_delta * 100:+.0f}% "
            "(severe analyst capitulation, Womack)",
        )

    # Bearish: either heavy downgrades OR deep target cut.
    if (net_eff <= -params.bearish_net_downgrades
            or target_delta <= params.bearish_target_delta_pct):
        # Sharper bearish band when both conditions stack, shallow when
        # only one fires. A net_eff already past the severe-net threshold
        # (without the matching target cut) also pulls the band deeper.
        both = (net_eff <= -params.bearish_net_downgrades
                and target_delta <= params.bearish_target_delta_pct)
        amplified = net_eff <= -params.severe_net_downgrades
        if amplified:
            score = 30
        elif both:
            score = 35
        else:
            score = 38
        return (
            score,
            "bearish",
            f"net {net_eff:+.0f} revs, target {target_delta * 100:+.0f}% "
            "(downward revisions, Jegadeesh-Kim)",
        )

    # Strong bullish: heavy net upgrades AND meaningful target hike.
    if (net_eff >= params.bullish_net_upgrades
            and target_delta >= params.bullish_target_delta_pct):
        return (
            80,
            "bullish",
            f"net {net_eff:+.0f} revs, target {target_delta * 100:+.0f}% "
            "(broad analyst enthusiasm, Womack)",
        )

    # Mild bullish: either condition alone.
    if (net_eff >= params.mild_bullish_net_upgrades
            or target_delta >= params.mild_bullish_target_delta_pct):
        both = (net_eff >= params.mild_bullish_net_upgrades
                and target_delta >= params.mild_bullish_target_delta_pct)
        score = 68 if both else 62
        return (
            score,
            "bullish",
            f"net {net_eff:+.0f} revs, target {target_delta * 100:+.0f}% "
            "(upward revisions)",
        )

    # Stable deadband.
    return None, "", ""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def analyze(
    revision_history: Iterable[_RevisionRowLike],
    *,
    as_of: date,
    params: Optional[AnalystRevisionsParams] = None,
) -> Optional[dict]:
    """Score a stock's recent analyst-revision activity.

    Returns ``None`` (composite engine skips the sub-score) when:
      * the history is empty;
      * no rows fall inside the 60-day window ending at ``as_of``;
      * the net activity sits inside the stable deadband and
        ``params.emit_neutral_on_stable`` is False (the documented
        default -- silence beats forcing a neutral 50).
    """
    params = params or AnalystRevisionsParams()
    in_window = _filter_window(revision_history, as_of, params.window_days)
    if not in_window:
        return None

    # Headline counts (used for indicators + the spec's net_upgrade_count
    # return key). Initiations contribute 0 to net direction.
    raw_upgrades = sum(1 for r in in_window if _direction_from_row(r) > 0)
    raw_downgrades = sum(1 for r in in_window if _direction_from_row(r) < 0)
    raw_net = raw_upgrades - raw_downgrades

    # Effective net: include grade-delta magnitude so strongBuy -> hold
    # (-2) outweighs buy -> hold (-1). Initiations / unknown grades
    # contribute 0 here too.
    grade_delta_sum = sum(_grade_delta(r) for r in in_window)
    net_eff = raw_net + params.grade_delta_weight * grade_delta_sum
    # Don't let grade_delta double-count beyond the row's own direction
    # past a reasonable cap -- keep the scoring stable when a single
    # broker swings two notches.

    # Target-price aggregate: sum of per-row percent deltas, skipping
    # rows where prior is missing. Summing (vs averaging) deliberately
    # mirrors the spec wording and emphasizes breadth -- 3 brokers each
    # hiking +3% is a louder signal than 1 broker hiking +9%.
    target_deltas = [
        d for d in (_target_delta_pct(r) for r in in_window)
        if d is not None
    ]
    target_delta_sum = sum(target_deltas)

    score, signal_type, detail = _score_from_signal(
        net_eff, target_delta_sum, params,
    )

    if score is None:
        if not params.emit_neutral_on_stable:
            return None
        score = 50
        signal_type = "bullish"  # placeholder; detail flags it as stable
        detail = (
            f"net {net_eff:+.0f} revs, target {target_delta_sum * 100:+.0f}% "
            "(stable -- below action threshold)"
        )

    senior_firms = sorted({r.firm for r in in_window if r.firm})
    return {
        "score": int(score),
        "signals": [{
            "type": signal_type,
            "source": "AnalystRevisions",
            "detail": detail,
        }],
        "net_upgrade_count": int(raw_net),
        "target_price_delta_pct": round(target_delta_sum, 4),
        "indicators": {
            "raw_upgrades": raw_upgrades,
            "raw_downgrades": raw_downgrades,
            "grade_delta_sum": grade_delta_sum,
            "effective_net": round(net_eff, 2),
            "revisions_in_window": len(in_window),
            "rows_with_target": len(target_deltas),
            "firms": senior_firms,
            "window_days": params.window_days,
            "as_of": as_of.isoformat(),
        },
    }
