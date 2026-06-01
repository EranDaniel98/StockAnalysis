"""Point-in-time quarterly accruals from SEC companyfacts (Postgres-free).

Sloan (1996) cash-flow accruals, per fiscal quarter:

    accrual = (NI_q - CFO_q) / avg_total_assets

keyed by the ORIGINAL filing date so a backtest at ``as_of`` only ever sees
accruals that were already public. Built as a sidecar to the factor snapshots
(``data/snapshots/<id>/accruals_pit.json``) so it needs no Postgres — the
existing ``FundamentalsPITLoader`` only serializes derived metrics (FCF, ROE,
margins), not the raw NI / CFO / Assets facts this needs.

Quarterly unpacking: companyfacts reports income-statement and cash-flow items
either as discrete 3-month facts or as cumulative year-to-date. We group every
duration fact by fiscal-year-start and take consecutive deltas
(``Q_n = cum_n - cum_{n-1}``), with a one-quarter span guard so a missing
interim quarter can't yield a contaminated double-quarter value. Balance-sheet
``Assets`` is an instant — keyed directly by period end. Concept names are
reused from ``src/market_data/edgar/concept_map.py`` so the two stay aligned.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from src.market_data.edgar.concept_map import DERIVED_CONCEPTS

_NI_CONCEPTS = DERIVED_CONCEPTS["net_income"]
_CFO_CONCEPTS = DERIVED_CONCEPTS["operating_cash_flow"]
_ASSETS_CONCEPTS = DERIVED_CONCEPTS["total_assets"]

# One fiscal quarter in days. A consecutive-cumulative delta is only trusted
# when the two period-ends are ~one quarter apart; otherwise an interim quarter
# is missing and the delta would span two quarters.
_QUARTER_LO, _QUARTER_HI = 70, 100


@dataclass(frozen=True)
class AccrualRecord:
    ticker: str
    valid_from: datetime  # original filing date (tz-aware UTC) — PIT timestamp
    period_end: date
    net_income: float
    operating_cash_flow: float
    total_assets: float
    accrual: float  # (NI - CFO) / avg_assets; high = low earnings quality


def _facts(us_gaap: dict[str, Any], concepts: list[str]) -> list[dict[str, Any]]:
    """Merge USD facts across concept variants (e.g. the three CFO tags)."""
    out: list[dict[str, Any]] = []
    for c in concepts:
        out.extend(us_gaap.get(c, {}).get("units", {}).get("USD", []))
    return out


def _quarterly_flow(
    us_gaap: dict[str, Any], concepts: list[str]
) -> dict[date, tuple[float, str]]:
    """Discrete-quarter values for a flow concept (NI, CFO).

    Returns ``{period_end: (discrete_value, filed_iso)}``. Dedupes raw facts by
    (start, end) keeping the EARLIEST filing — companyfacts echoes prior-period
    comparatives in later filings, and PIT wants first public disclosure, not
    the restated echo. Then groups by fiscal-year-start and deltas consecutive
    cumulative ends, gated to a single-quarter span.
    """
    best: dict[tuple[str, str], tuple[float, str]] = {}
    for f in _facts(us_gaap, concepts):
        start, end, filed, val = f.get("start"), f.get("end"), f.get("filed"), f.get("val")
        if not (start and end and filed) or val is None:
            continue
        key = (start, end)
        if key not in best or filed < best[key][1]:
            best[key] = (float(val), filed)

    by_start: dict[str, list[tuple[date, float, str]]] = defaultdict(list)
    for (start, end), (val, filed) in best.items():
        by_start[start].append((date.fromisoformat(end), val, filed))

    out: dict[date, tuple[float, str]] = {}
    for start, rows in by_start.items():
        rows.sort()
        start_d = date.fromisoformat(start)
        for i, (end, val, filed) in enumerate(rows):
            if i == 0:
                span = (end - start_d).days
                discrete = val
            else:
                span = (end - rows[i - 1][0]).days
                discrete = val - rows[i - 1][1]
            if not (_QUARTER_LO <= span <= _QUARTER_HI):
                continue
            if end not in out or filed < out[end][1]:
                out[end] = (discrete, filed)
    return out


def _assets_by_end(us_gaap: dict[str, Any]) -> dict[date, float]:
    """Instant total-assets by period end (earliest filing wins)."""
    best: dict[date, tuple[float, str]] = {}
    for f in _facts(us_gaap, _ASSETS_CONCEPTS):
        end, filed, val = f.get("end"), f.get("filed"), f.get("val")
        if not (end and filed) or val is None or f.get("start"):
            continue  # require an instant (no start) — balance-sheet fact
        e = date.fromisoformat(end)
        if e not in best or filed < best[e][1]:
            best[e] = (float(val), filed)
    return {e: v for e, (v, _) in best.items()}


def extract_accruals(ticker: str, facts_json: dict[str, Any]) -> list[AccrualRecord]:
    """One company's companyfacts -> chronological quarterly accrual records."""
    us_gaap = facts_json.get("facts", {}).get("us-gaap", {})
    if not us_gaap:
        return []
    ni = _quarterly_flow(us_gaap, _NI_CONCEPTS)
    cfo = _quarterly_flow(us_gaap, _CFO_CONCEPTS)
    assets = _assets_by_end(us_gaap)

    ends = sorted(set(ni) & set(cfo) & set(assets))
    records: list[AccrualRecord] = []
    for i, end in enumerate(ends):
        ni_q, ni_filed = ni[end]
        cfo_q, cfo_filed = cfo[end]
        ta = assets[end]
        prev_ta = assets[ends[i - 1]] if i > 0 else ta
        avg_assets = (ta + prev_ta) / 2.0
        if avg_assets <= 0:
            continue
        # PIT timestamp = the later of the NI / CFO disclosures (both come from
        # the same 10-Q/K, but guard against a split disclosure).
        filed = max(ni_filed, cfo_filed)
        records.append(
            AccrualRecord(
                ticker=ticker.upper(),
                valid_from=datetime.strptime(filed, "%Y-%m-%d").replace(
                    hour=12, tzinfo=timezone.utc
                ),
                period_end=end,
                net_income=ni_q,
                operating_cash_flow=cfo_q,
                total_assets=ta,
                accrual=(ni_q - cfo_q) / avg_assets,
            )
        )
    records.sort(key=lambda r: r.valid_from)
    return records


