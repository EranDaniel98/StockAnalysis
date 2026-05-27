"""Build a deterministic backtest snapshot from Polygon (Phase C of the
yfinance->Polygon migration).

``src.storage.snapshot.write_snapshot`` had no production caller — backtests
consumed snapshots built ad-hoc. This is that caller. It freezes prices for the
PIT S&P 500 universe (+ SPY from Polygon, + VIX from yfinance) over
[start - lookback, end] into a content-addressed snapshot.

Why this is the determinism fix: the snapshot id is sha256 over the ticker list,
window, pipeline version, AND the parquet content hashes. Polygon returns
bit-identical bars for the same query, so **building twice yields the same
snapshot_id** — whereas yfinance's drifting dividend adjustment produced a new
id (and a new Sharpe) every run (see memory project_yfinance_nondeterminism).
EDGAR PIT fundamentals are frozen separately into <snap>/fundamentals_pit.json
by run_factor_backtest on first use.

Usage:
    uv run python -m scripts.build_snapshot \\
        --as-of 2024-01-02 --start 2024-01-02 --end 2026-01-02 --label sp500_pit
    # ad-hoc / test universe:
    uv run python -m scripts.build_snapshot --tickers AAPL,MSFT,NVDA \\
        --start 2024-06-01 --end 2025-12-01
"""

from __future__ import annotations

import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from src.config_loader import Config
from src.market_data.polygon import PolygonClient, PolygonError, bars_to_frame
from src.storage.snapshot import write_snapshot

logger = logging.getLogger(__name__)


def fetch_equities(client: PolygonClient, tickers: list[str], start, end,
                   *, workers: int = 8) -> dict[str, pd.DataFrame]:
    """Adjusted daily OHLCV per ticker over [start, end] from Polygon."""
    out: dict[str, pd.DataFrame] = {}

    def _one(t: str):
        try:
            bars = client.aggregates(t, start, end, timespan="day", multiplier=1, adjusted=True)
        except PolygonError as e:
            logger.warning("polygon fetch failed for %s: %s", t, e)
            return None
        df = bars_to_frame(bars, daily=True)
        return df if not df.empty else None

    with ThreadPoolExecutor(max_workers=min(workers, max(1, len(tickers)))) as ex:
        futs = {ex.submit(_one, t): t for t in tickers}
        for fut in as_completed(futs):
            t = futs[fut]
            try:
                df = fut.result()
            except Exception as e:  # noqa: BLE001
                logger.error("worker error for %s: %s", t, e)
                df = None
            if df is not None:
                out[t] = df
    return out


def fetch_vix(start, end) -> pd.DataFrame | None:
    """VIX from yfinance (Polygon I:VIX is Indices-tier, not on $29 Stocks)."""
    import yfinance as yf

    try:
        h = yf.Ticker("^VIX").history(start=pd.Timestamp(start).date().isoformat(),
                                      end=pd.Timestamp(end).date().isoformat())
    except Exception as e:  # noqa: BLE001
        logger.warning("VIX fetch failed: %s", e)
        return None
    if h is None or h.empty:
        return None
    h = h.copy()
    h.columns = [str(c).strip() for c in h.columns]
    if isinstance(h.index, pd.DatetimeIndex) and h.index.tz is not None:
        h.index = h.index.tz_convert("UTC").tz_localize(None)
    keep = [c for c in ("Open", "High", "Low", "Close", "Volume") if c in h.columns]
    return h[keep] if keep else None


