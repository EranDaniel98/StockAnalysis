"""Net-share-issuance factor (Pontiff-Woodgate 2008), PIT from companyfacts.

The composite-issuance anomaly: firms that ISSUE shares (dilution) subsequently
UNDERPERFORM; firms that REPURCHASE (shrink the count) outperform. The signal is
the trailing-1-year log change in shares outstanding:

    nsi_1y = log(shares_t / shares_{t-~1y})

keyed by the ORIGINAL filing date (PIT — a backtest at ``as_of`` only sees share
counts already public). Built as a sidecar to the factor snapshots
(``data/snapshots/<id>/nsi_pit.json``), Postgres-free, mirroring
``accruals_pit.py``.

Sign: low/negative nsi (buyback) is BULLISH. The factor's ``raw`` is ``-nsi_1y``
so higher = better, matching the other factors' "high rank = attractive" frame.

KNOWN LIMITATION — splits not adjusted. EDGAR share counts are as-reported, not
retroactively split-adjusted, so a 2:1 split looks like +100% issuance. We drop
events with ``|nsi_1y| > 0.5`` (~a split / large M&A) as a crude guard. This is a
first-screen approximation; if the factor shows cross-regime IC, replace the
guard with proper Polygon split-ratio adjustment before any backtest.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

# Prefer a point-in-time share COUNT (instant) for a clean year-over-year ratio;
# fall back to the weighted-average diluted count (duration fact, keyed by end).
_SHARES_INSTANT = ["CommonStockSharesOutstanding", "CommonStockSharesIssued"]
_SHARES_DURATION = [
    "WeightedAverageNumberOfDilutedSharesOutstanding",
    "WeightedAverageNumberOfSharesOutstandingDiluted",
    "WeightedAverageNumberOfSharesOutstanding",
    "WeightedAverageNumberOfSharesOutstandingBasic",
]
_YEAR_LO, _YEAR_HI = 300, 430   # days; a "1-year-prior" period-end must fall here
_SPLIT_GUARD = 0.5              # |log share ratio| above this ~ a split/M&A — drop


@dataclass(frozen=True)
class NSIRecord:
    ticker: str
    valid_from: datetime   # original filing date (tz-aware UTC) — PIT timestamp
    period_end: date
    shares: float
    nsi_1y: float          # log(shares_t / shares_~1y_prior); >0 = issuance (bearish)


def _shares_by_end(us_gaap: dict[str, Any]) -> dict[date, tuple[float, str]]:
    """{period_end: (shares, filed_iso)} — earliest filing wins (PIT first
    disclosure, not a later restated echo). Instant concepts preferred; falls
    back to weighted-average duration counts keyed by their period end."""
    best: dict[date, tuple[float, str]] = {}

    def _ingest(concepts: list[str], require_instant: bool) -> None:
        for c in concepts:
            for f in us_gaap.get(c, {}).get("units", {}).get("shares", []):
                end, filed, val = f.get("end"), f.get("filed"), f.get("val")
                if not (end and filed) or val is None or float(val) <= 0:
                    continue
                if require_instant and f.get("start"):
                    continue  # want a balance-sheet instant, not a duration
                e = date.fromisoformat(end)
                if e not in best or filed < best[e][1]:
                    best[e] = (float(val), filed)

    _ingest(_SHARES_INSTANT, require_instant=True)
    if not best:  # no instant share count — fall back to weighted-average duration
        _ingest(_SHARES_DURATION, require_instant=False)
    return best


def extract_net_share_issuance(ticker: str, facts_json: dict[str, Any]) -> list[NSIRecord]:
    """One company's companyfacts -> chronological NSI records (one per period-end
    with a valid ~1y-prior share count and a non-split-sized change)."""
    us_gaap = facts_json.get("facts", {}).get("us-gaap", {})
    if not us_gaap:
        return []
    shares = _shares_by_end(us_gaap)
    ends = sorted(shares)
    records: list[NSIRecord] = []
    for i, end in enumerate(ends):
        s_now, filed = shares[end]
        # nearest prior end ~1 year back (closest to 365d within the window)
        prior = min(
            (e for e in ends[:i] if _YEAR_LO <= (end - e).days <= _YEAR_HI),
            key=lambda e: abs((end - e).days - 365), default=None,
        )
        if prior is None:
            continue
        s_prior = shares[prior][0]
        if s_prior <= 0:
            continue
        nsi = math.log(s_now / s_prior)
        if abs(nsi) > _SPLIT_GUARD:
            continue  # split / large M&A — not organic issuance (see module docstring)
        records.append(NSIRecord(
            ticker=ticker.upper(),
            valid_from=datetime.strptime(filed, "%Y-%m-%d").replace(hour=12, tzinfo=timezone.utc),
            period_end=end,
            shares=s_now,
            nsi_1y=nsi,
        ))
    records.sort(key=lambda r: r.valid_from)
    return records


class NetShareIssuancePITLoader:
    """In-memory PIT index over ``NSIRecord`` rows, one bucket per ticker."""

    def __init__(self, records: list[NSIRecord]) -> None:
        by_ticker: dict[str, list[NSIRecord]] = defaultdict(list)
        for r in records:
            by_ticker[r.ticker].append(r)
        for rows in by_ticker.values():
            rows.sort(key=lambda r: r.valid_from)
        self._by_ticker = dict(by_ticker)

    def lookup(self, ticker: str, as_of: datetime) -> NSIRecord | None:
        rows = self._by_ticker.get(ticker.upper())
        if not rows:
            return None
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=timezone.utc)
        chosen: NSIRecord | None = None
        for r in rows:
            if r.valid_from <= as_of:
                chosen = r
            else:
                break
        return chosen

    @property
    def tickers(self) -> set[str]:
        return set(self._by_ticker)

    def to_json(self, path: str | Path) -> None:
        rows = [
            {"ticker": r.ticker, "valid_from": r.valid_from.isoformat(),
             "period_end": r.period_end.isoformat(), "shares": r.shares, "nsi_1y": r.nsi_1y}
            for bucket in self._by_ticker.values() for r in bucket
        ]
        Path(path).write_text(json.dumps(rows), encoding="utf-8")

    @classmethod
    def from_json(cls, path: str | Path) -> "NetShareIssuancePITLoader":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls([
            NSIRecord(
                ticker=r["ticker"], valid_from=datetime.fromisoformat(r["valid_from"]),
                period_end=date.fromisoformat(r["period_end"]), shares=r["shares"], nsi_1y=r["nsi_1y"],
            )
            for r in raw
        ])


def net_share_issuance_factor(
    loader: NetShareIssuancePITLoader, tickers: Iterable[str], as_of: pd.Timestamp,
) -> pd.DataFrame:
    """Cross-sectional NSI ranking at ``as_of``. raw = -nsi_1y (buyback bullish);
    rank 1 = largest net repurchaser. Returns ticker/raw/rank/z_score."""
    as_of_dt = pd.Timestamp(as_of).to_pydatetime()
    if as_of_dt.tzinfo is None:
        as_of_dt = as_of_dt.replace(tzinfo=timezone.utc)
    rows: list[dict] = []
    for t in tickers:
        rec = loader.lookup(t, as_of_dt)
        if rec is None:
            continue
        rows.append({"ticker": t, "raw": -rec.nsi_1y})
    if not rows:
        return pd.DataFrame(columns=["ticker", "raw", "rank", "z_score"])
    df = pd.DataFrame(rows)
    df["rank"] = df["raw"].rank(ascending=False, method="min").astype(int)
    sigma = df["raw"].std(ddof=0)
    df["z_score"] = 0.0 if (not sigma or pd.isna(sigma)) else (df["raw"] - df["raw"].mean()) / sigma
    return df[["ticker", "raw", "rank", "z_score"]].sort_values("rank").reset_index(drop=True)