class AccrualsPITLoader:
    """In-memory PIT index over ``AccrualRecord`` rows, one bucket per ticker."""

    def __init__(self, records: list[AccrualRecord]) -> None:
        by_ticker: dict[str, list[AccrualRecord]] = defaultdict(list)
        for r in records:
            by_ticker[r.ticker].append(r)
        for rows in by_ticker.values():
            rows.sort(key=lambda r: r.valid_from)
        self._by_ticker = dict(by_ticker)

    def lookup(self, ticker: str, as_of: datetime) -> AccrualRecord | None:
        """Most recent record with ``valid_from <= as_of``, or None."""
        rows = self._by_ticker.get(ticker.upper())
        if not rows:
            return None
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=timezone.utc)
        chosen: AccrualRecord | None = None
        for r in rows:
            if r.valid_from <= as_of:
                chosen = r
            else:
                break
        return chosen

    def history(self, ticker: str, as_of: datetime) -> list[AccrualRecord]:
        """All records with ``valid_from <= as_of`` (oldest first) — for
        as-of asset-growth / placebo computations."""
        rows = self._by_ticker.get(ticker.upper())
        if not rows:
            return []
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=timezone.utc)
        return [r for r in rows if r.valid_from <= as_of]

    @property
    def tickers(self) -> set[str]:
        return set(self._by_ticker)

    def to_json(self, path: str | Path) -> None:
        rows = [
            {
                "ticker": r.ticker,
                "valid_from": r.valid_from.isoformat(),
                "period_end": r.period_end.isoformat(),
                "net_income": r.net_income,
                "operating_cash_flow": r.operating_cash_flow,
                "total_assets": r.total_assets,
                "accrual": r.accrual,
            }
            for rows in self._by_ticker.values()
            for r in rows
        ]
        Path(path).write_text(json.dumps(rows), encoding="utf-8")

    @classmethod
    def from_json(cls, path: str | Path) -> "AccrualsPITLoader":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        records = [
            AccrualRecord(
                ticker=r["ticker"],
                valid_from=datetime.fromisoformat(r["valid_from"]),
                period_end=date.fromisoformat(r["period_end"]),
                net_income=r["net_income"],
                operating_cash_flow=r["operating_cash_flow"],
                total_assets=r["total_assets"],
                accrual=r["accrual"],
            )
            for r in raw
        ]
        return cls(records)
