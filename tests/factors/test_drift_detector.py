"""Drift-detector tests.

Pin each check against synthetic pick files written to tmp_path so we
can drive the exact failure modes without depending on real history.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.factors.drift_detector import (
    DriftCheck, DriftReport, compute_drift_report, format_markdown,
)


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _baseline_payload(
    n_universe: int = 490, picks: list[dict] | None = None,
    factors: list[str] | None = None,
) -> dict:
    if picks is None:
        picks = [
            {
                "ticker": f"T{i:02d}",
                "sector": "Tech" if i % 2 == 0 else "Energy",
                "mom_rank": 5, "qual_rank": 10, "val_rank": 15,
                "z_score": 2.0 + i * 0.01,
            }
            for i in range(24)
        ]
    return {
        "as_of": "2026-05-17",
        "universe_size": n_universe,
        "factors": factors or ["momentum", "quality", "value"],
        "picks": picks,
    }


def test_first_run_no_history_is_ok(tmp_path: Path) -> None:
    today = tmp_path / "2026-05-18.json"
    _write(today, _baseline_payload())
    rep = compute_drift_report(today, tmp_path)
    assert rep.overall_status in ("ok", "warn")
    # The history-less branch should NOT trip a fail.
    fails = [c for c in rep.checks if c.status == "fail"]
    assert not fails


def test_universe_shrink_20pct_fails(tmp_path: Path) -> None:
    # 10 days of stable baseline.
    for d in range(10):
        _write(tmp_path / f"2026-05-{d:02d}.json", _baseline_payload(490))
    # Today: dropped from 490 to 360 = -26.5%.
    _write(tmp_path / "2026-05-18.json", _baseline_payload(360))
    rep = compute_drift_report(tmp_path / "2026-05-18.json", tmp_path)
    universe_check = next(
        c for c in rep.checks if c.name == "universe_size_drift"
    )
    assert universe_check.status == "fail"
    assert rep.overall_status == "fail"


def test_universe_shrink_15pct_warns(tmp_path: Path) -> None:
    for d in range(10):
        _write(tmp_path / f"2026-05-{d:02d}.json", _baseline_payload(490))
    # 490 -> 410 = -16%
    _write(tmp_path / "2026-05-18.json", _baseline_payload(410))
    rep = compute_drift_report(tmp_path / "2026-05-18.json", tmp_path)
    universe_check = next(
        c for c in rep.checks if c.name == "universe_size_drift"
    )
    assert universe_check.status == "warn"


def test_factor_coverage_collapse_fails(tmp_path: Path) -> None:
    """Quality column drops to all-None: should fail."""
    for d in range(10):
        _write(tmp_path / f"2026-05-{d:02d}.json", _baseline_payload(490))
    # Today: every pick has quality=None.
    broken_picks = [
        {
            "ticker": f"T{i:02d}",
            "sector": "Tech",
            "mom_rank": 5, "qual_rank": None, "val_rank": 15,
            "z_score": 2.0 + i * 0.01,
        } for i in range(24)
    ]
    _write(tmp_path / "2026-05-18.json", _baseline_payload(
        490, picks=broken_picks,
    ))
    rep = compute_drift_report(tmp_path / "2026-05-18.json", tmp_path)
    qual_check = next(
        c for c in rep.checks if c.name == "factor_coverage_quality"
    )
    assert qual_check.status == "fail"
    assert rep.overall_status == "fail"


def test_factor_coverage_topn_shrink_with_full_coverage_is_ok(
    tmp_path: Path,
) -> None:
    """Cutting top_n (e.g. 24 -> 15) with full per-factor coverage on
    both sides must NOT fail. Regression: the pre-ratio check compared
    raw counts and would flag any concentration ablation as drift."""
    for d in range(8):
        _write(tmp_path / f"2026-05-{d+1:02d}.json", _baseline_payload(490))
    smaller = [
        {
            "ticker": f"T{i:02d}", "sector": "Tech",
            "mom_rank": 5, "qual_rank": 10, "val_rank": 15,
            "z_score": 2.0,
        } for i in range(15)
    ]
    _write(
        tmp_path / "2026-05-18.json",
        _baseline_payload(490, picks=smaller),
    )
    rep = compute_drift_report(tmp_path / "2026-05-18.json", tmp_path)
    for f in ("momentum", "quality", "value"):
        check = next(
            c for c in rep.checks if c.name == f"factor_coverage_{f}"
        )
        assert check.status == "ok", (
            f"{f}: top_n change tripped coverage check ({check.message})"
        )


def test_factor_coverage_partial_drop_in_fraction_fails(tmp_path: Path) -> None:
    """Same top_n on both sides, but today only half the picks have
    quality data → fraction drops 100% -> 50% → fail."""
    for d in range(8):
        _write(tmp_path / f"2026-05-{d+1:02d}.json", _baseline_payload(490))
    half_missing = [
        {
            "ticker": f"T{i:02d}", "sector": "Tech",
            "mom_rank": 5,
            "qual_rank": None if i < 12 else 10,
            "val_rank": 15, "z_score": 2.0,
        } for i in range(24)
    ]
    _write(
        tmp_path / "2026-05-18.json",
        _baseline_payload(490, picks=half_missing),
    )
    rep = compute_drift_report(tmp_path / "2026-05-18.json", tmp_path)
    qual = next(
        c for c in rep.checks if c.name == "factor_coverage_quality"
    )
    assert qual.status == "fail"


def test_sector_concentration_over_50_fails(tmp_path: Path) -> None:
    one_sector = [
        {
            "ticker": f"T{i:02d}", "sector": "Financial Services",
            "mom_rank": 5, "qual_rank": 10, "val_rank": 15,
            "z_score": 2.0,
        } for i in range(24)
    ]
    _write(
        tmp_path / "2026-05-18.json",
        _baseline_payload(490, picks=one_sector),
    )
    rep = compute_drift_report(tmp_path / "2026-05-18.json", tmp_path)
    sector_check = next(
        c for c in rep.checks if c.name == "sector_concentration"
    )
    assert sector_check.status == "fail"


def test_unknown_sector_share_above_20_warns(tmp_path: Path) -> None:
    half_unknown = [
        {
            "ticker": f"T{i:02d}",
            "sector": "Unknown" if i < 12 else "Tech",
            "mom_rank": 5, "qual_rank": 10, "val_rank": 15,
            "z_score": 2.0,
        } for i in range(24)
    ]
    _write(
        tmp_path / "2026-05-18.json",
        _baseline_payload(490, picks=half_unknown),
    )
    rep = compute_drift_report(tmp_path / "2026-05-18.json", tmp_path)
    sector_check = next(
        c for c in rep.checks if c.name == "sector_concentration"
    )
    assert sector_check.status == "warn"


def test_top_z_3_sigma_outlier_fails(tmp_path: Path) -> None:
    # 10 prior days with varying top z_scores 2.0..2.45 so rolling
    # sigma is non-zero; today z=10 → far outside 3σ.
    for d in range(10):
        varying = _baseline_payload(490)
        for i, p in enumerate(varying["picks"]):
            # Top pick's z_score per day depends on the day index.
            p["z_score"] = 2.0 + d * 0.05 + i * 0.01
        _write(tmp_path / f"2026-05-{d:02d}.json", varying)
    high_z_picks = [
        {
            "ticker": "BLOWUP", "sector": "Tech",
            "mom_rank": 1, "qual_rank": 1, "val_rank": 1,
            "z_score": 10.0,
        }
    ] + [
        {
            "ticker": f"T{i:02d}", "sector": "Tech",
            "mom_rank": 5, "qual_rank": 10, "val_rank": 15,
            "z_score": 2.0,
        } for i in range(1, 24)
    ]
    _write(
        tmp_path / "2026-05-18.json",
        _baseline_payload(490, picks=high_z_picks),
    )
    rep = compute_drift_report(tmp_path / "2026-05-18.json", tmp_path)
    z_check = next(c for c in rep.checks if c.name == "composite_z_top")
    assert z_check.status == "fail"


def test_carry_rate_frozen_warns(tmp_path: Path) -> None:
    """Today's picks identical to yesterday's → frozen, warn."""
    payload = _baseline_payload()
    _write(tmp_path / "2026-05-17.json", payload)
    _write(tmp_path / "2026-05-18.json", payload)
    rep = compute_drift_report(tmp_path / "2026-05-18.json", tmp_path)
    carry = next(
        c for c in rep.checks if c.name == "hysteresis_carry_rate"
    )
    assert carry.status == "warn"
    assert "frozen" in carry.message.lower()


def test_carry_rate_zero_warns(tmp_path: Path) -> None:
    """No overlap with yesterday → hysteresis off (or didn't load)."""
    yesterday = _baseline_payload()
    today_picks = [
        {
            "ticker": f"X{i:02d}", "sector": "Tech",
            "mom_rank": 5, "qual_rank": 10, "val_rank": 15,
            "z_score": 2.0,
        } for i in range(24)
    ]
    _write(tmp_path / "2026-05-17.json", yesterday)
    _write(tmp_path / "2026-05-18.json", _baseline_payload(
        picks=today_picks,
    ))
    rep = compute_drift_report(tmp_path / "2026-05-18.json", tmp_path)
    carry = next(
        c for c in rep.checks if c.name == "hysteresis_carry_rate"
    )
    assert carry.status == "warn"


def test_format_markdown_renders_table(tmp_path: Path) -> None:
    _write(tmp_path / "2026-05-18.json", _baseline_payload())
    rep = compute_drift_report(tmp_path / "2026-05-18.json", tmp_path)
    md = format_markdown(rep)
    assert "Picks Drift Report" in md
    assert "universe_size_drift" in md


def test_factor_coverage_treats_nan_as_missing(tmp_path: Path) -> None:
    """Pandas writes NaN to JSON which decodes back as float('nan'), not
    None. The coverage check must treat NaN as missing OR the canary
    will silently mask broken upstream ingestion."""
    for d in range(5):
        _write(tmp_path / f"2026-05-{d:02d}.json", _baseline_payload(490))
    # Today: every pick has qual_rank == NaN (pandas-serialized).
    nan_picks = [
        {
            "ticker": f"T{i:02d}", "sector": "Tech",
            "mom_rank": 5, "qual_rank": float("nan"),
            "val_rank": 15, "z_score": 2.0 + i * 0.01,
        } for i in range(24)
    ]
    today_path = tmp_path / "2026-05-18.json"
    # NaN can't go through standard json.dumps; mimic pandas behavior
    # by writing the JSON manually.
    raw = json.dumps(
        _baseline_payload(490, picks=nan_picks),
        default=lambda o: None,
    )
    # The dumps above won't preserve NaN; rewrite with allow_nan
    # (which IS pandas' default) to faithfully reproduce the bug.
    today_path.write_text(
        json.dumps(_baseline_payload(490, picks=nan_picks), allow_nan=True),
        encoding="utf-8",
    )
    rep = compute_drift_report(today_path, tmp_path)
    qual_check = next(
        c for c in rep.checks if c.name == "factor_coverage_quality"
    )
    assert qual_check.status == "fail"


def test_unreadable_today_file_fails(tmp_path: Path) -> None:
    bad = tmp_path / "2026-05-18.json"
    bad.write_text("not json", encoding="utf-8")
    rep = compute_drift_report(bad, tmp_path)
    assert rep.overall_status == "fail"
