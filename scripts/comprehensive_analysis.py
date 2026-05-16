"""Generate the comprehensive portfolio analysis report.

Orchestrator:
  1. Load today's composite-factor picks (from data/daily_picks/*.json)
  2. Pull live prices + 1y history for technicals
  3. Load EDGAR PIT fundamentals for the picks
  4. Pull yfinance .info for analyst targets, short interest, beta
  5. Optionally derive expected return from existing backtest trade log
  6. Per-stock analyze
  7. Render full markdown report to disk

Usage
-----

    uv run python -m scripts.comprehensive_analysis \\
        --picks-date 2026-05-16 \\
        --output reports/portfolio_analysis_2026_05_16.md
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("comprehensive_analysis")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--picks-date", default=None,
                   help="YYYY-MM-DD. Defaults to today UTC.")
    p.add_argument("--picks-dir", default="data/daily_picks")
    p.add_argument("--equity", type=float, default=None,
                   help="Override portfolio equity (defaults to Alpaca paper)")
    p.add_argument("--backtest-json", default="data/factors/sweep/comp_d05_r63_2024.json",
                   help="Backtest result JSON to derive per-pick return "
                        "distribution from (uses trades_sample).")
    p.add_argument("--output", required=True,
                   help="Output markdown path.")
    return p.parse_args()


def _load_picks(picks_dir: str, date_str: str | None) -> dict:
    if date_str is None:
        date_str = datetime.now(timezone.utc).date().isoformat()
    path = Path(picks_dir) / f"{date_str}.json"
    if not path.exists():
        raise SystemExit(
            f"No picks file at {path}. Run "
            f"`uv run python -m scripts.daily_factor_picks` first."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _fetch_prices(tickers: list[str]) -> dict[str, pd.DataFrame]:
    from src.config_loader import Config
    from src.data.cache import DataCache
    from src.data.fetcher import DataFetcher

    config = Config()
    cache = DataCache(
        expiry_hours=config.get("data", "cache_expiry_hours", default=24),
        market_hours_expiry_minutes=config.get(
            "data", "market_hours_cache_minutes", default=5,
        ),
    )
    fetcher = DataFetcher(config, cache)
    raw = fetcher.fetch_batch(tickers)
    out: dict[str, pd.DataFrame] = {}
    for t, df in raw.items():
        if df is None or df.empty:
            continue
        d = df.copy()
        if isinstance(d.index, pd.DatetimeIndex) and d.index.tz is not None:
            d.index = d.index.tz_convert("UTC").tz_localize(None)
        out[t] = d
    return out


def _fetch_yf_info(tickers: list[str]) -> dict[str, dict]:
    """Pull yfinance Ticker.info per name. Slow (1-2s each) but rich."""
    import yfinance as yf
    out: dict[str, dict] = {}
    for i, t in enumerate(tickers):
        try:
            info = yf.Ticker(t).info or {}
            out[t] = info
            logger.info("  [%d/%d] %s info: target=%s rec=%s short=%s",
                        i + 1, len(tickers), t,
                        info.get("targetMeanPrice"),
                        info.get("recommendationKey"),
                        info.get("shortPercentOfFloat"))
        except Exception as e:  # noqa: BLE001
            logger.warning("yfinance .info failed for %s: %s", t, e)
            out[t] = {}
    return out


def _fetch_earnings_dates(tickers: list[str]) -> dict[str, pd.Timestamp]:
    """Next earnings date per ticker, as_of "now". Best-effort.

    Returns the earliest future earnings event from yfinance's
    `get_earnings_dates` (which is upcoming + recent). Empty dict if
    the call fails. Drop tz before returning.
    """
    import yfinance as yf
    out: dict[str, pd.Timestamp] = {}
    today = pd.Timestamp.utcnow().tz_localize(None)
    for t in tickers:
        try:
            df = yf.Ticker(t).get_earnings_dates(limit=4)
            if df is None or df.empty:
                continue
            idx = df.index
            if isinstance(idx, pd.DatetimeIndex) and idx.tz is not None:
                idx = idx.tz_convert("UTC").tz_localize(None)
            future = sorted([d for d in idx if d >= today])
            if future:
                out[t] = future[0]
        except Exception:  # noqa: BLE001
            continue
    return out


def _load_fundamentals(tickers: list[str]):
    from src.db.repositories.fundamentals import PostgresFundamentalsRepository
    from src.db.session import get_sessionmaker, run_with_dispose
    from src.scoring.fundamentals_pit_loader import FundamentalsPITLoader

    async def _go():
        async with get_sessionmaker()() as session:
            repo = PostgresFundamentalsRepository(session)
            return await FundamentalsPITLoader.from_repository(repo, tickers)

    return run_with_dispose(_go())


def _load_insider_transactions(tickers: list[str], days: int = 90) -> dict[str, list[dict]]:
    """Pull last N days of Form 4 transactions for the ticker list.

    Returns {ticker: [tx_dict, ...]}; each dict has the columns the
    comprehensive analyzer expects (transaction_code, value_usd,
    transaction_date, filing_date).
    """
    from datetime import date, timedelta
    from sqlalchemy import text
    from src.db.session import get_sessionmaker, run_with_dispose

    async def _go():
        cutoff = date.today() - timedelta(days=days)
        async with get_sessionmaker()() as session:
            res = await session.execute(
                text(
                    "SELECT ticker, transaction_code, value_usd, "
                    "transaction_date, filing_date "
                    "FROM insider_transactions "
                    "WHERE ticker = ANY(:tks) "
                    "AND filing_date >= :cutoff"
                ),
                {"tks": [t.upper() for t in tickers], "cutoff": cutoff},
            )
            return res.mappings().all()

    rows = run_with_dispose(_go())
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["ticker"], []).append(dict(r))
    return out


def _resolve_equity(override: float | None) -> float:
    if override is not None:
        return float(override)
    try:
        from src.execution.alpaca import AlpacaClient
        from src.execution.safety_gates import TradingSafetyGate
        from src.config_loader import Config
        client = AlpacaClient(safety_gate=TradingSafetyGate.from_config(Config()))
        acct = client.get_account()
        return float(acct.get("equity", 10_000.0) or 10_000.0)
    except Exception as e:  # noqa: BLE001
        logger.warning("Alpaca equity lookup failed (%s); defaulting to $10,000", e)
        return 10_000.0


def _load_backtest_trades(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        logger.warning("backtest JSON not found at %s; "
                       "using literature-prior returns", path)
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    return data.get("trades_sample", [])


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = _parse_args()

    payload = _load_picks(args.picks_dir, args.picks_date)
    picks = payload["picks"]
    if not picks:
        raise SystemExit("Picks file empty.")
    as_of_str = payload["as_of"]
    as_of_ts = pd.Timestamp(as_of_str)
    pick_tickers = [p["ticker"] for p in picks]
    logger.info("Picks loaded: %d names for %s", len(picks), as_of_str)

    # Equity for sizing.
    equity = _resolve_equity(args.equity)
    logger.info("Portfolio equity: $%.2f", equity)

    # Live prices (~24 tickers). 5y of history so 200d SMA + ATR work cleanly.
    logger.info("Fetching prices for %d picks...", len(pick_tickers))
    prices = _fetch_prices(pick_tickers)
    logger.info("Got prices for %d/%d", len(prices), len(pick_tickers))

    # yfinance .info — slow loop, but only 24 calls
    logger.info("Fetching yfinance info for %d picks (analyst tgt + short + beta)...",
                len(pick_tickers))
    yf_info = _fetch_yf_info(pick_tickers)

    # Next earnings dates
    logger.info("Fetching earnings calendars...")
    earnings = _fetch_earnings_dates(pick_tickers)
    today = pd.Timestamp.utcnow().tz_localize(None)
    days_to_earn = {
        t: max(0, (d - today).days)
        for t, d in earnings.items()
    }

    # EDGAR PIT fundamentals — we already have these cached for all S&P 500.
    logger.info("Loading EDGAR PIT fundamentals for picks...")
    loader = _load_fundamentals(pick_tickers)

    # Insider transactions (Form 4) — last 90 days.
    logger.info("Loading insider transactions (last 90d) for picks...")
    insider_txs = _load_insider_transactions(pick_tickers, days=90)
    logger.info("Insider coverage: %d/%d tickers with ≥1 transaction",
                sum(1 for v in insider_txs.values() if v),
                len(pick_tickers))

    # Expected returns from backtest trade log
    trades = _load_backtest_trades(args.backtest_json)
    from src.analysis.comprehensive import (
        analyze_ticker, estimate_per_pick_returns,
    )
    exp_returns = estimate_per_pick_returns(trades)
    logger.info(
        "Per-pick return estimates (from %d trade events): "
        "median=%.1f%%, 75th=%.1f%%, 25th=%.1f%%",
        len(trades), *exp_returns,
    )

    # Per-stock analyze
    analyses = []
    for p_dict in picks:
        t = p_dict["ticker"]
        if t not in prices:
            logger.warning("Skipping %s: no price data", t)
            continue
        a = analyze_ticker(
            ticker=t,
            prices=prices[t],
            loader=loader,
            as_of=as_of_ts,
            composite_rank=int(p_dict["rank"]),
            composite_z=float(p_dict["z_score"]),
            mom_rank=int(p_dict["mom_rank"]) if pd.notna(p_dict.get("mom_rank")) else None,
            qual_rank=int(p_dict["qual_rank"]) if pd.notna(p_dict.get("qual_rank")) else None,
            val_rank=int(p_dict["val_rank"]) if pd.notna(p_dict.get("val_rank")) else None,
            mom_raw=None,  # not in picks JSON; could re-pull but cost > value
            equity_usd=equity,
            n_positions=len(picks),
            expected_returns=exp_returns,
            days_to_next_earnings=days_to_earn.get(t),
            yf_info=yf_info.get(t, {}),
            insider_txs=insider_txs.get(t, []),
        )
        analyses.append(a)

    # Correlation structure (60d daily returns)
    from src.analysis.comprehensive import compute_correlation_matrix
    _, corr_summary = compute_correlation_matrix(
        prices, [a.ticker for a in analyses], as_of_ts, window_days=60,
    )
    if corr_summary.get("mean_off_diagonal") is not None:
        logger.info(
            "Correlation: mean=%.3f, effective_n=%.1f",
            corr_summary["mean_off_diagonal"], corr_summary["effective_n"],
        )

    logger.info("Rendering report for %d analyses...", len(analyses))
    from src.analysis.comprehensive_render import render_full_report
    md = render_full_report(analyses, equity, as_of_str, corr_summary)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")
    logger.info("Wrote %s (%d KB)", out_path, len(md) // 1024)

    # Also dump a parallel JSON for programmatic consumption.
    json_path = out_path.with_suffix(".json")
    payload_out = {
        "as_of": as_of_str,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "strategy": payload.get("strategy"),
        "equity_usd": equity,
        "n_positions": len(analyses),
        "expected_per_pick_pct": {
            "median": exp_returns[0],
            "p75": exp_returns[1],
            "p25": exp_returns[2],
        },
        "picks": [
            {
                "rank": a.portfolio_rank,
                "ticker": a.ticker,
                "composite_z": a.composite_z,
                "entry_price": a.plan.entry_price,
                "stop_loss": a.plan.stop_loss_price,
                "target": a.plan.target_price,
                "time_exit_date": a.plan.time_exit_date,
                "target_shares": a.plan.target_shares,
                "position_size_usd": a.plan.position_size_usd,
                "expected_return_pct": a.expected_return_pct,
                "rationale": a.rationale,
                "analyst_target": a.analyst_target,
                "sector": a.fundamentals.sector,
                "days_to_earnings": a.risk_flags.days_to_next_earnings,
            }
            for a in analyses
        ],
    }
    json_path.write_text(
        json.dumps(payload_out, indent=2, default=str),
        encoding="utf-8",
    )
    logger.info("Wrote %s", json_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
