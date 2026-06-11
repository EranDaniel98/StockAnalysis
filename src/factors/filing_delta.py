"""Lazy-Prices filing-delta factor (pre-registered study wiring).

Signal: cosine similarity between a name's most recent 10-K/10-Q item text
(Item 1A + 7 / Part I Item 2) and its same-form filing ~1yr prior, read from
the per-snapshot sidecar ``filing_delta_signal.json`` built by
``scripts/research/build_filing_delta_sidecar.py``. HIGHER similarity = staler
filing = BULLISH (Cohen-Malloy-Nguyen 2020: changers underperform).

Resolution rule (fixed by the spec, reports/_lazy_prices_hypothesis.json): at
any ``as_of`` a ticker's value is the similarity of its most recent scored
record with ``accepted <= as_of`` and ``accepted >= as_of - 380d``; missing
when there is none — never filled. ``accepted`` is the SEC acceptance
TIMESTAMP, so a filing accepted intraday on ``as_of`` (midnight timestamp)
does not count yet — conservative, no same-day lookahead.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

SIDECAR_FILENAME = "filing_delta_signal.json"
TRAILING_DAYS = 380  # spec-fixed staleness window for an eligible filing


def sidecar_path(snapshot_id: str, snap_root: Path | str = "data/snapshots") -> Path:
    return Path(snap_root) / snapshot_id / SIDECAR_FILENAME


class FilingDeltaLoader:
    """In-memory (ticker, as_of) -> similarity resolver over sidecar records."""

    def __init__(self, by_ticker: dict[str, list[tuple[pd.Timestamp, float]]]):
        self._by_ticker = by_ticker

    @classmethod
    def from_json(cls, path: Path | str) -> "FilingDeltaLoader":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        by_ticker: dict[str, list[tuple[pd.Timestamp, float]]] = {}
        for r in payload.get("records", []):
            # similarity null = items/comparator missing -> the filing carries
            # no signal; skip it (the prior scored filing, if still inside the
            # trailing window, remains the live value — matches the sidecar's
            # own coverage accounting).
            if r.get("similarity") is None:
                continue
            by_ticker.setdefault(r["ticker"], []).append(
                (pd.Timestamp(r["accepted"]), float(r["similarity"]))
            )
        for hits in by_ticker.values():
            hits.sort(key=lambda x: x[0])
        return cls(by_ticker)

    @property
    def tickers(self) -> list[str]:
        return sorted(self._by_ticker)

    def value(self, ticker: str, as_of: pd.Timestamp) -> float | None:
        """Similarity of the most recent scored filing accepted <= as_of
        within the trailing ``TRAILING_DAYS``. None when absent."""
        hits = self._by_ticker.get(ticker)
        if not hits:
            return None
        as_of_ts = pd.Timestamp(as_of)
        lo = as_of_ts - pd.Timedelta(days=TRAILING_DAYS)
        for ts, sim in reversed(hits):
            if ts <= as_of_ts:
                return sim if ts >= lo else None
        return None


def filing_delta_factor(
    loader: FilingDeltaLoader,
    universe: list[str],
    as_of: pd.Timestamp | str,
) -> pd.DataFrame:
    """Cross-sectional filing-delta frame: ``ticker, raw, rank, z_score``.

    raw = similarity (higher = staler = bullish); rank 1 = stalest. Names
    without an eligible scored filing are dropped, never filled.
    """
    as_of_ts = pd.Timestamp(as_of)
    rows: list[dict] = []
    for ticker in universe:
        sim = loader.value(ticker, as_of_ts)
        if sim is not None:
            rows.append({"ticker": ticker, "raw": sim})
    if not rows:
        return pd.DataFrame(columns=["ticker", "raw", "rank", "z_score"])
    out = pd.DataFrame(rows)
    out["rank"] = out["raw"].rank(ascending=False, method="min").astype(int)
    mu = float(out["raw"].mean())
    sigma = float(out["raw"].std(ddof=0))
    out["z_score"] = (out["raw"] - mu) / sigma if sigma > 0 else 0.0
    return out.sort_values("rank").reset_index(drop=True)
