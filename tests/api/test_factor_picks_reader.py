"""factor_picks_reader translation tests.

Verifies the mapping from data/daily_picks/*.json to the BuySignal
schema preserves enough information that:
  * the web UI's existing color thresholds (composite_score >= 65/80)
    still light up sensibly,
  * sub-scores per factor are 0-100 percentile in the universe,
  * top quartile by z is labelled STRONG BUY,
  * missing picks or malformed JSON returns [] without raising.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.api.services.factor_picks_reader import (
    _rank_to_sub_score,
    _z_to_composite,
    find_latest_picks_file,
    load_latest_factor_picks,
)


def test_z_to_composite_clamps_and_rescales() -> None:
    assert _z_to_composite(-5.0) == pytest.approx(40.0)
    assert _z_to_composite(-2.5) == pytest.approx(40.0)
    assert _z_to_composite(0.0) == pytest.approx(40.0 + (2.5 / 5.5) * 55.0)
    assert _z_to_composite(3.0) == pytest.approx(95.0)
    assert _z_to_composite(10.0) == pytest.approx(95.0)


def test_rank_to_sub_score_percentile() -> None:
    assert _rank_to_sub_score(1, 100) == pytest.approx(100.0)
    assert _rank_to_sub_score(100, 100) == pytest.approx(0.0)
    assert _rank_to_sub_score(50, 100) == pytest.approx(50.5, rel=1e-2)


def test_rank_to_sub_score_handles_nan_and_none() -> None:
    assert _rank_to_sub_score(None, 100) is None
    assert _rank_to_sub_score(float("nan"), 100) is None
    assert _rank_to_sub_score("bad", 100) is None  # type: ignore[arg-type]
    # Universe size <= 1 is invalid.
    assert _rank_to_sub_score(1, 1) is None
    assert _rank_to_sub_score(1, 0) is None


def test_find_latest_picks_file_picks_greatest_date(tmp_path: Path) -> None:
    (tmp_path / "2026-05-10.json").write_text("{}")
    (tmp_path / "2026-05-15.json").write_text("{}")
    (tmp_path / "2026-05-12.json").write_text("{}")
    # Non-date stems must be skipped.
    (tmp_path / "execution_log.json").write_text("{}")
    found = find_latest_picks_file(tmp_path)
    assert found is not None
    assert found.name == "2026-05-15.json"


def test_find_latest_picks_file_returns_none_on_empty(tmp_path: Path) -> None:
    assert find_latest_picks_file(tmp_path) is None
    assert find_latest_picks_file(tmp_path / "missing") is None


def _write_picks(path: Path, picks: list[dict],
                  *, universe_size: int = 100,
                  strategy: str = "composite_d05_r63") -> None:
    payload = {
        "as_of": "2026-05-17",
        "generated_at_utc": "2026-05-17T07:10:28.215476+00:00",
        "strategy": strategy,
        "factors": ["momentum", "quality", "value"],
        "universe_size": universe_size,
        "top_n": len(picks),
        "picks": picks,
        "snapshot_id": None,
    }
    path.write_text(json.dumps(payload, default=str), encoding="utf-8")


def test_load_latest_factor_picks_translates_fields(tmp_path: Path) -> None:
    _write_picks(tmp_path / "2026-05-17.json", picks=[
        {
            "ticker": "APA", "z_score": 2.76, "rank": 1,
            "mom_rank": 24, "qual_rank": None, "val_rank": 20,
            "sector": "Energy",
        },
        {
            "ticker": "CF", "z_score": 2.28, "rank": 2,
            "mom_rank": 76, "qual_rank": 51.0, "val_rank": 50,
            "sector": "Basic Materials",
        },
        {
            "ticker": "NEM", "z_score": 2.20, "rank": 3,
            "mom_rank": 18, "qual_rank": 101.0, "val_rank": None,
            "sector": "Basic Materials",
        },
        {
            "ticker": "LOW", "z_score": 0.50, "rank": 24,
            "mom_rank": 200, "qual_rank": 200, "val_rank": 200,
            "sector": "Consumer",
        },
    ])
    signals = load_latest_factor_picks(tmp_path)
    assert len(signals) == 4
    # Sorted by composite_score desc → APA first.
    assert signals[0].ticker == "APA"
    assert signals[0].action == "STRONG BUY"
    assert signals[0].sector == "Energy"
    assert signals[0].sub_scores["momentum"] > 70  # rank 24/100
    assert "quality" not in signals[0].sub_scores  # was None → omitted
    assert signals[-1].action == "BUY"  # lower-z names get BUY
    # All rows share the synthetic run_id.
    assert all(s.run_id.startswith("factor:composite_d05_r63:")
               for s in signals)


def test_load_latest_factor_picks_empty_when_missing(tmp_path: Path) -> None:
    assert load_latest_factor_picks(tmp_path) == []


def test_load_latest_factor_picks_empty_on_malformed(tmp_path: Path) -> None:
    (tmp_path / "2026-05-17.json").write_text("not json {")
    assert load_latest_factor_picks(tmp_path) == []


def test_load_latest_factor_picks_skips_picks_without_ticker(tmp_path: Path) -> None:
    _write_picks(tmp_path / "2026-05-17.json", picks=[
        {"ticker": "A", "z_score": 1.0, "rank": 1,
         "mom_rank": 1, "qual_rank": 1, "val_rank": 1},
        {"z_score": 0.5, "rank": 2,  # no ticker
         "mom_rank": 2, "qual_rank": 2, "val_rank": 2},
    ])
    signals = load_latest_factor_picks(tmp_path)
    assert [s.ticker for s in signals] == ["A"]


def test_load_latest_factor_picks_attaches_z_to_confidence(tmp_path: Path) -> None:
    _write_picks(tmp_path / "2026-05-17.json", picks=[
        {"ticker": "A", "z_score": 2.34, "rank": 7,
         "mom_rank": 1, "qual_rank": 1, "val_rank": 1},
    ])
    signals = load_latest_factor_picks(tmp_path)
    assert "z=+2.34" in signals[0].confidence
    assert "rank=7" in signals[0].confidence
