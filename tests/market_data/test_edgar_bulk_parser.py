"""Bulk DERA parser tests against a synthetic in-memory quarter zip.

No network calls — the fixture builds a tiny sub.txt + num.txt mirroring
the SEC DERA format and feeds it into ``parse_quarter_zip``.

Fixture shape:
  - 3 companies (CIKs 1/2/3 → AAPL/MSFT/TEST)
  - Per company: 2x 10-Q (2023-Q2 and 2024-Q2) + 1x 10-K (2024 annual).
  - Numeric facts cover the full balance-sheet / income-statement / cash-flow
    concept set the parser pulls from (Revenues, NetIncomeLoss, GrossProfit,
    OperatingIncomeLoss, StockholdersEquity, Assets, AssetsCurrent,
    LiabilitiesCurrent, LongTermDebt, NetCashProvidedByOperatingActivities,
    EarningsPerShareDiluted, CashAndCashEquivalentsAtCarryingValue).
  - One company (CIK 999) is in sub.txt but absent from the CIK map — used
    to assert "tickers absent from supplied map are dropped".

Assertions cover:
  - Snapshot count matches in-universe filings.
  - Derived ratios (gross_margin, profit_margin, operating_margin, roe,
    roa, debt_to_equity, current_ratio) hand-computed against the
    fixture values.
  - YoY growth populates on the 2024-Q2 row using the 2023-Q2 prior.
  - valid_to chains correctly within ticker.
  - CIKs absent from the map produce zero output rows.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from src.market_data.edgar_bulk.parser import parse_quarter_zip


# ---------------------------------------------------------------------------
# Synthetic fixture
# ---------------------------------------------------------------------------

# sub.txt schema we mimic: adsh \t cik \t form \t filed \t period
# We only emit the columns the parser actually reads; pandas with usecols
# tolerates extras but also tolerates "only these columns". `period` is the
# filing's report date (YYYYMMDD) — the parser keeps only num rows whose
# ddate matches it, dropping prior-year comparatives.
SUB_HEADER = "adsh\tcik\tform\tfiled\tperiod"

# num.txt schema: adsh \t tag \t ddate \t qtrs \t segments \t uom \t value
# `qtrs` = period length (0 instant, 1 quarter, 2/3 YTD, 4 annual); the parser
# keeps only the quarterly (10-Q) / annual (10-K) flow + instants. `segments`
# is non-empty for dimensional/segment rows (BusinessSegments=..., per-product
# revenue, ...) — the parser keeps only the consolidated (empty-segments) row.
NUM_HEADER = "adsh\ttag\tddate\tqtrs\tsegments\tuom\tvalue"

# Balance-sheet (point-in-time) concepts carry qtrs=0; everything else is a
# flow (qtrs=1 in a 10-Q, qtrs=4 in a 10-K).
_INSTANT_TAGS = frozenset({
    "StockholdersEquity", "Assets", "AssetsCurrent", "LiabilitiesCurrent",
    "LongTermDebt", "CashAndCashEquivalentsAtCarryingValue",
})

# The filing report date shared by every fixture filing (kept uniform, like
# the original ddate, so the valid_from-from-filed test stays meaningful).
_FIXTURE_PERIOD = "20240630"


def _qtrs_for(tag: str, form: str) -> int:
    if tag in _INSTANT_TAGS:
        return 0
    return 4 if form.upper() == "10-K" else 1


# Per-filing values designed so derived ratios are exact decimals.
# 2024-Q2 (filed 2024-08-01): revenue=120, gross=60 (margin 0.5),
#   net_income=15 (profit_margin 0.125), op_income=24 (op_margin 0.2),
#   equity=200 (roe 0.075), assets=500 (roa 0.03),
#   ltd=60 (d/e 0.3), current_assets=150, current_liabilities=75 (cr 2.0)
# 2023-Q2 (filed 2023-08-01): revenue=100, net_income=10, eps=0.50
# 2024 10-K (filed 2024-12-15): full-year revenue=400, net_income=50
# We only fully populate the 2024-Q2 derived-ratio columns; 2023-Q2 carries
# the YoY-source data; the 10-K is just there to prove form-filtering and
# source-tagging work.

_AAPL_FILINGS = [
    # (adsh, form, filed_yyyymmdd, [(tag, value), ...])
    (
        "0000000001-23-000001", "10-Q", "20230801",
        [
            ("Revenues", 100.0),
            ("NetIncomeLoss", 10.0),
            ("EarningsPerShareDiluted", 0.50),
        ],
    ),
    (
        "0000000001-24-000001", "10-Q", "20240801",
        [
            ("Revenues", 120.0),
            ("NetIncomeLoss", 15.0),
            ("EarningsPerShareDiluted", 0.75),
            ("GrossProfit", 60.0),
            ("OperatingIncomeLoss", 24.0),
            ("StockholdersEquity", 200.0),
            ("Assets", 500.0),
            ("AssetsCurrent", 150.0),
            ("LiabilitiesCurrent", 75.0),
            ("LongTermDebt", 60.0),
            ("CashAndCashEquivalentsAtCarryingValue", 40.0),
            ("NetCashProvidedByOperatingActivities", 30.0),
        ],
    ),
    (
        "0000000001-24-000002", "10-K", "20241215",
        [
            ("Revenues", 400.0),
            ("NetIncomeLoss", 50.0),
            ("EarningsPerShareDiluted", 2.50),
        ],
    ),
]

# MSFT — different values so we can assert per-ticker isolation
_MSFT_FILINGS = [
    (
        "0000000002-23-000001", "10-Q", "20230801",
        [
            ("Revenues", 200.0),
            ("NetIncomeLoss", 30.0),
            ("EarningsPerShareDiluted", 1.00),
        ],
    ),
    (
        "0000000002-24-000001", "10-Q", "20240801",
        [
            ("Revenues", 250.0),
            ("NetIncomeLoss", 40.0),
            ("EarningsPerShareDiluted", 1.25),
        ],
    ),
    (
        "0000000002-24-000002", "10-K", "20241215",
        [
            ("Revenues", 900.0),
            ("NetIncomeLoss", 120.0),
            ("EarningsPerShareDiluted", 3.80),
        ],
    ),
]

# TEST — minimal, gets dropped from universe assertion via map filtering test
_TEST_FILINGS = [
    (
        "0000000003-24-000001", "10-Q", "20240801",
        [
            ("Revenues", 50.0),
            ("NetIncomeLoss", 5.0),
        ],
    ),
]

# UNMAPPED — present in sub.txt but its CIK isn't in the map we pass.
# Used to prove the orchestrator drops out-of-universe filings.
_UNMAPPED_FILINGS = [
    (
        "0000000999-24-000001", "10-Q", "20240801",
        [
            ("Revenues", 999.0),
            ("NetIncomeLoss", 99.0),
        ],
    ),
]

# Noise: 8-K filings (must be filtered out) + an Assets row for AAPL with a
# bogus tag (must be ignored).
_NOISE_FILINGS = [
    (
        "0000000001-24-000099", "8-K", "20240601",
        [
            ("Revenues", 9999.0),  # should never appear in output (8-K filtered)
        ],
    ),
]

# Period/segment noise the parser must DROP, for AAPL's 2024-Q2 filing.
# Emitted BEFORE the clean rows so that — absent the qtrs/ddate/segments
# filters — the parser's first-wins selection would pick these wrong values,
# failing the eps/revenue assertions. (adsh, tag, ddate, qtrs, segments, value)
_PERIOD_NOISE = [
    ("0000000001-24-000001", "EarningsPerShareDiluted", _FIXTURE_PERIOD, 2, "", 1.40),  # YTD EPS
    ("0000000001-24-000001", "EarningsPerShareDiluted", "20230630", 1, "", 9.99),  # prior-yr Q (wrong ddate)
    ("0000000001-24-000001", "Revenues", _FIXTURE_PERIOD, 2, "", 230.0),  # YTD revenue
    ("0000000001-24-000001", "Revenues", _FIXTURE_PERIOD, 1, "ProductOrService=IPhone;", 45.0),  # segment revenue
]


def _build_sub_txt() -> str:
    lines = [SUB_HEADER]
    cik_filings = [
        (1, _AAPL_FILINGS),
        (2, _MSFT_FILINGS),
        (3, _TEST_FILINGS),
        (999, _UNMAPPED_FILINGS),
        (1, _NOISE_FILINGS),
    ]
    for cik, filings in cik_filings:
        for adsh, form, filed, _facts in filings:
            lines.append(f"{adsh}\t{cik}\t{form}\t{filed}\t{_FIXTURE_PERIOD}")
    return "\n".join(lines) + "\n"


def _build_num_txt() -> str:
    lines = [NUM_HEADER]
    # Period/segment decoys first — first-wins would pick these without the fix.
    for adsh, tag, ddate, qtrs, segments, value in _PERIOD_NOISE:
        uom = "USD/shares" if tag == "EarningsPerShareDiluted" else "USD"
        lines.append(f"{adsh}\t{tag}\t{ddate}\t{qtrs}\t{segments}\t{uom}\t{value}")
    # A row with a garbage tag to prove tag-filtering works.
    lines.append(f"0000000001-24-000001\tBogusUnusedTag\t{_FIXTURE_PERIOD}\t0\t\tUSD\t12345.0")
    all_filings = (
        _AAPL_FILINGS + _MSFT_FILINGS + _TEST_FILINGS
        + _UNMAPPED_FILINGS + _NOISE_FILINGS
    )
    for adsh, form, _filed, facts in all_filings:
        for tag, value in facts:
            uom = "USD/shares" if tag == "EarningsPerShareDiluted" else "USD"
            # ddate == period + empty segments for the clean rows; qtrs marks
            # the duration so the parser keeps the quarterly/annual flow + instants.
            lines.append(
                f"{adsh}\t{tag}\t{_FIXTURE_PERIOD}\t{_qtrs_for(tag, form)}\t\t{uom}\t{value}"
            )
    return "\n".join(lines) + "\n"


@pytest.fixture
def synthetic_zip(tmp_path: Path) -> Path:
    """Build a tiny in-memory DERA quarter zip on disk and return its path.

    Writes via ``zipfile.ZipFile`` from a BytesIO buffer, then flushes to
    ``tmp_path`` — parse_quarter_zip wants a file path it can re-open.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("sub.txt", _build_sub_txt())
        zf.writestr("num.txt", _build_num_txt())
        # tag.txt / pre.txt aren't consumed but a real DERA zip has them —
        # write empty placeholders so we exercise the "extra entries ignored"
        # path.
        zf.writestr("tag.txt", "tag\tversion\n")
        zf.writestr("pre.txt", "adsh\tline\n")
    path = tmp_path / "2024q2.zip"
    path.write_bytes(buf.getvalue())
    return path