def main() -> int:
    ap = argparse.ArgumentParser(description="Build a deterministic Polygon-sourced backtest snapshot.")
    ap.add_argument("--start", required=True, help="backtest window start (YYYY-MM-DD)")
    ap.add_argument("--end", required=True, help="backtest window end (YYYY-MM-DD)")
    ap.add_argument("--as-of", help="PIT S&P 500 universe date (YYYY-MM-DD); defaults to --start")
    ap.add_argument("--tickers", default="", help="comma list to OVERRIDE the PIT universe (ad-hoc/test)")
    ap.add_argument("--label", default="sp500_pit", help="universe label recorded in the manifest")
    ap.add_argument("--universe", default="sp500_pit", choices=["sp500_pit", "russell_1000"],
                    help="which universe to freeze (ignored when --tickers is given)")
    ap.add_argument("--lookback-days", type=int, default=400,
                    help="extra calendar history before --start so the 252-trading-day momentum lookback warms up")
    ap.add_argument("--pipeline-version", default="polygon_v1")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    win_start, win_end = pd.Timestamp(args.start), pd.Timestamp(args.end)
    as_of = pd.Timestamp(args.as_of) if args.as_of else win_start
    fetch_start = win_start - pd.Timedelta(days=args.lookback_days)

    # $29 Starter = ~5yr history. Warn (don't fail) if the lookback reaches past it.
    earliest = pd.Timestamp.today().normalize() - pd.DateOffset(years=5)
    if fetch_start < earliest:
        logger.warning("fetch_start %s precedes the ~5yr Polygon Starter horizon (%s); "
                       "momentum lookback will be truncated. Pre-2021 windows need the $79 (10yr) tier.",
                       fetch_start.date(), earliest.date())

    cfg = Config()
    if args.tickers.strip():
        universe = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        label = args.label if args.label != "sp500_pit" else "adhoc"
    elif args.universe == "russell_1000":
        universe = [t.upper() for t in cfg.get_russell_1000_tickers()]
        if not universe:
            raise SystemExit("Russell 1000 list empty — run "
                             "`uv run python -m scripts.fetch_russell_1000` first.")
        label = "russell_1000"
        logger.warning(
            "Russell 1000 list is STATIC CURRENT membership (not point-in-time). "
            "Backtests over historical windows are SURVIVORSHIP-BIASED — you hold "
            "today's index members, not the set that existed at each rebalance, so "
            "momentum buys hindsight winners and never holds the names that dropped "
            "out. A 2024-26 run showed +73%% alpha that was almost entirely this bias. "
            "Do NOT trust Russell backtests until PIT membership exists.")
    else:
        # Audit #16: freeze the FULL window membership, not a single as-of set.
        # all-members-during-[start,end] = members at start ∪ members at end ∪
        # every name added/removed inside the window. This kills the
        # eligibility freeze (additions missing, removals over-held); the
        # backtest re-resolves as_of(d) per rebalance from the frozen oracle.
        from src.universe import load_default_sp500

        membership = load_default_sp500()
        ch = membership.changes
        win_ch = ch[(ch["date"] >= win_start) & (ch["date"] <= win_end)]
        window_members = (
            set(membership.as_of(win_start))
            | set(membership.as_of(win_end))
            | set(win_ch["ticker"])
        )
        universe = sorted(window_members)
        if not universe:
            raise SystemExit("PIT S&P 500 universe is empty — run "
                             "`uv run python -m scripts.fetch_sp500_membership` first, or pass --tickers.")
        label = args.label
        logger.info("sp500_pit window membership: %d names over [%s..%s] "
                    "(%d as-of-start + additions/removals)",
                    len(universe), win_start.date(), win_end.date(),
                    len(membership.as_of(win_start)))

    client = PolygonClient()
    logger.info("fetching %d tickers + SPY from Polygon over [%s .. %s]",
                len(universe), fetch_start.date(), win_end.date())
    prices = fetch_equities(client, universe, fetch_start, win_end, workers=args.workers)
    spy = fetch_equities(client, ["SPY"], fetch_start, win_end).get("SPY")
    vix = fetch_vix(fetch_start, win_end)
    if spy is None:
        raise SystemExit("no SPY data — cannot build a usable snapshot (trading-day calendar comes from SPY)")

    # Freeze earnings (surprise %, reported EPS) so PEAD backtests reproduce off
    # the snapshot instead of the live cache. Cache-only (large max-age) — never
    # live-fetch ~500 tickers at build time.
    from pathlib import Path as _Path

    from src.factors.earnings_cache import load_earnings_histories
    earnings = load_earnings_histories(universe, _Path("data/earnings_history"),
                                       max_age_hours=87_600.0)
    logger.info("froze earnings for %d/%d tickers (PEAD)", len(earnings), len(universe))

    manifest = write_snapshot(
        price_data=prices,
        fundamentals={},                 # EDGAR PIT is frozen separately by run_factor_backtest
        earnings_history=earnings,       # surprise %/reported EPS frozen for reproducible PEAD
        spy_df=spy,
        vix_df=vix,
        universe_label=label,
        window_start=win_start,
        window_end=win_end,
        pipeline_version=args.pipeline_version,
        universe_as_of=str(as_of.date()),
    )

    # Audit #16: freeze the PIT membership oracle into the snapshot dir so the
    # backtest can re-resolve as_of(d) per rebalance reproducibly (off frozen
    # data, never the live CSV). Only meaningful for sp500_pit.
    if label == "sp500_pit":
        import shutil
        from pathlib import Path

        from src.universe.sp500_pit import DEFAULT_CHANGES_PATH, DEFAULT_CURRENT_PATH

        snap_dir = Path("data/snapshots") / manifest.snapshot_id
        shutil.copy(DEFAULT_CURRENT_PATH, snap_dir / "sp500_current.csv")
        shutil.copy(DEFAULT_CHANGES_PATH, snap_dir / "sp500_changes.csv")
        logger.info("froze PIT membership (current + changes) into %s", snap_dir)

    print(f"\nsnapshot_id: {manifest.snapshot_id}")
    print(f"  prices: {manifest.n_tickers_with_prices}/{len(universe)} tickers  "
          f"SPY={manifest.has_spy} VIX={manifest.has_vix}")
    print(f"  window: {manifest.window_start} .. {manifest.window_end}  (universe as-of {manifest.universe_as_of})")
    print(f"\nnext: uv run python -m scripts.run_factor_backtest "
          f"--snapshot-id {manifest.snapshot_id} --output reports/<name>.json")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    sys.exit(main())
