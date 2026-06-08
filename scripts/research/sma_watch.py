"""SMA trend-line watch — is a ticker holding or breaking its moving average?

Built for the energy-book oil-trend question: the producer/services names in
the momentum-value book (APA/DVN/HAL/BKR) ride the oil trend, and USO/XLE
sitting ON their 50-day SMA is the line that decides "pullback within an
uptrend" vs "trend break". This reports each watched ticker's position vs its
SMA and a plain status. Display/alert only — never a trade trigger.

Config (config/settings.yaml::sma_watch): sma_window, break_threshold_pct,
tickers. Nothing hardcoded.

    uv run python -m scripts.research.sma_watch
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

logger = logging.getLogger("sma_watch")

OUTPUT = Path("reports") / "sma_watch_latest.json"


def _cfg() -> dict:
    from src.config_loader import Config  # loads .env + the yamls
    return Config().get("sma_watch", default=None) or {}


def _daily_closes(ticker: str, lookback_days: int) -> pd.Series | None:
    from src.market_data.polygon import PolygonClient, bars_to_frame
    end = pd.Timestamp.now(tz=timezone.utc).tz_localize(None).normalize()
    start = (end - pd.Timedelta(days=lookback_days)).date().isoformat()
    df = bars_to_frame(
        PolygonClient().aggregates(ticker, start, end.date().isoformat(),
                                   timespan="day", multiplier=1, adjusted=True),
        daily=True,
    )
    return None if df is None or df.empty else df["Close"]


def _status(last: float, sma: float, thr_pct: float) -> str:
    """ABOVE = holding the trend; BELOW = break warning; AT_LINE = inflection."""
    band = sma * thr_pct / 100.0
    if last > sma + band:
        return "ABOVE"
    if last < sma - band:
        return "BELOW"
    return "AT_LINE"


def build() -> dict:
    cfg = _cfg()
    window = int(cfg.get("sma_window", 50))
    thr = float(cfg.get("break_threshold_pct", 1.0))
    tickers = list(cfg.get("tickers", ["USO", "XLE"]))
    # Fetch ~3x the SMA window in calendar days so we always have `window` rows.
    lookback_days = window * 5 + 30

    rows: list[dict] = []
    for t in tickers:
        closes = _daily_closes(t, lookback_days)
        if closes is None or len(closes) < window:
            rows.append({"ticker": t, "status": "NO_DATA"})
            logger.warning("%s: insufficient data for a %d-SMA", t, window)
            continue
        last = float(closes.iloc[-1])
        sma = float(closes.iloc[-window:].mean())
        rows.append({
            "ticker": t,
            "last": round(last, 2),
            "sma": round(sma, 2),
            "pct_vs_sma": round((last / sma - 1.0) * 100.0, 2),
            "status": _status(last, sma, thr),
        })

    return {
        "sma_window": window,
        "break_threshold_pct": thr,
        "watch": rows,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    payload = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    w = payload["sma_window"]
    logger.info("%d-SMA watch (%.1f%% band):", w, payload["break_threshold_pct"])
    for r in payload["watch"]:
        if r["status"] == "NO_DATA":
            logger.info("  %-5s  no data", r["ticker"])
            continue
        flag = {"ABOVE": "holding", "AT_LINE": "AT THE LINE",
                "BELOW": "BROKE BELOW"}[r["status"]]
        logger.info("  %-5s  last %.2f vs %d-SMA %.2f  (%+.2f%%)  -> %s",
                    r["ticker"], r["last"], w, r["sma"], r["pct_vs_sma"], flag)
    logger.info("wrote %s", OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
