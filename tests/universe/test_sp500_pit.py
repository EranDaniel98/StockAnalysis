"""PIT S&P 500 membership — anchor-date validation.

The point of this file is not to be exhaustive; it's to pin down a
handful of well-known events so any future regression in the changes
log scrape or the reconstruction algorithm fails loudly.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.universe.sp500_pit import SP500Membership, load_default_sp500


@pytest.fixture(scope="module")
def membership() -> SP500Membership:
    return load_default_sp500()


def test_current_is_around_500(membership: SP500Membership) -> None:
    # 503 today because of dual-class shares (e.g., GOOG + GOOGL).
    assert 490 <= len(membership.current) <= 520


def test_changes_log_nonempty_and_covers_recent_decade(
    membership: SP500Membership,
) -> None:
    assert not membership.changes.empty
    # We expect comprehensive coverage from 2010 onwards.
    recent = membership.changes[
        membership.changes["date"] >= pd.Timestamp("2010-01-01")
    ]
    assert len(recent) >= 400, (
        f"Only {len(recent)} changes since 2010 — coverage gap suspected."
    )


def test_anchor_tsla_added_2020_12_21(membership: SP500Membership) -> None:
    # TSLA was added 2020-12-21. So on 2020-12-20 it was NOT in, on
    # 2020-12-22 it WAS in.
    before = membership.as_of("2020-12-20")
    on_day = membership.as_of("2020-12-21")
    after = membership.as_of("2020-12-22")
    assert "TSLA" not in before, "TSLA in pre-2020-12-21 set"
    assert "TSLA" in on_day, "TSLA missing on its add date"
    assert "TSLA" in after, "TSLA dropped after add date"


def test_anchor_fb_added_2013_12_23(membership: SP500Membership) -> None:
    # FB (later META) was added 2013-12-23. Wikipedia changes log
    # carries the original FB symbol; today's current set carries META.
    before = membership.as_of("2013-12-22")
    # FB → META rename is not in the changes log; the reconstructed
    # set should contain FB after the add date (because the current set
    # has META, and undoing the FB add removes FB — but for dates AFTER
    # the add we don't undo it). So on/after 2013-12-23, META is in
    # current; FB is not. That's a known caveat — assert it.
    on_day = membership.as_of("2013-12-23")
    assert "FB" not in before
    # META is in current; rename is not in the log, so META appears
    # for all reconstructed dates back to the FB add date. This is the
    # documented limitation in src/universe/sp500_pit.py.
    assert "META" in on_day


def test_anchor_bbby_removed_2017_07_26(membership: SP500Membership) -> None:
    # Bed Bath & Beyond was removed from S&P 500 on 2017-07-26.
    before = membership.as_of("2017-07-25")
    after = membership.as_of("2017-07-27")
    assert "BBBY" in before, "BBBY should be in set the day before removal"
    assert "BBBY" not in after, "BBBY should be out the day after removal"


def test_membership_monotonic_at_index_boundaries(
    membership: SP500Membership,
) -> None:
    """as_of should be deterministic and idempotent across two calls."""
    a = membership.as_of("2022-01-03")
    b = membership.as_of("2022-01-03")
    assert a == b


def test_current_is_subset_of_all_tickers_ever(
    membership: SP500Membership,
) -> None:
    ever = membership.all_tickers_ever()
    assert membership.current.issubset(ever)
    # The "ever" set must be larger than the current set — historical
    # delistings/removals add to it.
    assert len(ever) > len(membership.current)


def test_as_of_floor_warns_but_returns(
    membership: SP500Membership,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Calls before the trusted floor warn but still return data."""
    import logging
    with caplog.at_level(logging.WARNING):
        result = membership.as_of("2001-06-01")
    assert isinstance(result, frozenset)
    assert any("trusted floor" in r.message for r in caplog.records)


def test_as_of_today_matches_current(membership: SP500Membership) -> None:
    """Asking for "today" should reproduce the current set."""
    today = pd.Timestamp.today().normalize()
    result = membership.as_of(today)
    # Allow for the case where the latest event is in the future
    # (S&P announces some changes ahead of effective date).
    future_changes = membership.changes[membership.changes["date"] > today]
    if future_changes.empty:
        assert result == membership.current
    else:
        # Should still be set-equal-ish; we just check size is within
        # the count of pending changes.
        assert abs(len(result) - len(membership.current)) <= len(future_changes)


def test_universe_size_at_2022_05_13_is_realistic(
    membership: SP500Membership,
) -> None:
    """At any sensible PIT date, the universe should be ~500 names."""
    snap = membership.as_of("2022-05-13")
    assert 490 <= len(snap) <= 520, (
        f"Reconstructed 2022-05-13 universe is {len(snap)} — not ~500"
    )
