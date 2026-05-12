"""Pure-function tests for ml/registry.py.

The DB write/read paths (``register_run``, ``list_models``,
``latest_per_name``) need Postgres and live in integration tests. Here
we cover ``_to_pg_ts`` (timestamp coercion) and ``load_artifact``
(joblib round-trip + missing-file error).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import joblib
import pandas as pd
import pytest

from src.ml.registry import LoadedModel, _to_pg_ts, load_artifact


class TestToPgTs:
    def test_naive_datetime_becomes_utc(self) -> None:
        ts = _to_pg_ts(datetime(2025, 6, 1, 12, 0))
        assert ts.tzinfo is not None
        # Year/month/day preserved.
        assert (ts.year, ts.month, ts.day) == (2025, 6, 1)

    def test_aware_datetime_passes_through(self) -> None:
        original = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)
        ts = _to_pg_ts(original)
        assert ts == original

    def test_iso_string_becomes_utc_datetime(self) -> None:
        ts = _to_pg_ts("2025-06-01")
        assert ts.tzinfo is not None
        assert ts.year == 2025

    def test_naive_pandas_timestamp_becomes_utc(self) -> None:
        ts = _to_pg_ts(pd.Timestamp("2025-06-01"))
        assert ts.tzinfo is not None


@dataclass
class _StubRow:
    """Just enough of ModelVersion for load_artifact."""

    model_name: str
    version: int
    artifact_path: str


class TestLoadArtifact:
    def test_round_trips_joblib_payload(self, tmp_path) -> None:
        payload = {
            "model": "fake-estimator",
            "feature_cols": ["z_technical"],
            "horizon_days": 5,
            "params": {"alpha": 1.0},
        }
        path = tmp_path / "stub.joblib"
        joblib.dump(payload, path)

        row = _StubRow(model_name="stub_v1", version=1, artifact_path=str(path))
        loaded = load_artifact(row)
        assert isinstance(loaded, LoadedModel)
        assert loaded.row is row
        assert loaded.artifact["model"] == "fake-estimator"
        assert loaded.artifact["feature_cols"] == ["z_technical"]

    def test_missing_file_raises_FileNotFoundError(self, tmp_path) -> None:
        row = _StubRow(
            model_name="stub_v1",
            version=1,
            artifact_path=str(tmp_path / "does-not-exist.joblib"),
        )
        with pytest.raises(FileNotFoundError, match="missing artifact"):
            load_artifact(row)
