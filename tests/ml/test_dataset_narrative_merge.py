"""Unit tests for _merge_narrative_asof — the pure-function as-of join
between factor snapshots and insider narrative snapshots.

The full integration through Postgres is covered by the live-data smoke
script (scripts/backfill_insider_narrative.py output already populates
the table); here we test the merge math in isolation.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.ml.dataset import (
    DEFAULT_NARRATIVE_MAX_AGE_DAYS,
    NARRATIVE_SIM_COLUMNS,
    _merge_narrative_asof,
)


def _make_snapshots(rows: list[dict]) -> pd.DataFrame:
    """Factor-snapshot rows — just the columns merge_narrative_asof
    needs to do its job."""
    if not rows:
        return pd.DataFrame({"ticker": [], "as_of": pd.to_datetime([])})
    df = pd.DataFrame(rows)
    df["as_of"] = pd.to_datetime(df["as_of"])
    return df


def _make_narratives(rows: list[dict]) -> pd.DataFrame:
    """Narrative-snapshot rows. Defaults fill missing similarity
    columns with 0.0."""
    if not rows:
        df = pd.DataFrame({"ticker": [], "cluster_end_date": pd.to_datetime([])})
    else:
        df = pd.DataFrame(rows)
        df["cluster_end_date"] = pd.to_datetime(df["cluster_end_date"])
    for col in NARRATIVE_SIM_COLUMNS:
        if col not in df.columns:
            df[col] = 0.0
    if "has_recent_8k" not in df.columns:
        df["has_recent_8k"] = True
    if "days_to_filing" not in df.columns:
        df["days_to_filing"] = 5
    if "narrative_skew" not in df.columns:
        df["narrative_skew"] = 0.1
    return df


class TestNoNarrativeData:
    def test_empty_narratives_yields_default_columns(self) -> None:
        snaps = _make_snapshots([
            {"ticker": "AAPL", "as_of": "2024-06-15"},
            {"ticker": "AAPL", "as_of": "2024-06-22"},
        ])
        merged = _merge_narrative_asof(snaps, _make_narratives([]))
        assert (merged["has_recent_narrative"] == False).all()  # noqa: E712
        assert (merged["sim_buyback_authorization"] == 0.0).all()
        # narrative_age_days defaults to 0.0 (sentinel) for unmatched
        # rows so the column stays numeric — LightGBM rejects object
        # columns and the trainer's dropna would otherwise discard
        # every row.
        assert (merged["narrative_age_days"] == 0.0).all()

    def test_empty_snapshots_returns_empty(self) -> None:
        empty_snaps = _make_snapshots([])
        result = _merge_narrative_asof(empty_snaps, _make_narratives([]))
        assert result.empty


class TestWithinTolerance:
    def test_match_within_60_days_attaches_narrative(self) -> None:
        snaps = _make_snapshots([
            {"ticker": "CRM", "as_of": "2026-03-25"},
        ])
        narratives = _make_narratives([
            {
                "ticker": "CRM",
                "cluster_end_date": "2026-03-19",
                "sim_buyback_authorization": 0.74,
                "narrative_skew": 0.4,
            },
        ])
        merged = _merge_narrative_asof(snaps, narratives)
        row = merged.iloc[0]
        assert row["has_recent_narrative"] == True  # noqa: E712
        # narrative_age_days is the gap from cluster_end_date to as_of
        assert row["narrative_age_days"] == 6
        assert row["sim_buyback_authorization"] == pytest.approx(0.74)
        assert row["narrative_skew"] == pytest.approx(0.4)
        assert row["has_recent_8k"] == True  # noqa: E712

    def test_picks_most_recent_when_multiple_clusters(self) -> None:
        snaps = _make_snapshots([
            {"ticker": "CRM", "as_of": "2026-03-25"},
        ])
        narratives = _make_narratives([
            {"ticker": "CRM", "cluster_end_date": "2026-02-01",
             "sim_guidance_raised": 0.20},
            {"ticker": "CRM", "cluster_end_date": "2026-03-19",
             "sim_guidance_raised": 0.55},
            # Future cluster — must be ignored (lookahead-safe merge)
            {"ticker": "CRM", "cluster_end_date": "2026-04-10",
             "sim_guidance_raised": 0.90},
        ])
        merged = _merge_narrative_asof(snaps, narratives)
        # The merge picks 2026-03-19 (most recent <= as_of); the
        # 2026-04-10 future cluster is correctly ignored.
        assert merged.iloc[0]["sim_guidance_raised"] == pytest.approx(0.55)
        assert merged.iloc[0]["narrative_age_days"] == 6


class TestOutsideTolerance:
    def test_old_cluster_outside_60d_window_is_ignored(self) -> None:
        snaps = _make_snapshots([
            {"ticker": "TSLA", "as_of": "2026-06-15"},
        ])
        narratives = _make_narratives([
            # 120 days old → outside default 60-day tolerance
            {"ticker": "TSLA", "cluster_end_date": "2026-02-15",
             "sim_buyback_authorization": 0.80},
        ])
        merged = _merge_narrative_asof(snaps, narratives)
        row = merged.iloc[0]
        assert row["has_recent_narrative"] == False  # noqa: E712
        assert row["sim_buyback_authorization"] == 0.0
        assert row["narrative_age_days"] == 0.0  # sentinel for unmatched

    def test_custom_tolerance_can_widen_window(self) -> None:
        snaps = _make_snapshots([
            {"ticker": "TSLA", "as_of": "2026-06-15"},
        ])
        narratives = _make_narratives([
            {"ticker": "TSLA", "cluster_end_date": "2026-02-15",
             "sim_buyback_authorization": 0.80},
        ])
        # Widen tolerance to 180 days — should now match
        merged = _merge_narrative_asof(
            snaps, narratives, max_age_days=180
        )
        assert merged.iloc[0]["has_recent_narrative"] == True  # noqa: E712
        assert merged.iloc[0]["sim_buyback_authorization"] == pytest.approx(0.80)


class TestPerTickerIsolation:
    def test_ticker_a_narrative_does_not_leak_to_ticker_b(self) -> None:
        """The ``by="ticker"`` keyword on merge_asof should isolate
        per-ticker matches; AAPL's cluster shouldn't show up on CRM
        rows."""
        snaps = _make_snapshots([
            {"ticker": "AAPL", "as_of": "2026-03-25"},
            {"ticker": "CRM", "as_of": "2026-03-25"},
        ])
        narratives = _make_narratives([
            {"ticker": "AAPL", "cluster_end_date": "2026-03-19",
             "sim_buyback_authorization": 0.99},
        ])
        merged = _merge_narrative_asof(snaps, narratives)
        # AAPL row gets the AAPL narrative
        aapl = merged[merged["ticker"] == "AAPL"].iloc[0]
        assert aapl["sim_buyback_authorization"] == pytest.approx(0.99)
        # CRM row gets nothing
        crm = merged[merged["ticker"] == "CRM"].iloc[0]
        assert crm["sim_buyback_authorization"] == 0.0
        assert crm["has_recent_narrative"] == False  # noqa: E712


class TestLookaheadSafety:
    def test_future_cluster_never_attached(self) -> None:
        """A snapshot's cluster_end_date strictly AFTER the training
        row's as_of must never be merged in — that's the entire point
        of direction='backward'."""
        snaps = _make_snapshots([
            {"ticker": "CRM", "as_of": "2026-03-10"},
        ])
        narratives = _make_narratives([
            # Cluster is 9 days AFTER the training row
            {"ticker": "CRM", "cluster_end_date": "2026-03-19",
             "sim_buyback_authorization": 0.74},
        ])
        merged = _merge_narrative_asof(snaps, narratives)
        assert merged.iloc[0]["has_recent_narrative"] == False  # noqa: E712
        assert merged.iloc[0]["sim_buyback_authorization"] == 0.0


class TestDefaultMaxAgeDays:
    def test_default_is_60_days(self) -> None:
        """Confirm the published default doesn't drift accidentally —
        an A/B sweep result is tied to this constant."""
        assert DEFAULT_NARRATIVE_MAX_AGE_DAYS == 60
