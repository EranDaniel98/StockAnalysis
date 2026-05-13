"""Short-interest change analyzer.

Implements an Asquith-Pathak (2005) / Boehmer-Jones-Zhang (2008) style
score over FINRA biweekly short-interest reports: rising short interest
predicts 1-3 month underperformance, while a sharp drop in short
interest after an elevated level (high days-to-cover) flags covering
pressure / short-squeeze setups that have historically led positive
returns.

Pure function over a list of ``ShortInterestRow`` (or any rows with the
same shape). The composite engine wires this in the same way as
``insider_flow`` / ``catalyst``:

  ``analyze(short_interest_history, *, as_of, shares_outstanding=None,
            params=None) -> dict | None``

Return shape on signal:
  ``{"score": int 0-100, "signals": [...], "short_interest_pct": float,
     "days_to_cover": float | None, "indicators": {...}}``

Returning ``None`` means "no usable signal" — not enough history,
missing volume, or the change is mild enough that we'd rather defer to
the other analyzers than push 50 into the composite average. That
matches the existing convention (alpha158 / PEAD / RS / insider_flow).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Optional, Protocol


class _ShortRowLike(Protocol):
    """Structural shape this analyzer reads. Any duck-typed test fake or
    SQLAlchemy ORM row with these fields works."""

    settlement_date: date
    short_interest_shares: int
    avg_daily_volume: Optional[int]
    days_to_cover: Optional[float]


@dataclass(frozen=True)
class ShortInterestRow:
    """In-process row contract for the analyzer.

    Mirrors a typical FINRA biweekly settlement record. Both
    ``avg_daily_volume`` and ``days_to_cover`` are optional because some
    upstream feeds only publish one of them — the analyzer will derive
    days-to-cover from volume when present and fall back to the
    pre-computed field otherwise.
    """

    settlement_date: date
    short_interest_shares: int
    avg_daily_volume: Optional[int] = None
    days_to_cover: Optional[float] = None


@dataclass(frozen=True)
class ShortInterestParams:
    """Tunable inputs. Defaults track the Asquith-Pathak window choices:

    * ``window_days`` 30 — biweekly FINRA cadence gives ~2 reports in
      30 days, enough to measure direction without aliasing on a single
      stale data point.
    * ``heavy_increase_pct`` 0.20 — Boehmer et al. (2008) report that
      the predictive power of short-interest *changes* concentrates in
      the top decile; +20% over 30 days is roughly the 90th percentile
      change for US large caps.
    * ``sharp_decrease_pct`` 0.20 — symmetric on the downside;
      short-covering of this magnitude in 30d is the squeeze signal.
    * ``high_dtc`` 5.0 — days-to-cover ≥5 is the standard threshold
      practitioners use for "crowded short" (e.g. S3 Partners
      thresholds).
    * ``catastrophic_dtc`` 10.0 — sustained DTC ≥10 with no recent
      decrease is interpreted as conviction short interest, not a
      transient pile-on.
    """

    window_days: int = 30
    heavy_increase_pct: float = 0.20
    mild_increase_pct: float = 0.05
    mild_decrease_pct: float = 0.10
    sharp_decrease_pct: float = 0.20
    high_dtc: float = 5.0
    catastrophic_dtc: float = 10.0
    # When the change is between ``mild_decrease_pct`` and
    # ``mild_increase_pct`` we treat the signal as too weak to score and
    # return None (same convention as the other analyzers). Flip this to
    # True to force a neutral 50 into the composite instead — useful for
    # diagnostics but not the default.
    emit_neutral: bool = False


def _filter_history(
    rows: Iterable[_ShortRowLike],
    as_of: date,
) -> list[_ShortRowLike]:
    """Drop rows reported after ``as_of`` (look-ahead bias guard) and
    sort chronologically. Stable on duplicate settlement dates."""
    eligible = [r for r in rows if r.settlement_date <= as_of]
    eligible.sort(key=lambda r: r.settlement_date)
    return eligible


def _pick_baseline(
    history: list[_ShortRowLike],
    current: _ShortRowLike,
    window_days: int,
) -> Optional[_ShortRowLike]:
    """Find the row closest to ``window_days`` before ``current``.

    We don't require an exact match (FINRA cadence drifts around
    holidays) — instead pick the most recent row at or before the target
    date. Returns None if no prior row exists in the window.
    """
    target = current.settlement_date - timedelta(days=window_days)
    candidates = [r for r in history if r.settlement_date <= target
                  and r.settlement_date < current.settlement_date]
    if not candidates:
        # Fall back to the oldest available row that's still before
        # current — better a wider lookback than no signal at all, but
        # we expose the actual baseline date so the caller can judge.
        prior = [r for r in history if r.settlement_date < current.settlement_date]
        if not prior:
            return None
        return prior[0]
    return candidates[-1]


def _days_to_cover(row: _ShortRowLike) -> Optional[float]:
    """Prefer pre-computed days_to_cover; otherwise derive from avg
    daily volume. Returns None when neither path produces a finite
    positive number (covers volume=0 divide-by-zero)."""
    if row.days_to_cover is not None and row.days_to_cover > 0:
        return float(row.days_to_cover)
    if row.avg_daily_volume and row.avg_daily_volume > 0:
        return float(row.short_interest_shares) / float(row.avg_daily_volume)
    return None


def _score_from_change(
    change_pct: float,
    dtc: Optional[float],
    params: ShortInterestParams,
) -> tuple[Optional[int], str, str]:
    """Map (change, days-to-cover) into a (score, signal_type, detail).

    Returns ``(None, "", "")`` when the change is too mild to score
    (the caller then returns None unless ``emit_neutral`` is set).
    """
    # Bearish: rising short interest.
    if change_pct >= params.heavy_increase_pct:
        if dtc is not None and dtc >= params.high_dtc:
            score = 27  # heavy increase + crowded short
            detail = (
                f"+{change_pct * 100:.0f}% SI in 30d, DTC={dtc:.1f} "
                f"(bearish, Asquith-Pathak)"
            )
        else:
            score = 33
            detail = f"+{change_pct * 100:.0f}% SI in 30d (bearish)"
        return score, "bearish", detail

    if change_pct >= params.mild_increase_pct:
        score = 43 if (dtc is None or dtc < params.high_dtc) else 40
        detail = f"+{change_pct * 100:.0f}% SI in 30d (mild bearish lean)"
        return score, "bearish", detail

    # Bullish: falling short interest.
    if change_pct <= -params.sharp_decrease_pct:
        if dtc is not None and dtc >= params.high_dtc:
            # Best case: was crowded, now covering hard.
            score = 75
            detail = (
                f"{change_pct * 100:.0f}% SI in 30d, DTC was {dtc:.1f} "
                f"(squeeze setup, Boehmer-Jones-Zhang)"
            )
        else:
            score = 65
            detail = f"{change_pct * 100:.0f}% SI in 30d (covering)"
        return score, "bullish", detail

    if change_pct <= -params.mild_decrease_pct:
        score = 57
        detail = f"{change_pct * 100:.0f}% SI in 30d (mild bullish lean)"
        return score, "bullish", detail

    return None, "", ""


def analyze(
    short_interest_history: Iterable[_ShortRowLike],
    *,
    as_of: date,
    shares_outstanding: Optional[int] = None,
    params: Optional[ShortInterestParams] = None,
) -> Optional[dict]:
    """Score a stock's short-interest dynamics.

    Returns ``None`` (composite engine skips the sub-score) when:
      * fewer than 2 history points exist on or before ``as_of``;
      * the most recent row has neither volume nor pre-computed DTC and
        the change-window baseline can't be located;
      * the 30-day change falls inside the "mild" deadband and
        ``params.emit_neutral`` is False — the analyzer prefers silence
        to a forced neutral 50 (same convention as insider_flow).

    Special case: a "catastrophic" short-interest level (DTC >=
    ``params.catastrophic_dtc``) with no recent decrease scores 20 even
    if the 30d change is mild — sustained crowded-short conviction is
    bearish on its own per Asquith-Pathak's static-level finding.
    """
    params = params or ShortInterestParams()
    history = _filter_history(short_interest_history, as_of)
    if len(history) < 2:
        return None

    current = history[-1]
    baseline = _pick_baseline(history, current, params.window_days)
    if baseline is None:
        return None
    if baseline.short_interest_shares <= 0:
        # Can't compute a relative change from a zero baseline.
        return None

    change_pct = (
        (current.short_interest_shares - baseline.short_interest_shares)
        / float(baseline.short_interest_shares)
    )

    dtc = _days_to_cover(current)

    # Catastrophic-level short interest with no recent decrease — score
    # a hard bearish 20 even if the 30d change itself looks mild.
    catastrophic = (
        dtc is not None
        and dtc >= params.catastrophic_dtc
        and change_pct > -params.mild_decrease_pct
    )
    if catastrophic:
        score: Optional[int] = 20
        signal_type = "bearish"
        detail = (
            f"DTC={dtc:.1f} sustained (catastrophic short-interest "
            f"conviction, Asquith-Pathak)"
        )
    else:
        score, signal_type, detail = _score_from_change(change_pct, dtc, params)

    if score is None:
        if not params.emit_neutral:
            return None
        score = 50
        signal_type = "bullish"  # placeholder; UI keys off "stable" detail
        detail = f"{change_pct * 100:+.0f}% SI in 30d (stable)"

    short_interest_pct: Optional[float]
    if shares_outstanding and shares_outstanding > 0:
        short_interest_pct = (
            current.short_interest_shares / float(shares_outstanding)
        )
    elif current.avg_daily_volume and current.avg_daily_volume > 0:
        # Best-effort fallback: not a true float-percentage, but a
        # volume-normalized intensity that scales similarly across
        # tickers. Documented in the return key.
        short_interest_pct = (
            current.short_interest_shares / float(current.avg_daily_volume)
        )
    else:
        short_interest_pct = None

    baseline_age_days = (current.settlement_date - baseline.settlement_date).days
    return {
        "score": int(score),
        "signals": [{
            "type": signal_type,
            "source": "ShortInterest",
            "detail": detail,
        }],
        "short_interest_pct": short_interest_pct,
        "days_to_cover": dtc,
        "indicators": {
            "change_30d_pct": round(change_pct, 4),
            "current_short_interest_shares": current.short_interest_shares,
            "baseline_short_interest_shares": baseline.short_interest_shares,
            "baseline_age_days": baseline_age_days,
            "current_settlement_date": current.settlement_date.isoformat(),
            "baseline_settlement_date": baseline.settlement_date.isoformat(),
            "catastrophic_level": catastrophic,
        },
    }
