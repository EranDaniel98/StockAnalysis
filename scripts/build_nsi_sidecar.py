"""Build a per-snapshot net-share-issuance sidecar (Postgres-free).

Reuses the cached SEC companyfacts in ``data/edgar_cache/`` (shared with the
accruals sidecar), extracts PIT trailing-1y net-share-issuance via
``src.factors.net_share_issuance``, and writes
``data/snapshots/<id>/nsi_pit.json``.

    uv run python -m scripts.build_nsi_sidecar --snapshot-id <id>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from src.factors.net_share_issuance import NetShareIssuancePITLoader, extract_net_share_issuance
from src.market_data.edgar.client import EDGARClient, get_ticker_to_cik

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
log = logging.getLogger("nsi_sidecar")

CACHE = Path("data/edgar_cache")
SNAP_ROOT = Path("data/snapshots")


def _resolve_cik(ticker: str, t2c: dict[str, int]) -> int | None:
    for cand in (ticker, ticker.replace(".", "-"), ticker.replace("-", "."), ticker.split(".")[0]):
        cik = t2c.get(cand.upper())
        if cik is not None:
            return cik
    return None


async def _facts_cached(client: EDGARClient, cik: int) -> dict | None:
    path = CACHE / f"CIK{int(cik):010d}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        facts = await client.fetch_company_facts(cik)
    except Exception as exc:  # noqa: BLE001 — a missing/erroring CIK just skips
        log.warning("companyfacts fetch failed for CIK %s: %s", cik, exc)
        return None
    path.write_text(json.dumps(facts), encoding="utf-8")
    return facts


async def main() -> int:
    ap = argparse.ArgumentParser(description="Build net-share-issuance sidecar for a snapshot")
    ap.add_argument("--snapshot-id", required=True)
    args = ap.parse_args()

    from dotenv import load_dotenv

    load_dotenv()

    snap_dir = SNAP_ROOT / args.snapshot_id
    manifest = json.loads((snap_dir / "manifest.json").read_text(encoding="utf-8"))
    tickers: list[str] = manifest["tickers"]
    CACHE.mkdir(parents=True, exist_ok=True)

    client = EDGARClient()
    try:
        t2c_path = CACHE / "ticker_cik.json"
        if t2c_path.exists():
            t2c = {k: int(v) for k, v in json.loads(t2c_path.read_text(encoding="utf-8")).items()}
        else:
            t2c = await get_ticker_to_cik(client)
            t2c_path.write_text(json.dumps(t2c), encoding="utf-8")

        records = []
        covered = 0
        missing_cik: list[str] = []
        no_nsi: list[str] = []
        for i, t in enumerate(tickers, 1):
            cik = _resolve_cik(t, t2c)
            if cik is None:
                missing_cik.append(t)
                continue
            facts = await _facts_cached(client, cik)
            if facts is None:
                missing_cik.append(t)
                continue
            recs = extract_net_share_issuance(t, facts)
            if recs:
                records.extend(recs)
                covered += 1
            else:
                no_nsi.append(t)
            if i % 50 == 0:
                print(f"  [{i}/{len(tickers)}] covered={covered}", file=sys.stderr)

        loader = NetShareIssuancePITLoader(records)
        out = snap_dir / "nsi_pit.json"
        loader.to_json(out)
        print(
            f"Wrote {out}\n"
            f"  universe={len(tickers)} covered={covered} "
            f"no_nsi={len(no_nsi)} missing_cik={len(missing_cik)} records={len(records)}"
        )
    finally:
        await client.aclose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
