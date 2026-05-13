"""Tests for src.scoring.analyzers.insider_flow.

Pure function over transaction lists — drives entirely with hand-built
records that mirror the SQLAlchemy ORM row shape via a small dataclass.
No database, no EDGAR.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

import pytest

from src.scoring.analyzers.insider_flow import (
    InsiderFlowParams,
    _detect_cluster,
    _is_senior_role,
    _score_from_cluster,
    analyze,
)


@dataclass
class FakeTx:
    """Mimics InsiderTxRow / InsiderTransaction for the analyzer's
    Protocol shape — we only need the fields the analyzer actually
    reads."""

    ticker: str = "AAPL"
    transaction_date: date = field(default_factory=lambda: date(2024, 1, 15))
    transaction_code: str = "P"
    acquired_disposed: str = "A"
    owner_cik: str = "0001000001"
    owner_name: str = "INSIDER ONE"
    owner_role: str = "officer"
    officer_title: Optional[str] = "Chief Executive Officer"
    shares: Decimal = Decimal("1000")
    price_per_share: Optional[Decimal] = Decimal("100.00")
    value_usd: Optional[Decimal] = Decimal("100000.00")


def _cluster_buys(*, count: int, as_of: date, value_each: float = 100_000.0,
                  senior_indices: tuple[int, ...] = ()) -> list[FakeTx]:
    """Build a cluster of N distinct insiders buying within 10 days
    of ``as_of``. ``senior_indices`` marks which positions get a
    CEO/CFO title."""
    txs = []
    for i in range(count):
        title = "Chief Executive Officer" if i in senior_indices else "VP Engineering"
        txs.append(FakeTx(
            owner_cik=f"00010{i:05d}",
            owner_name=f"INSIDER {i}",
            officer_title=title,
            transaction_date=as_of - timedelta(days=i + 1),
            value_usd=Decimal(str(value_each)),
        ))
    return txs


class TestNoSignal:
    def test_empty_transactions_returns_none(self) -> None:
        assert analyze([], as_of=date(2024, 1, 31)) is None

    def test_only_sells_returns_none(self) -> None:
        """The analyzer is bullish-only — open-market sells are too
        noisy (tax, scheduled 10b5-1) to use as a bearish signal."""
        txs = [FakeTx(transaction_code="S", acquired_disposed="D")]
        assert analyze(txs, as_of=date(2024, 1, 31)) is None

    def test_only_grants_returns_none(self) -> None:
        """Code A (grant) is an RSU vesting, not an open-market buy —
        must be filtered out."""
        txs = [FakeTx(transaction_code="A", value_usd=Decimal("0"))]
        assert analyze(txs, as_of=date(2024, 1, 31)) is None

    def test_single_insider_below_threshold(self) -> None:
        """Even a $5M buy by one insider doesn't clear the
        cluster threshold (default min=2)."""
        tx = FakeTx(value_usd=Decimal("5000000"))
        assert analyze([tx], as_of=date(2024, 1, 31)) is None

    def test_buys_outside_window_ignored(self) -> None:
        """A 2-insider cluster from 90 days ago doesn't fire when the
        window is 30 days."""
        as_of = date(2024, 6, 1)
        txs = _cluster_buys(count=2, as_of=as_of - timedelta(days=90))
        assert analyze(txs, as_of=as_of) is None

    def test_value_threshold_filters_tiny_buys(self) -> None:
        """Two insiders each buying $1k each (sub-threshold) — no
        cluster fires. Defaults require $25k per buy."""
        txs = _cluster_buys(count=2, as_of=date(2024, 1, 31), value_each=1_000.0)
        assert analyze(txs, as_of=date(2024, 1, 31)) is None


class TestClusterScoring:
    @pytest.fixture
    def as_of(self) -> date:
        return date(2024, 1, 31)

    def test_minimal_cluster_lands_in_bullish_lean(self, as_of: date) -> None:
        """2 insiders, $100k each, no seniors → base 60."""
        txs = _cluster_buys(count=2, as_of=as_of)
        result = analyze(txs, as_of=as_of)
        assert result is not None
        assert 55 <= result["score"] <= 65
        assert result["signals"][0]["source"] == "InsiderCluster"
        assert result["signals"][0]["type"] == "bullish"

    def test_more_insiders_raise_score(self, as_of: date) -> None:
        small = analyze(_cluster_buys(count=2, as_of=as_of), as_of=as_of)
        big = analyze(_cluster_buys(count=5, as_of=as_of), as_of=as_of)
        assert big["score"] > small["score"]

    def test_senior_insiders_raise_score(self, as_of: date) -> None:
        baseline = analyze(_cluster_buys(count=3, as_of=as_of), as_of=as_of)
        with_ceo = analyze(
            _cluster_buys(count=3, as_of=as_of, senior_indices=(0,)),
            as_of=as_of,
        )
        assert with_ceo["score"] > baseline["score"]

    def test_large_dollar_value_raises_score(self, as_of: date) -> None:
        small = analyze(_cluster_buys(count=2, as_of=as_of, value_each=50_000), as_of=as_of)
        huge = analyze(_cluster_buys(count=2, as_of=as_of, value_each=5_000_000), as_of=as_of)
        assert huge["score"] > small["score"]

    def test_score_capped_at_95(self, as_of: date) -> None:
        """6 insiders incl. 3 seniors with $10M each → still ≤95
        (a hard cap prevents any single sub-score from dominating
        the composite)."""
        txs = _cluster_buys(
            count=6, as_of=as_of, value_each=10_000_000,
            senior_indices=(0, 1, 2),
        )
        result = analyze(txs, as_of=as_of)
        assert result["score"] <= 95


class TestIndicators:
    def test_indicators_populated(self) -> None:
        as_of = date(2024, 1, 31)
        txs = _cluster_buys(count=3, as_of=as_of, value_each=200_000,
                            senior_indices=(0,))
        result = analyze(txs, as_of=as_of)
        ind = result["indicators"]
        assert ind["insider_count"] == 3
        assert ind["senior_count"] == 1
        assert ind["total_value_usd"] == 600_000.0
        assert ind["cluster_age_days"] >= 1
        assert len(ind["insider_names"]) == 3


class TestSeniorRoleDetection:
    @pytest.mark.parametrize(
        "title,expected",
        [
            ("Chief Executive Officer", True),
            ("CEO", True),
            ("Chief Financial Officer", True),
            ("CFO", True),
            ("President", True),
            ("Chairman of the Board", True),
            ("VP of Engineering", False),
            ("Director", False),
            ("", False),
            (None, False),
        ],
    )
    def test_titles(self, title, expected) -> None:
        tx = FakeTx(officer_title=title)
        assert _is_senior_role(tx) is expected


class TestCustomParams:
    def test_tighter_min_cluster(self) -> None:
        """Raise min_cluster_insiders to 3; a 2-insider cluster no
        longer qualifies."""
        params = InsiderFlowParams(min_cluster_insiders=3)
        txs = _cluster_buys(count=2, as_of=date(2024, 1, 31))
        assert analyze(txs, as_of=date(2024, 1, 31), params=params) is None
        txs3 = _cluster_buys(count=3, as_of=date(2024, 1, 31))
        assert analyze(txs3, as_of=date(2024, 1, 31), params=params) is not None

    def test_longer_window_catches_older_clusters(self) -> None:
        as_of = date(2024, 6, 1)
        txs = _cluster_buys(count=2, as_of=as_of - timedelta(days=45))
        default = analyze(txs, as_of=as_of)
        wider = analyze(
            txs, as_of=as_of,
            params=InsiderFlowParams(
                window_days=90, signal_active_days=120,
            ),
        )
        assert default is None
        assert wider is not None
