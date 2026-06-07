"""Binance public-API map + raw puller for a funding-carry backtest (BACKTEST ONLY, no keys).

Standalone. Caches raw pulls under data/crypto_cache/ so re-runs are cheap.

Endpoints (all public, no auth):
  - Funding history : GET https://fapi.binance.com/fapi/v1/fundingRate
  - Perp daily kline: GET https://fapi.binance.com/fapi/v1/klines   (interval=1d)
  - Spot daily kline: GET https://api.binance.com/api/v3/klines      (interval=1d)

Run:
  uv run python scripts/binance_funding_carry_map.py            # pull all syms, 3y+ funding + klines
  uv run python scripts/binance_funding_carry_map.py --probe    # just listing-date probe (no big pulls)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import time
from pathlib import Path

import httpx

FAPI = "https://fapi.binance.com"
SAPI = "https://api.binance.com"
CACHE = Path(__file__).resolve().parents[1] / "data" / "crypto_cache"
CACHE.mkdir(parents=True, exist_ok=True)

# Liquid USDT-perp set: BTC, ETH + 8 alts, all with spot+perp and perp listed 2020 (<=2021).
# Funding-history inception ~= perp listing; spot is older for all of these.
LIQUID_SET = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT",
    "SOLUSDT", "DOGEUSDT", "LTCUSDT", "LINKUSDT", "DOTUSDT",
]

# Binance USDT-M perp taker/maker fee schedule (VIP0, public docs, no BNB discount):
#   maker 0.0200% (2.0 bps), taker 0.0500% (5.0 bps).  With BNB-pay discount ~10% off.
# Funding is paid/received separately every 8h and is NOT a trading fee.
FEES_BPS = {"maker": 2.0, "taker": 5.0, "taker_bnb_disc": 4.5}


def _get(url: str, params: dict, retries: int = 4) -> list:
    last = None
    for i in range(retries):
        try:
            r = httpx.get(url, params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # transient network / 429
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"GET failed {url} {params}: {last}")


def utc_date(ms: int) -> dt.date:
    return dt.datetime.fromtimestamp(ms / 1000, dt.UTC).date()


def funding_history(symbol: str, start_ms: int, end_ms: int | None = None) -> list[dict]:
    """Page forward through funding history. limit=1000 (~333 days @ 8h cadence).

    Pagination: walk startTime forward to (last fundingTime + 1) until < 1000 rows
    or past end_ms. The endpoint ignores startTime=0 (returns latest), so a real
    epoch like the perp listing must be supplied.
    """
    out: list[dict] = []
    cur = start_ms
    while True:
        params = {"symbol": symbol, "startTime": cur, "limit": 1000}
        if end_ms:
            params["endTime"] = end_ms
        batch = _get(FAPI + "/fapi/v1/fundingRate", params)
        if not batch:
            break
        out.extend(batch)
        if len(batch) < 1000:
            break
        cur = batch[-1]["fundingTime"] + 1
        if end_ms and cur >= end_ms:
            break
        time.sleep(0.25)
    # dedup on fundingTime
    seen, dedup = set(), []
    for row in out:
        t = row["fundingTime"]
        if t not in seen:
            seen.add(t)
            dedup.append(row)
    return dedup


def daily_klines(symbol: str, perp: bool, start_ms: int, end_ms: int | None = None) -> list[list]:
    base, path = (FAPI, "/fapi/v1/klines") if perp else (SAPI, "/api/v3/klines")
    out: list[list] = []
    cur = start_ms
    while True:
        params = {"symbol": symbol, "interval": "1d", "startTime": cur, "limit": 1000}
        if end_ms:
            params["endTime"] = end_ms
        batch = _get(base + path, params)
        if not batch:
            break
        out.extend(batch)
        if len(batch) < 1000:
            break
        cur = batch[-1][0] + 1
        if end_ms and cur >= end_ms:
            break
        time.sleep(0.2)
    return out


def first_perp_listing(symbol: str) -> dt.date | None:
    j = _get(FAPI + "/fapi/v1/klines", {"symbol": symbol, "interval": "1d", "startTime": 0, "limit": 1})
    return utc_date(j[0][0]) if j else None


def probe() -> dict:
    rows = {}
    for s in LIQUID_SET:
        perp = first_perp_listing(s)
        spot_j = _get(SAPI + "/api/v3/klines", {"symbol": s, "interval": "1d", "startTime": 0, "limit": 1})
        spot = utc_date(spot_j[0][0]) if spot_j else None
        rows[s] = {"perp_listed": str(perp), "spot_listed": str(spot)}
        print(f"{s:10} perp={perp} spot={spot}")
    (CACHE / "listing_dates.json").write_text(json.dumps(rows, indent=2))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true", help="only print listing dates")
    ap.add_argument("--years", type=float, default=3.0)
    args = ap.parse_args()

    if args.probe:
        probe()
        return

    end_ms = int(time.time() * 1000)
    start_ms = end_ms - int(args.years * 365.25 * 86400 * 1000)
    for s in LIQUID_SET:
        fr = funding_history(s, start_ms, end_ms)
        pk = daily_klines(s, True, start_ms, end_ms)
        sk = daily_klines(s, False, start_ms, end_ms)
        (CACHE / f"funding_{s}.json").write_text(json.dumps(fr))
        (CACHE / f"perp_kline_{s}.json").write_text(json.dumps(pk))
        (CACHE / f"spot_kline_{s}.json").write_text(json.dumps(sk))
        print(f"{s:10} funding={len(fr)} perp_klines={len(pk)} spot_klines={len(sk)}")


if __name__ == "__main__":
    main()
