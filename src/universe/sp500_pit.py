"""Point-in-time S&P 500 membership reconstruction.

Inputs
------
- ``data/universe/sp500_current.csv``  — today's constituent set
- ``data/universe/sp500_changes.csv``  — historical add/remove events

Algorithm
---------
Membership at date ``D`` is computed by walking the changes log and
undoing every event whose effective date is strictly after ``D``:

- An "add" after ``D`` means the ticker wasn't in the index at ``D`` →
  remove from the working set.
- A "remove" after ``D`` means the ticker was still in the index at
  ``D`` → add back to the working set.

The algorithm is order-independent: each ticker's events in the
(D, today] window net out correctly because S&P membership is binary
and events alternate state.

Coverage caveats
----------------
- The Wikipedia "Selected changes" log is comprehensive from ~2007
  onwards (≥20 events/year). Earlier years have gaps; do NOT trust
  reconstructions before 2008.
- Ticker renames (FB→META, GOOG/GOOGL splits) are NOT in the changes
  log. The "current" set carries the new symbol; backtests across a
  rename will see the new symbol on both sides, which is acceptable
  for index membership purposes but may break price fetches for the
  pre-rename window. Hand-curated rename map can be added later.

Reference anchors (validated in tests)
--------------------------------------
- TSLA  added 2020-12-21
- FB    added 2013-12-23 (FB→META rename not in changes log)
- BBBY  removed 2017-07-26
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date as _date
from pathlib import Path
from typing import Iterable

import pandas as pd


logger = logging.getLogger(__name__)

DEFAULT_CURRENT_PATH = Path("data/universe/sp500_current.csv")
DEFAULT_CHANGES_PATH = Path("data/universe/sp500_changes.csv")

# Earliest date we trust the reconstruction. Set by the gap analysis
# in scripts/fetch_sp500_membership.py — Wikipedia coverage hits
# ≥20 changes/year from 2007 onwards.
TRUSTED_FLOOR = pd.Timestamp("2008-01-01")


@dataclass(frozen=True)
class SP500Membership:
    """Immutable PIT membership oracle for the S&P 500.

    Construct via :func:`load_default_sp500` or
    :meth:`SP500Membership.from_csvs`. The constructor is intentionally
    cheap so callers can build one per backtest run.
    """

    # Current set (today's tickers, from sp500_current.csv).
    current: frozenset[str]
    # Events sorted ascending by date. Each row: date, action, ticker.
    changes: pd.DataFrame
    # Trusted floor — calls with as_of < this date warn-log.
    trusted_floor: pd.Timestamp = TRUSTED_FLOOR

    @classmethod
    def from_csvs(
        cls,
        current_path: Path = DEFAULT_CURRENT_PATH,
        changes_path: Path = DEFAULT_CHANGES_PATH,
        trusted_floor: pd.Timestamp | None = None,
    ) -> "SP500Membership":
        if not current_path.exists():
            raise FileNotFoundError(
                f"S&P 500 current list not found at {current_path}. "
                f"Run `uv run python -m scripts.fetch_sp500_membership` "
                f"to populate it.",
            )
        if not changes_path.exists():
            raise FileNotFoundError(
                f"S&P 500 changes log not found at {changes_path}. "
                f"Run `uv run python -m scripts.fetch_sp500_membership` "
                f"to populate it.",
            )

        cur_df = pd.read_csv(current_path)
        ch_df = pd.read_csv(changes_path)
        for col in ("symbol",):
            if col not in cur_df.columns:
                raise ValueError(
                    f"{current_path} missing required column '{col}'",
                )
        for col in ("date", "action", "ticker"):
            if col not in ch_df.columns:
                raise ValueError(
                    f"{changes_path} missing required column '{col}'",
                )

        ch_df = ch_df.copy()
        ch_df["date"] = pd.to_datetime(ch_df["date"], errors="coerce")
        ch_df = ch_df.dropna(subset=["date"])
        # Normalize tickers: uppercase, strip class-share suffixes that
        # Wikipedia sometimes wraps in odd unicode. Keep simple.
        ch_df["ticker"] = ch_df["ticker"].astype(str).str.strip().str.upper()
        ch_df["action"] = ch_df["action"].astype(str).str.strip().str.lower()
        ch_df = ch_df[ch_df["action"].isin({"add", "remove"})]
        ch_df = ch_df.sort_values("date").reset_index(drop=True)

        current = frozenset(
            cur_df["symbol"].astype(str).str.strip().str.upper().tolist(),
        )

        return cls(
            current=current,
            changes=ch_df,
            trusted_floor=trusted_floor or TRUSTED_FLOOR,
        )

    def as_of(self, target_date: _date | pd.Timestamp | str) -> frozenset[str]:
        """Return the S&P 500 constituents on ``target_date``.

        ``target_date`` is interpreted as "the start of trading on that
        date" — i.e., events with the same effective date are treated
        as already applied. (Convention: S&P announces changes with an
        effective date; the new constituent trades inside the index
        starting that day.)
        """
        d = pd.Timestamp(target_date)
        if d < self.trusted_floor:
            logger.warning(
                "PIT membership requested for %s — before trusted floor %s. "
                "Coverage gaps in changes log will inflate the universe.",
                d.date(), self.trusted_floor.date(),
            )

        # Working set = current minus any subsequent add (wasn't there yet)
        # plus any subsequent remove (was still there).
        working: set[str] = set(self.current)
        # Iterate ONLY events strictly after target_date (vectorized).
        after = self.changes[self.changes["date"] > d]
        for action, ticker in zip(
            after["action"].to_numpy(),
            after["ticker"].to_numpy(),
        ):
            if action == "add":
                working.discard(ticker)
            elif action == "remove":
                working.add(ticker)
        return frozenset(working)

    def all_tickers_ever(self) -> frozenset[str]:
        """Tickers that ever appeared in the index over the changes window.

        Useful for batch-fetching prices once and slicing per as_of()
        downstream. Includes survivors (current) + every ticker that
        was added or removed in the changes log.
        """
        ever = set(self.current)
        ever.update(self.changes["ticker"].tolist())
        return frozenset(ever)


def load_default_sp500() -> SP500Membership:
    """Convenience loader using the default CSV paths."""
    return SP500Membership.from_csvs()
