"""Tests for src.market_data.short_interest_finra.loader.

Two scopes:
  * the rolling-window helpers (pure functions, no DB)
  * the FINRA CSV parser (pure function, no network)

Loader tests use synthetic daily rows so we don't hit Postgres or
the network. The integration test for the SQL path lives elsewhere
(skipped without a live DB).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.market_data.short_interest_finra.client import (
    DailyShortRow,
    parse_daily_csv,
)
from src.market_data.short_interest_finra.loader import (
    WINDOW_DAYS,
    ShortInterestRow,
    _aggregate_daily,
    _rolling_series,
    build_series_from_daily,
)
from src.scoring.analyzers.short_interest import analyze as si_analyze


# ---------------------------------------------------------------------------
# rolling window helpers
# ---------------------------------------------------------------------------


def _daily_seq(
    *, start: date, n: int, short: int, total: int,
) -> list[tuple[date, int, int]]:
    """Generate ``n`` consecutive daily entries with constant values."""
    return [
        (start + timedelta(days=i), short, total)
        for i in range(n)
    ]


def test_rolling_series_returns_empty_when_too_few_days() -> None:
    daily = _daily_seq(start=date(2026, 1, 1), n=10, short=100, total=1000)
    out = build_series_from_daily(daily)
    assert out == []


def test_rolling_series_skips_warmup_then_emits_rows() -> None:
    daily = _daily_seq(start=date(2026, 1, 1), n=WINDOW_DAYS + 5, short=100, total=1000)
    out = build_series_from_daily(daily)
    # 30-day window → first WINDOW_DAYS-1 days are warm-up, so we
    # expect (n - WINDOW_DAYS + 1) = 6 emitted rows.
    assert len(out) == 6
    for row in out:
        assert isinstance(row, ShortInterestRow)
        # 30 days of 100 short_volume each → cumulative 3000
        assert row.short_interest_shares == 100 * WINDOW_DAYS
        # 30 days of 1000 total_volume → mean 1000
        assert row.avg_daily_volume == 1000
        # days_to_cover left to the analyzer
        assert row.days_to_cover is None


def test_rolling_series_handles_changing_volume() -> None:
    """Ramp up short volume sharply over the window — last row's sum
    should reflect the new level."""
    n_days = WINDOW_DAYS * 2
    start = date(2026, 1, 1)
    daily: list[tuple[date, int, int]] = []
    for i in range(n_days):
        if i < WINDOW_DAYS:
            daily.append((start + timedelta(days=i), 100, 1000))
        else:
            daily.append((start + timedelta(days=i), 300, 1000))
    out = build_series_from_daily(daily)
    # First emitted row covers days [0..WINDOW_DAYS-1] → sum=3000.
    assert out[0].short_interest_shares == 100 * WINDOW_DAYS
    # Last emitted row covers days [WINDOW_DAYS..2*WINDOW_DAYS-1] → sum=9000.
    assert out[-1].short_interest_shares == 300 * WINDOW_DAYS
    # avg_daily_volume stays 1000 the whole time.
    assert all(r.avg_daily_volume == 1000 for r in out)


def test_aggregate_daily_sums_duplicate_dates() -> None:
    """If a row sneaks in twice for the same date (shouldn't happen in
    practice due to the uq constraint, but we're defensive), the
    aggregate should sum them."""
    class FakeRow:
        def __init__(self, settlement_date: date, sv: int, tv: int) -> None:
            self.settlement_date = settlement_date
            self.short_volume = sv
            self.total_volume = tv

    rows = [
        FakeRow(date(2026, 1, 1), 100, 500),
        FakeRow(date(2026, 1, 1), 50, 200),  # dup of jan-1; sums with above
        FakeRow(date(2026, 1, 2), 600, 800),
    ]
    dates, sv, tv = _aggregate_daily(rows)  # type: ignore[arg-type]
    assert dates == [date(2026, 1, 1), date(2026, 1, 2)]
    assert sv == [150, 600]  # jan-1: 100+50, jan-2: 600
    assert tv == [700, 800]  # jan-1: 500+200, jan-2: 800


def test_rolling_series_feeds_analyzer_with_signal() -> None:
    """End-to-end: build a synthetic ramp-up series, feed the rolling
    rows into the analyzer, and confirm a bearish signal fires.

    Sharp ramp from 100→300 daily short volume crosses the analyzer's
    20% heavy-increase threshold in the 30-day-ago baseline window.
    """
    n_days = WINDOW_DAYS * 3
    start = date(2026, 1, 1)
    daily: list[tuple[date, int, int]] = []
    for i in range(n_days):
        if i < WINDOW_DAYS * 2:
            daily.append((start + timedelta(days=i), 100, 5000))
        else:
            daily.append((start + timedelta(days=i), 400, 5000))
    rows = build_series_from_daily(daily)
    assert rows  # the rolling helper produced output

    # As_of is the last emitted row's date.
    as_of = rows[-1].settlement_date
    result = si_analyze(rows, as_of=as_of)
    assert result is not None
    assert result["signals"][0]["type"] == "bearish"
    # 100→400 over the rolling window is a 3x increase, well past
    # heavy_increase_pct=0.20.
    assert result["indicators"]["change_30d_pct"] > 0.20


def test_rolling_series_squeeze_setup_emits_bullish() -> None:
    """Drop short volume by ~80% over the window after a crowded
    period — analyzer should label that bullish (covering)."""
    n_days = WINDOW_DAYS * 3
    start = date(2026, 1, 1)
    daily: list[tuple[date, int, int]] = []
    # Phase 1: heavy shorting (300/day)
    for i in range(WINDOW_DAYS * 2):
        daily.append((start + timedelta(days=i), 300, 5000))
    # Phase 2: shorts cover (50/day)
    for i in range(WINDOW_DAYS * 2, n_days):
        daily.append((start + timedelta(days=i), 50, 5000))
    rows = build_series_from_daily(daily)
    assert rows
    result = si_analyze(rows, as_of=rows[-1].settlement_date)
    assert result is not None
    assert result["signals"][0]["type"] == "bullish"
    assert result["indicators"]["change_30d_pct"] < -0.20


# ---------------------------------------------------------------------------
# FINRA CSV parser
# ---------------------------------------------------------------------------


def test_parse_daily_csv_basic() -> None:
    csv = (
        "Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n"
        "20260512|AAPL|1000000|50000|5000000|Q\n"
        "20260512|MSFT|800000|20000|4000000|Q\n"
        "File Trailer|2|0\n"
    )
    rows = parse_daily_csv(csv)
    by_ticker = {r.ticker: r for r in rows}
    assert "AAPL" in by_ticker
    assert "MSFT" in by_ticker
    assert by_ticker["AAPL"].short_volume == 1000000
    assert by_ticker["AAPL"].total_volume == 5000000
    assert by_ticker["AAPL"].short_exempt_volume == 50000
    assert by_ticker["AAPL"].settlement_date == date(2026, 5, 12)


def test_parse_daily_csv_aggregates_across_markets() -> None:
    """Same symbol shows up twice (Q + N venues) — must aggregate."""
    csv = (
        "Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n"
        "20260512|AAPL|600000|30000|3000000|Q\n"
        "20260512|AAPL|400000|20000|2000000|N\n"
    )
    rows = parse_daily_csv(csv)
    assert len(rows) == 1
    aapl = rows[0]
    assert aapl.ticker == "AAPL"
    assert aapl.short_volume == 1000000
    assert aapl.total_volume == 5000000
    assert aapl.short_exempt_volume == 50000


def test_parse_daily_csv_drops_zero_volume_rows() -> None:
    """Suspended symbols sometimes show with total_volume=0; drop them."""
    csv = (
        "Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n"
        "20260512|GOOD|1000|0|5000|Q\n"
        "20260512|DEAD|0|0|0|Q\n"
    )
    rows = parse_daily_csv(csv)
    tickers = {r.ticker for r in rows}
    assert "GOOD" in tickers
    assert "DEAD" not in tickers


def test_parse_daily_csv_uppercase_symbols() -> None:
    csv = (
        "Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n"
        "20260512|aapl|1000|0|5000|Q\n"
    )
    rows = parse_daily_csv(csv)
    assert rows[0].ticker == "AAPL"


def test_parse_daily_csv_uses_default_date_when_row_date_missing() -> None:
    """Some FINRA snapshots omit the Date column for the trailer line —
    the default_date kwarg fills in for rows that need it."""
    csv = (
        "Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n"
        "BAD|AAPL|1000|0|5000|Q\n"
    )
    rows = parse_daily_csv(csv, default_date=date(2026, 5, 12))
    assert len(rows) == 1
    assert rows[0].settlement_date == date(2026, 5, 12)


def test_parse_daily_csv_empty_input() -> None:
    assert parse_daily_csv("") == []
    assert parse_daily_csv("   \n") == []


def test_parse_daily_csv_missing_required_columns() -> None:
    """If FINRA changes the schema and drops a required column, we want
    a loud ExternalAPIError, not silent zero rows."""
    from src.contracts.errors import ExternalAPIError

    csv = (
        "Date|Symbol|FooBar|Market\n"
        "20260512|AAPL|1000|Q\n"
    )
    with pytest.raises(ExternalAPIError):
        parse_daily_csv(csv)