@pytest.fixture
def cik_map() -> dict[int, str]:
    return {1: "AAPL", 2: "MSFT", 3: "TEST"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_one_snapshot_per_in_universe_filing(synthetic_zip, cik_map):
    """Three filings each for AAPL + MSFT (2x 10-Q + 1x 10-K), one 10-Q for TEST.
    8-K rows and out-of-universe CIK 999 should be dropped."""
    snaps = parse_quarter_zip(synthetic_zip, cik_map)
    tickers = [s.ticker for s in snaps]
    assert tickers.count("AAPL") == 3
    assert tickers.count("MSFT") == 3
    assert tickers.count("TEST") == 1
    assert len(snaps) == 7
    # Unmapped CIK should be entirely absent.
    assert all(s.ticker in {"AAPL", "MSFT", "TEST"} for s in snaps)


def test_unmapped_cik_is_dropped(synthetic_zip, cik_map):
    """When a CIK is in sub.txt but absent from the supplied map, its rows
    must not appear in the output. (This is a stronger guarantee than 'no
    ticker' — they should be filtered before snapshot construction.)"""
    snaps = parse_quarter_zip(synthetic_zip, cik_map)
    # The unmapped filing had revenue=999.0 — that exact value must not
    # appear under ANY ticker (would mean we leaked it under one of the
    # mapped tickers by accident).
    revenues = [s.revenue for s in snaps]
    assert 999.0 not in revenues


def test_eight_k_form_filtered(synthetic_zip, cik_map):
    """8-K filings should never produce a snapshot regardless of payload."""
    snaps = parse_quarter_zip(synthetic_zip, cik_map)
    # 9999.0 was the revenue we attached to the 8-K filing as a tracer.
    revenues = [s.revenue for s in snaps]
    assert 9999.0 not in revenues


def test_10k_vs_10q_source_tag(synthetic_zip, cik_map):
    """Form 10-K maps to ``edgar_10k``; 10-Q maps to ``edgar_10q``."""
    snaps = parse_quarter_zip(synthetic_zip, cik_map)
    aapl = sorted([s for s in snaps if s.ticker == "AAPL"], key=lambda s: s.valid_from)
    assert aapl[0].source == "edgar_10q"  # 2023-08-01
    assert aapl[1].source == "edgar_10q"  # 2024-08-01
    assert aapl[2].source == "edgar_10k"  # 2024-12-15


def test_2024q2_aapl_derived_ratios(synthetic_zip, cik_map):
    """All derived ratios for the fully-populated AAPL 2024-Q2 filing."""
    snaps = parse_quarter_zip(synthetic_zip, cik_map)
    aapl_2024_q2 = next(
        s for s in snaps
        if s.ticker == "AAPL"
        and s.valid_from.year == 2024
        and s.source == "edgar_10q"
    )
    # 60 / 120 = 0.5
    assert aapl_2024_q2.gross_margin == pytest.approx(0.5)
    # 24 / 120 = 0.2
    assert aapl_2024_q2.operating_margin == pytest.approx(0.2)
    # 15 / 120 = 0.125
    assert aapl_2024_q2.profit_margin == pytest.approx(0.125)
    # 15 / 200 = 0.075
    assert aapl_2024_q2.roe == pytest.approx(0.075)
    # 15 / 500 = 0.03
    assert aapl_2024_q2.roa == pytest.approx(0.03)
    # 60 / 200 = 0.3
    assert aapl_2024_q2.debt_to_equity == pytest.approx(0.3)
    # 150 / 75 = 2.0
    assert aapl_2024_q2.current_ratio == pytest.approx(2.0)
    # Raw values preserved
    assert aapl_2024_q2.revenue == pytest.approx(120.0)
    assert aapl_2024_q2.eps_diluted == pytest.approx(0.75)
    assert aapl_2024_q2.total_cash == pytest.approx(40.0)
    assert aapl_2024_q2.total_debt == pytest.approx(60.0)
    assert aapl_2024_q2.free_cash_flow == pytest.approx(30.0)


def test_yoy_growth_aapl_q2(synthetic_zip, cik_map):
    """2024-Q2 should match 2023-Q2 (same source, ~365d apart) → +20%
    revenue, +50% EPS growth."""
    snaps = parse_quarter_zip(synthetic_zip, cik_map)
    aapl = sorted([s for s in snaps if s.ticker == "AAPL"], key=lambda s: s.valid_from)
    aapl_2023 = aapl[0]
    aapl_2024_q2 = aapl[1]
    # No prior-year row exists for the first 10-Q.
    assert aapl_2023.revenue_growth_yoy is None
    assert aapl_2023.earnings_growth_yoy is None
    # 120 vs 100 = +20%, 0.75 vs 0.50 = +50%
    assert aapl_2024_q2.revenue_growth_yoy == pytest.approx(0.20)
    assert aapl_2024_q2.earnings_growth_yoy == pytest.approx(0.50)


def test_valid_to_chains_within_ticker(synthetic_zip, cik_map):
    """Each snapshot's valid_to should equal the next snapshot's valid_from
    for the same ticker; the most recent row's valid_to stays None."""
    snaps = parse_quarter_zip(synthetic_zip, cik_map)
    aapl = sorted([s for s in snaps if s.ticker == "AAPL"], key=lambda s: s.valid_from)
    assert aapl[0].valid_to == aapl[1].valid_from
    assert aapl[1].valid_to == aapl[2].valid_from
    assert aapl[2].valid_to is None


def test_valid_from_uses_filed_date(synthetic_zip, cik_map):
    """valid_from must come from the ``filed`` column (filing date), not the
    period-end ``ddate``. The fixture uses ddate=20240630 for every row but
    filed dates of 20230801 / 20240801 / 20241215 — assert valid_from
    reflects the filed dates."""
    snaps = parse_quarter_zip(synthetic_zip, cik_map)
    aapl_filed = sorted(
        s.valid_from.strftime("%Y%m%d")
        for s in snaps if s.ticker == "AAPL"
    )
    assert aapl_filed == ["20230801", "20240801", "20241215"]


def test_missing_concepts_leave_fields_none(synthetic_zip, cik_map):
    """The TEST filing only reports Revenues + NetIncomeLoss. Derived ratios
    requiring missing inputs (e.g. roe needs equity) must be None, not 0
    or NaN."""
    snaps = parse_quarter_zip(synthetic_zip, cik_map)
    test_snap = next(s for s in snaps if s.ticker == "TEST")
    assert test_snap.revenue == pytest.approx(50.0)
    # gross_margin needs both GrossProfit and Revenues; only Revenues
    # was provided, so this stays None.
    assert test_snap.gross_margin is None
    assert test_snap.operating_margin is None
    assert test_snap.roe is None
    assert test_snap.roa is None
    assert test_snap.debt_to_equity is None
    assert test_snap.current_ratio is None


def test_period_filter_drops_ytd_and_comparatives(synthetic_zip, cik_map):
    """The AAPL 2024-Q2 filing also carries a YTD EPS (qtrs=2, 1.40), a
    prior-year quarterly EPS (wrong ddate, 9.99), a YTD revenue (qtrs=2, 230)
    and a per-segment revenue (segments='ProductOrService=IPhone;', 45) — all
    emitted BEFORE the clean rows. The qtrs/ddate/segments filters must drop
    them so the quarterly EPS (0.75) and consolidated revenue (120) survive.
    Without the fix, first-wins selection would surface 1.40 / 45 here."""
    snaps = parse_quarter_zip(synthetic_zip, cik_map)
    aapl_2024_q2 = next(
        s for s in snaps
        if s.ticker == "AAPL" and s.valid_from.year == 2024 and s.source == "edgar_10q"
    )
    assert aapl_2024_q2.eps_diluted == pytest.approx(0.75)
    assert aapl_2024_q2.revenue == pytest.approx(120.0)


def test_empty_map_returns_no_snapshots(synthetic_zip):
    """Edge case: when no CIKs in the zip overlap the supplied map, the
    parser short-circuits and returns []."""
    snaps = parse_quarter_zip(synthetic_zip, {42: "NOPE"})
    assert snaps == []
