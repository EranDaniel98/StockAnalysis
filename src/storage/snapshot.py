"""Immutable backtest snapshot — freeze every yfinance-sourced input.

Why this exists
---------------

Two runs of the same backtest hours apart return different Sharpes
because yfinance back-applies dividend/split adjustments for several
days after the event. The audit chain measured a ±0.4 Sharpe drift
across pulls of the same window — comparable in magnitude to the
effect we're trying to test (see ``project_yfinance_nondeterminism``).

A backtest snapshot freezes the yfinance-sourced inputs once into
Parquet files in ``data/snapshots/<snapshot_id>/``. The snapshot is
content-addressed: two snapshots with identical data have identical
IDs. Re-runs of the engine reading the same snapshot ID produce
bit-identical results, modulo any deterministic engine internals.

What's frozen
-------------

* `prices.parquet`        — long-form OHLCV for the full universe + SPY + VIX
* `fundamentals.json`     — yfinance fundamental snapshot per ticker
                            (NB: yfinance fundamentals are PIT-now, not PIT-historical;
                            for fundamental-weighted strategies prefer the EDGAR PIT
                            loader instead of these — those rows live in Postgres
                            and are already deterministic across runs.)
* `earnings.parquet`      — earnings_date per ticker (long form)
* `manifest.json`         — snapshot_id, created_at, universe label,
                            window {start, end}, pipeline_version,
                            ticker list, and the content hashes used
                            to derive snapshot_id.

What's NOT frozen
-----------------

* EDGAR PIT fundamentals — already deterministic in Postgres.
* Insider/catalyst/short-interest tables — also Postgres-backed.
* The strategy YAML — file-system-versioned; record its hash in the
  result metadata if you want trace.

Snapshot ID
-----------

sha256 of (sorted ticker list || ISO start || ISO end || pipeline_version)
truncated to 16 hex chars. Same inputs → same ID. Different captured
universe → different ID. The same yfinance source data on two
different days → different IDs (because content hashes of the parquet
bytes are mixed in).

Loader contract
---------------

``SnapshotLoader.load()`` returns a dataclass with `price_data`,
`fundamentals`, `earnings_history`, `spy_df`, `vix_df` — the same
shapes the backtest engine receives from the live fetcher path.
Calling code never knows whether prices came from yfinance or a
snapshot.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional

import pandas as pd

logger = logging.getLogger(__name__)


SNAPSHOT_ROOT = Path("data/snapshots")
PRICES_FILE = "prices.parquet"
SPY_FILE = "spy.parquet"
VIX_FILE = "vix.parquet"
FUNDAMENTALS_FILE = "fundamentals.json"
EARNINGS_FILE = "earnings.parquet"
MANIFEST_FILE = "manifest.json"


@dataclass(frozen=True)
class SnapshotManifest:
    """Immutable description of a snapshot. Round-trips through JSON."""

    snapshot_id: str
    created_at: str  # ISO8601 UTC
    universe_label: str
    window_start: str  # ISO date
    window_end: str    # ISO date
    pipeline_version: str
    tickers: tuple[str, ...]
    n_tickers_with_prices: int
    n_tickers_with_fundamentals: int
    n_tickers_with_earnings: int
    has_spy: bool
    has_vix: bool
    content_hashes: Mapping[str, str] = field(default_factory=dict)
    # Optional. For PIT-reconstructed universes only — the as-of date
    # used to build the constituent list. None for static universes
    # (e.g., russell_1000). Kept separately from window_start because
    # the operator may pick an as-of different from window_start
    # (e.g., to test a single rebalance at the window mid-point).
    universe_as_of: Optional[str] = None

    def to_dict(self) -> dict:
        out = {
            "snapshot_id": self.snapshot_id,
            "created_at": self.created_at,
            "universe_label": self.universe_label,
            "window": {"start": self.window_start, "end": self.window_end},
            "pipeline_version": self.pipeline_version,
            "tickers": list(self.tickers),
            "n_tickers_with_prices": self.n_tickers_with_prices,
            "n_tickers_with_fundamentals": self.n_tickers_with_fundamentals,
            "n_tickers_with_earnings": self.n_tickers_with_earnings,
            "has_spy": self.has_spy,
            "has_vix": self.has_vix,
            "content_hashes": dict(self.content_hashes),
        }
        if self.universe_as_of is not None:
            out["universe_as_of"] = self.universe_as_of
        return out

    @staticmethod
    def from_dict(d: dict) -> "SnapshotManifest":
        win = d.get("window") or {}
        return SnapshotManifest(
            snapshot_id=d["snapshot_id"],
            created_at=d["created_at"],
            universe_label=d["universe_label"],
            window_start=win.get("start", ""),
            window_end=win.get("end", ""),
            pipeline_version=d["pipeline_version"],
            tickers=tuple(d.get("tickers", [])),
            n_tickers_with_prices=int(d.get("n_tickers_with_prices", 0)),
            n_tickers_with_fundamentals=int(d.get("n_tickers_with_fundamentals", 0)),
            n_tickers_with_earnings=int(d.get("n_tickers_with_earnings", 0)),
            has_spy=bool(d.get("has_spy", False)),
            has_vix=bool(d.get("has_vix", False)),
            content_hashes=dict(d.get("content_hashes", {})),
            universe_as_of=d.get("universe_as_of"),
        )


@dataclass
class SnapshotInputs:
    """Engine-shaped inputs reconstituted from a snapshot. Same field
    shapes as the live-fetcher path so the backtest engine doesn't
    know whether it's reading frozen data or fresh."""

    price_data: dict[str, pd.DataFrame]
    fundamentals: dict[str, dict]
    earnings_history: dict[str, pd.DataFrame]
    spy_df: Optional[pd.DataFrame]
    vix_df: Optional[pd.DataFrame]
    manifest: SnapshotManifest


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_file(path: Path) -> str:
    """SHA-256 of a file's contents. Refuses silently — caller checks
    return value before relying on it."""
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _compute_snapshot_id(
    tickers: list[str], window_start: str, window_end: str,
    pipeline_version: str, content_hashes: Mapping[str, str],
) -> str:
    """Content-addressed ID. Mixes the ticker list + window + pipeline
    version + content hashes of every frozen file. Two snapshots with
    identical input data therefore get identical IDs."""
    h = hashlib.sha256()
    for t in sorted(tickers):
        h.update(t.encode("utf-8"))
        h.update(b"\x00")
    h.update(window_start.encode("utf-8"))
    h.update(b"\x00")
    h.update(window_end.encode("utf-8"))
    h.update(b"\x00")
    h.update(pipeline_version.encode("utf-8"))
    h.update(b"\x00")
    for key in sorted(content_hashes.keys()):
        h.update(key.encode("utf-8"))
        h.update(b"\x00")
        h.update(content_hashes[key].encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


def _normalize_price_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Engine convention: tz-naive DatetimeIndex named 'Date' (or
    unnamed), OHLCV columns including 'Close'. Snapshot stores
    tz-naive UTC dates for stability."""
    if df is None or df.empty:
        return df
    out = df.copy()
    if isinstance(out.index, pd.DatetimeIndex):
        if out.index.tz is not None:
            out.index = out.index.tz_localize(None)
    else:
        out.index = pd.to_datetime(out.index)
    return out


def write_snapshot(
    *,
    price_data: dict[str, pd.DataFrame],
    fundamentals: dict[str, dict],
    earnings_history: dict[str, pd.DataFrame] | None,
    spy_df: pd.DataFrame | None,
    vix_df: pd.DataFrame | None,
    universe_label: str,
    window_start: pd.Timestamp,
    window_end: pd.Timestamp,
    pipeline_version: str,
    root: Path = SNAPSHOT_ROOT,
    universe_as_of: str | None = None,
) -> SnapshotManifest:
    """Persist a snapshot under ``root/<snapshot_id>/``.

    The snapshot directory is created fresh. We never write into an
    existing snapshot id (immutability — the same id always means the
    same content). Two-pass: write parquet files first, hash them,
    compute the content-addressed id, then move-or-rename into final
    location.

    Returns the manifest describing the new snapshot.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)

    # Staging dir — content hashes feed into the final id, so we don't
    # know the destination path yet.
    staging = root / f".staging_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}"
    if staging.exists():
        raise RuntimeError(f"staging path collision: {staging}")
    staging.mkdir(parents=True)

    tickers = sorted(price_data.keys())

    # ----- prices.parquet (long form) -----
    price_rows = []
    for ticker, df in price_data.items():
        if df is None or df.empty:
            continue
        d = _normalize_price_frame(df).copy()
        d.index.name = "date"
        d = d.reset_index()
        d["ticker"] = ticker
        # Keep only the OHLCV columns the engine reads from. Different
        # callers occasionally leave behind 'Adj Close' / 'Dividends'
        # which we don't need.
        keep = [c for c in ("date", "ticker", "Open", "High", "Low", "Close", "Volume") if c in d.columns]
        price_rows.append(d[keep])
    if price_rows:
        prices_long = pd.concat(price_rows, ignore_index=True)
        # Deterministic row order. Threaded fetchers hand us tickers in
        # completion order, which would otherwise vary the parquet bytes —
        # and thus the content-addressed snapshot_id — across identical runs.
        prices_long = prices_long.sort_values(["ticker", "date"]).reset_index(drop=True)
        prices_long.to_parquet(staging / PRICES_FILE, index=False)
    n_with_prices = sum(1 for df in price_data.values() if df is not None and not df.empty)

    # ----- spy / vix -----
    has_spy = spy_df is not None and not spy_df.empty
    has_vix = vix_df is not None and not vix_df.empty
    if has_spy:
        s = _normalize_price_frame(spy_df).copy()
        s.index.name = "date"
        s.reset_index().to_parquet(staging / SPY_FILE, index=False)
    if has_vix:
        v = _normalize_price_frame(vix_df).copy()
        v.index.name = "date"
        v.reset_index().to_parquet(staging / VIX_FILE, index=False)

    # ----- fundamentals.json -----
    # yfinance returns mixed types (Timestamps, floats, NaN, dicts).
    # Coerce to JSON-safe scalars; the engine consumes a plain dict.
    def _json_safe(v):
        if isinstance(v, pd.Timestamp):
            return v.isoformat()
        if isinstance(v, (int, str, bool)) or v is None:
            return v
        if isinstance(v, float):
            return v if pd.notna(v) else None
        try:
            f = float(v)
            return f if pd.notna(f) else None
        except (TypeError, ValueError):
            return str(v)

    fund_safe = {}
    for t, fd in fundamentals.items():
        if not isinstance(fd, dict):
            continue
        fund_safe[t] = {k: _json_safe(v) for k, v in fd.items()}
    (staging / FUNDAMENTALS_FILE).write_text(
        json.dumps(fund_safe, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    n_with_fund = len(fund_safe)

    # ----- earnings.parquet (long form: ticker, earnings_date) -----
    n_with_earn = 0
    if earnings_history:
        rows = []
        for ticker, df in earnings_history.items():
            if df is None or df.empty:
                continue
            # Each earnings frame has earnings dates either as the
            # index or as a column. Normalize to a 1-col long form.
            dates = None
            if isinstance(df.index, pd.DatetimeIndex):
                dates = df.index
            elif "Earnings Date" in df.columns:
                dates = pd.to_datetime(df["Earnings Date"])
            elif "earnings_date" in df.columns:
                dates = pd.to_datetime(df["earnings_date"])
            if dates is None or len(dates) == 0:
                continue
            d = pd.DataFrame({"ticker": ticker,
                              "earnings_date": pd.to_datetime(dates)})
            if d["earnings_date"].dt.tz is not None:
                d["earnings_date"] = d["earnings_date"].dt.tz_localize(None)
            rows.append(d)
            n_with_earn += 1
        if rows:
            earn_long = pd.concat(rows, ignore_index=True).sort_values(
                ["ticker", "earnings_date"]).reset_index(drop=True)
            earn_long.to_parquet(staging / EARNINGS_FILE, index=False)

    # ----- compute content hashes & snapshot id -----
    content_hashes = {
        PRICES_FILE: _hash_file(staging / PRICES_FILE),
        SPY_FILE: _hash_file(staging / SPY_FILE),
        VIX_FILE: _hash_file(staging / VIX_FILE),
        FUNDAMENTALS_FILE: _hash_file(staging / FUNDAMENTALS_FILE),
        EARNINGS_FILE: _hash_file(staging / EARNINGS_FILE),
    }
    snapshot_id = _compute_snapshot_id(
        tickers=tickers,
        window_start=str(pd.Timestamp(window_start).date()),
        window_end=str(pd.Timestamp(window_end).date()),
        pipeline_version=pipeline_version,
        content_hashes=content_hashes,
    )

    final = root / snapshot_id
    if final.exists():
        # Snapshot with this id already exists — drop the staging copy.
        # The existing snapshot is content-identical by construction.
        for p in staging.iterdir():
            p.unlink()
        staging.rmdir()
        logger.info("Snapshot %s already exists; staging discarded.", snapshot_id)
    else:
        staging.rename(final)

    manifest = SnapshotManifest(
        snapshot_id=snapshot_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        universe_label=universe_label,
        window_start=str(pd.Timestamp(window_start).date()),
        window_end=str(pd.Timestamp(window_end).date()),
        pipeline_version=pipeline_version,
        tickers=tuple(tickers),
        n_tickers_with_prices=n_with_prices,
        n_tickers_with_fundamentals=n_with_fund,
        n_tickers_with_earnings=n_with_earn,
        has_spy=has_spy,
        has_vix=has_vix,
        content_hashes=content_hashes,
        universe_as_of=universe_as_of,
    )
    (final / MANIFEST_FILE).write_text(
        json.dumps(manifest.to_dict(), indent=2),
        encoding="utf-8",
    )
    logger.info("Wrote snapshot %s (%d tickers) at %s", snapshot_id,
                n_with_prices, final)
    return manifest


def load_snapshot(
    snapshot_id: str, root: Path = SNAPSHOT_ROOT,
) -> SnapshotInputs:
    """Reconstitute the engine inputs from a snapshot directory.

    Raises FileNotFoundError if the snapshot doesn't exist. Verifies
    every content hash recorded in the manifest — any byte change
    raises ValueError. That's the immutability contract.
    """
    root = Path(root)
    snap = root / snapshot_id
    if not snap.exists():
        raise FileNotFoundError(f"snapshot not found: {snap}")
    manifest_path = snap / MANIFEST_FILE
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest missing in snapshot: {manifest_path}")
    manifest = SnapshotManifest.from_dict(
        json.loads(manifest_path.read_text(encoding="utf-8")),
    )

    # Verify content hashes — refuse to use a snapshot that's been
    # tampered with after the fact.
    for name, expected in manifest.content_hashes.items():
        actual = _hash_file(snap / name)
        if expected and actual != expected:
            raise ValueError(
                f"snapshot {snapshot_id}: content hash mismatch for {name} "
                f"(expected {expected[:12]}..., got {actual[:12]}...)"
            )

    # ----- prices -----
    price_data: dict[str, pd.DataFrame] = {}
    prices_path = snap / PRICES_FILE
    if prices_path.exists():
        prices_long = pd.read_parquet(prices_path)
        prices_long["date"] = pd.to_datetime(prices_long["date"])
        for ticker, group in prices_long.groupby("ticker"):
            g = group.drop(columns=["ticker"]).set_index("date").sort_index()
            price_data[str(ticker)] = g

    spy_df = None
    if (snap / SPY_FILE).exists():
        s = pd.read_parquet(snap / SPY_FILE)
        s["date"] = pd.to_datetime(s["date"])
        spy_df = s.set_index("date").sort_index()
    vix_df = None
    if (snap / VIX_FILE).exists():
        v = pd.read_parquet(snap / VIX_FILE)
        v["date"] = pd.to_datetime(v["date"])
        vix_df = v.set_index("date").sort_index()

    # ----- fundamentals -----
    fundamentals: dict[str, dict] = {}
    fund_path = snap / FUNDAMENTALS_FILE
    if fund_path.exists():
        fundamentals = json.loads(fund_path.read_text(encoding="utf-8"))

    # ----- earnings -----
    earnings_history: dict[str, pd.DataFrame] = {}
    earn_path = snap / EARNINGS_FILE
    if earn_path.exists():
        earn_long = pd.read_parquet(earn_path)
        earn_long["earnings_date"] = pd.to_datetime(earn_long["earnings_date"])
        for ticker, group in earn_long.groupby("ticker"):
            # Engine consumes a DataFrame indexed by earnings date.
            df = group.drop(columns=["ticker"]).rename(
                columns={"earnings_date": "Earnings Date"},
            ).copy()
            df = df.set_index("Earnings Date").sort_index()
            earnings_history[str(ticker)] = df

    return SnapshotInputs(
        price_data=price_data,
        fundamentals=fundamentals,
        earnings_history=earnings_history,
        spy_df=spy_df,
        vix_df=vix_df,
        manifest=manifest,
    )


def list_snapshots(root: Path = SNAPSHOT_ROOT) -> list[SnapshotManifest]:
    """All known snapshots under root, ordered by created_at."""
    root = Path(root)
    if not root.exists():
        return []
    out: list[SnapshotManifest] = []
    for p in root.iterdir():
        if not p.is_dir():
            continue
        mf = p / MANIFEST_FILE
        if not mf.exists():
            continue
        try:
            m = SnapshotManifest.from_dict(
                json.loads(mf.read_text(encoding="utf-8")),
            )
        except Exception:  # noqa: BLE001
            continue
        out.append(m)
    out.sort(key=lambda m: m.created_at)
    return out
