"""Insider Form 4 cluster-buy analyzer.

Implements a Cohen-Malloy-Pomorski-style score: multiple insiders
independently buying open-market stock within a short rolling window
is a much stronger signal than any single insider buy in isolation.
Routine RSU-related buys are noisier and add little — the cluster
filter implicitly washes them out (RSU schedules don't co-fire across
multiple insiders).

Pure function over a list of ``InsiderTxRow`` (or any rows with the
same shape):

  ``analyze(transactions, as_of, params=None) -> dict | None``

Returns the standard analyzer shape:
  { score (0-100), signals (list), indicators (dict), ...
    weighted_intensity (raw cluster magnitude) }

The composite engine slots this in like ``alpha158_result`` /
``rel_strength_result`` — None means "no signal for this stock; skip
the sub-score." That's the right behavior for any ticker with no
recent insider buying — silence is information that pulls weight back
to the other analyzers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable, Optional, Protocol


class _TxLike(Protocol):
    """Structural type covering both the parser dataclass and the
    SQLAlchemy ORM row. We only read these fields."""

    ticker: Optional[str]
    transaction_date: date
    transaction_code: str
    acquired_disposed: str
    owner_cik: str
    owner_name: str
    owner_role: str
    officer_title: Optional[str]
    shares: Decimal
    price_per_share: Optional[Decimal]
    value_usd: Optional[Decimal]


@dataclass(frozen=True)
class InsiderFlowParams:
    """Tunable inputs. Defaults are CMP-2012-ish:
      * 30-day window (CMP used calendar quarters; tighter is fine
        for a Monday-rebalance backtest).
      * Min 2 distinct insiders to qualify as a cluster.
      * Min $25k per individual buy — filters out auto-purchase plans
        and ESPP rounding.
    """

    window_days: int = 30
    min_cluster_insiders: int = 2
    min_value_per_buy: float = 25_000.0
    # How long after the cluster does the signal stay active? CMP found
    # the abnormal-return drift extends 6-12 months; we use 60 days as
    # a compromise — long enough that weekly rebalances reliably catch
    # the signal but short enough to keep the time horizon comparable
    # to the existing PEAD analyzer.
    signal_active_days: int = 60


@dataclass(frozen=True)
class ClusterResult:
    """Detected cluster — what the scorer turns into a score band."""

    insider_count: int
    total_value_usd: float
    cluster_end: date  # most-recent buy in the cluster
    senior_count: int  # CEO/CFO/Chair-level buys are sharper
    insider_names: tuple[str, ...] = field(default_factory=tuple)


def _is_senior_role(tx: _TxLike) -> bool:
    """CEO/CFO/Chair/President buys carry markedly more signal than
    a junior VP. We don't have a clean role-rank field, so do a
    string-match on officer_title (best-effort; misses are
    conservative — treats unknown as non-senior)."""
    title = (tx.officer_title or "").lower()
    return any(
        token in title for token in (
            "chief executive", "ceo",
            "chief financial", "cfo",
            "chairman", "chair ", "chairperson",
            "president",
        )
    )


def _detect_cluster(
    txs: list[_TxLike],
    as_of: date,
    params: InsiderFlowParams,
) -> Optional[ClusterResult]:
    """Find the strongest cluster of distinct-insider buys in the
    window ending at ``as_of``.

    "Strongest" = most distinct insiders. Ties broken by total dollar
    value. Returns None if no cluster meets the minimum-insider
    threshold.
    """
    cutoff = as_of - timedelta(days=params.window_days)
    # Filter to qualifying buys
    in_window: list[_TxLike] = []
    for tx in txs:
        if tx.transaction_code != "P" or tx.acquired_disposed != "A":
            continue
        if tx.transaction_date < cutoff or tx.transaction_date > as_of:
            continue
        if tx.value_usd is not None and float(tx.value_usd) < params.min_value_per_buy:
            continue
        in_window.append(tx)
    if not in_window:
        return None
    distinct_insiders = {tx.owner_cik for tx in in_window}
    if len(distinct_insiders) < params.min_cluster_insiders:
        return None
    total_value = sum(float(tx.value_usd or 0) for tx in in_window)
    cluster_end = max(tx.transaction_date for tx in in_window)
    senior_count = len({
        tx.owner_cik for tx in in_window if _is_senior_role(tx)
    })
    insider_names = tuple(sorted({tx.owner_name for tx in in_window}))
    return ClusterResult(
        insider_count=len(distinct_insiders),
        total_value_usd=total_value,
        cluster_end=cluster_end,
        senior_count=senior_count,
        insider_names=insider_names,
    )


def _score_from_cluster(cluster: ClusterResult) -> int:
    """Map cluster strength to a 0-100 sub-score.

    Bands are loosely calibrated so a 2-insider, $50k cluster (the
    minimum-meaningful signal) lands at the 60-65 "bullish lean"
    band, and a 4+-insider multi-million-dollar cluster with senior
    participation maxes out at 90. The composite engine then takes
    weighted average with other sub-scores.
    """
    base = 60
    base += min(15, (cluster.insider_count - 2) * 5)   # +5 per extra insider, cap +15
    base += min(10, cluster.senior_count * 5)          # +5 per senior insider, cap +10
    if cluster.total_value_usd >= 5_000_000:
        base += 10
    elif cluster.total_value_usd >= 1_000_000:
        base += 5
    return min(95, base)


def analyze(
    transactions: Iterable[_TxLike],
    *,
    as_of: date,
    params: InsiderFlowParams | None = None,
) -> Optional[dict]:
    """Score a stock's recent insider-buying activity.

    Returns None when no qualifying cluster exists in the window —
    composite engine then skips the sub-score (same convention as
    alpha158/PEAD/RS). The "no signal" outcome is intentional silence
    rather than a neutral 50, because most tickers on any given day
    have no recent insider activity and forcing 50 would just bias
    the composite toward neutral.
    """
    params = params or InsiderFlowParams()
    txs = list(transactions)

    # Cluster detection in the active window (ending at as_of, looking
    # back signal_active_days for a still-fresh trigger).
    fresh_cutoff = as_of - timedelta(days=params.signal_active_days)
    recent_txs = [tx for tx in txs if tx.transaction_date >= fresh_cutoff]
    cluster = _detect_cluster(recent_txs, as_of, params)
    if cluster is None:
        return None

    score = _score_from_cluster(cluster)
    age_days = (as_of - cluster.cluster_end).days
    detail = (
        f"{cluster.insider_count} insiders bought "
        f"${cluster.total_value_usd:,.0f} ({age_days}d ago)"
    )
    if cluster.senior_count:
        detail += f", incl. {cluster.senior_count} senior"
    return {
        "score": score,
        "signals": [{
            "type": "bullish",
            "source": "InsiderCluster",
            "detail": detail,
        }],
        "indicators": {
            "insider_count": cluster.insider_count,
            "senior_count": cluster.senior_count,
            "total_value_usd": cluster.total_value_usd,
            "cluster_age_days": age_days,
            "insider_names": list(cluster.insider_names),
        },
    }
