"""Stage -1 builder for the pre-registered "Lazy Prices" (CMN 2020) study.

Mechanical (non-LLM) year-over-year item-level textual-change signal on PIT
S&P 500 10-K / 10-Q filings. For every ticker in a snapshot's frozen PIT
membership it:

  1. ticker -> CIK (data/edgar_cache/ticker_cik.json)
  2. loads EDGAR submissions metadata (cached under
     data/edgar_cache/submissions/, paged-file-merged so prolific filers reach
     back >1yr before window_start)
  3. keeps 10-K / 10-Q (exact form, no amendments) accepted in
     [window_start - 420d, window_end]
  4. fetches each primary doc (cached IMMUTABLY under
     data/edgar_cache/filings_text/<accession>.html)
  5. extracts item-level text (10-K: Item 1A + Item 7/7A; 10-Q: Part II Item 1A
     + Part I Item 2) after HTML strip
  6. cosine similarity of TF 1-2gram vectors vs the same-form filing of the same
     CIK ~1yr earlier (300-430d, nearest 365)
  7. writes data/snapshots/<id>/filing_delta_signal.json (OUTSIDE the content
     hash) + a Stage-0 21-day-grid coverage report.

PIT: every similarity is attributed to its filing's acceptanceDateTime (the SEC
accept timestamp), NOT filingDate. No lookahead. No LLM, no price input.

    uv run python -m scripts.research.build_filing_delta_sidecar \
        --snapshot-id fe045eff04a15142 --limit 12
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sklearn.feature_extraction.text import CountVectorizer

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
log = logging.getLogger("filing_delta")

CACHE = Path("data/edgar_cache")
SUBMISSIONS_CACHE = CACHE / "submissions"
FILINGS_TEXT_CACHE = CACHE / "filings_text"
SNAP_ROOT = Path("data/snapshots")

# Comparator search band (days) and ideal lag (CMN compares to ~1yr-prior same form).
COMP_MIN_DAYS = 300
COMP_MAX_DAYS = 430
COMP_IDEAL_DAYS = 365

# Pre-window history the comparator needs (~1yr) plus slack.
HISTORY_PAD_DAYS = 420
# A filing scored at the pad edge needs its own ~1yr-earlier comparator, so
# comparator-eligible collection extends one comparator-band further back.
COMPARATOR_PAD_DAYS = 430
# If recent[] earliest 10-K/10-Q is later than (window_start - this), page back.
PAGE_BACK_THRESHOLD_DAYS = 400

# Stage-0 coverage grid + trailing window.
COVERAGE_GRID_DAYS = 21
COVERAGE_TRAILING_DAYS = 380

# A located item span shorter than this is treated as a table-of-contents
# false positive (the real section body is long).
MIN_ITEM_CHARS = 2000


def _strip_html(t: str) -> str:
    """Clone of scripts/build_filing_signal.py::_strip_html."""
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"&#?\w+;", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _resolve_cik(ticker: str, t2c: dict[str, int]) -> int | None:
    for cand in (ticker, ticker.replace(".", "-"), ticker.replace("-", "."), ticker.split(".")[0]):
        cik = t2c.get(cand.upper())
        if cik is not None:
            return cik
    return None


# --- Item-boundary extraction ------------------------------------------------
#
# Boundaries are matched on the HTML-stripped text. Robust to "Item 1A.",
# "ITEM 1A —", "Item 1A: Risk Factors". We take the LAST/longest qualifying span
# to dodge the table-of-contents (TOC) reference, which is short.

# Matches the START of an item header, e.g. "item 1a", "item 7a", "item 2".
def _item_start_re(num: str) -> re.Pattern[str]:
    # num like "1A", "7", "7A", "2" — allow optional trailing letter already in num.
    return re.compile(rf"\bitem\s+{re.escape(num.lower())}\b[\.\:\—\-\s]", re.IGNORECASE)


def _next_item_re(after_nums: list[str]) -> re.Pattern[str]:
    alts = "|".join(re.escape(n.lower()) for n in after_nums)
    return re.compile(rf"\bitem\s+(?:{alts})\b", re.IGNORECASE)


def _extract_span(text: str, start_num: str, end_nums: list[str]) -> str | None:
    """Longest text span from `Item <start_num>` up to the next `Item <end_nums>`.

    Returns the longest qualifying span (>= MIN_ITEM_CHARS) so the short TOC
    reference is skipped in favour of the real section body. None if no span
    reaches the minimum length.
    """
    low = text.lower()
    start_re = _item_start_re(start_num)
    end_re = _next_item_re(end_nums)
    best = ""
    for m in start_re.finditer(low):
        s = m.start()
        nxt = end_re.search(low, m.end())
        e = nxt.start() if nxt else len(text)
        span = text[s:e]
        if len(span) > len(best):
            best = span
    return best if len(best) >= MIN_ITEM_CHARS else None


def _extract_items(text: str, form: str) -> dict[str, str]:
    """Per-item stripped text for the pre-registered items.

    10-K : Item 1A (Risk Factors) + Item 7/7A (MD&A + market risk)
    10-Q : Part II Item 1A (Risk Factors) + Part I Item 2 (MD&A)

    The same `Item N` regexes work for both forms — Part I/II only disambiguate
    when the same item number repeats, which for our chosen items it does not
    within a single document (10-Q Item 2 = MD&A in Part I; 10-Q Item 1A in
    Part II — distinct numbers). We take the longest span per number.
    """
    out: dict[str, str] = {}
    if form == "10-K":
        ra = _extract_span(text, "1A", ["1B", "1C", "2"])
        mda = _extract_span(text, "7", ["7A", "8"])
        if ra:
            out["1A"] = ra
        if mda:
            out["7"] = mda
    else:  # 10-Q
        ra = _extract_span(text, "1A", ["2", "3", "4", "5", "6"])
        mda = _extract_span(text, "2", ["3", "4"])
        if ra:
            out["1A"] = ra
        if mda:
            out["2"] = mda
    return out


def _cosine_tf(a: str, b: str) -> float:
    """Cosine similarity of TF (1-2 gram, lowercased, english-stopword-stripped)
    count vectors. Deterministic. Returns 0.0 if either side has no usable terms."""
    vec = CountVectorizer(ngram_range=(1, 2), stop_words="english", lowercase=True)
    try:
        m = vec.fit_transform([a, b])
    except ValueError:
        return 0.0  # empty vocabulary
    v = m.toarray().astype(np.float64)
    na = np.linalg.norm(v[0])
    nb = np.linalg.norm(v[1])
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(v[0], v[1]) / (na * nb))


# --- Submissions metadata (with paged-file backfill) -------------------------


def _recent_rows(recent: dict) -> list[dict]:
    forms = recent.get("form", [])
    return [
        {
            "accession": recent["accessionNumber"][i],
            "form": forms[i],
            "accepted": recent["acceptanceDateTime"][i],
            "filing_date": recent["filingDate"][i],
            "report_date": recent.get("reportDate", [""] * len(forms))[i],
            "primary_doc": recent.get("primaryDocument", [""] * len(forms))[i],
        }
        for i in range(len(forms))
    ]


def _flat_rows(block: dict) -> list[dict]:
    """Paged submissions files are flat (no `recent` wrapper)."""
    return _recent_rows(block)


async def _fetch_submissions_cached(client, cik: int) -> dict | None:
    SUBMISSIONS_CACHE.mkdir(parents=True, exist_ok=True)
    path = SUBMISSIONS_CACHE / f"CIK{int(cik):010d}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        sub = await client.fetch_submissions(cik)
    except Exception as exc:  # noqa: BLE001
        log.warning("submissions fetch failed for CIK %s: %s", cik, exc)
        return None
    path.write_text(json.dumps(sub), encoding="utf-8")
    return sub


async def _fetch_paged_file_cached(client, name: str) -> dict | None:
    """Older paged submissions file (data.sec.gov/submissions/<name>)."""
    from src.market_data.edgar.client import _get_with_retries

    SUBMISSIONS_CACHE.mkdir(parents=True, exist_ok=True)
    path = SUBMISSIONS_CACHE / name
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    url = f"{client.BASE_DATA}/submissions/{name}"
    try:
        resp = await _get_with_retries(client._client, url, rate_limiter=client._rate)
    except Exception as exc:  # noqa: BLE001
        log.warning("paged submissions fetch failed for %s: %s", name, exc)
        return None
    if resp.status_code != 200:
        log.warning("paged submissions %s returned %s", name, resp.status_code)
        return None
    block = resp.json()
    path.write_text(json.dumps(block), encoding="utf-8")
    return block


async def _all_filing_rows(
    client, cik: int, window_start: pd.Timestamp
) -> list[dict]:
    """All filing rows for a CIK, paging back if `recent` doesn't reach the
    history the comparator needs."""
    sub = await _fetch_submissions_cached(client, cik)
    if sub is None:
        return []
    filings = sub.get("filings", {})
    rows = _recent_rows(filings.get("recent", {}))

    primary_forms = [r for r in rows if r["form"] in ("10-K", "10-Q")]
    need_before = window_start - pd.Timedelta(days=PAGE_BACK_THRESHOLD_DAYS)
    earliest = None
    if primary_forms:
        earliest = min(_parse_ts(r["accepted"]) for r in primary_forms)

    if earliest is None or earliest > need_before:
        for f in filings.get("files", []):
            block = await _fetch_paged_file_cached(client, f["name"])
            if block:
                rows.extend(_flat_rows(block))
    return rows


# --- PIT timestamp parsing ---------------------------------------------------


def _parse_ts(s: str) -> pd.Timestamp:
    """acceptanceDateTime is e.g. '2025-10-31T10:01:26.000Z' (UTC). Parse
    tz-aware then drop tz for naive comparisons against window dates."""
    ts = pd.Timestamp(s)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts


# --- Per-ticker processing ---------------------------------------------------


async def _filing_text(client, cik: int, row: dict) -> str | None:
    """Stripped item-bearing raw text; cached immutably by accession."""
    FILINGS_TEXT_CACHE.mkdir(parents=True, exist_ok=True)
    acc = row["accession"]
    path = FILINGS_TEXT_CACHE / f"{acc}.html"
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    if not row["primary_doc"]:
        return None
    try:
        raw = await client.fetch_filing_text(cik, acc, row["primary_doc"])
    except Exception as exc:  # noqa: BLE001
        log.warning("filing text fetch failed for %s: %s", acc, exc)
        return None
    path.write_text(raw, encoding="utf-8")
    return raw


def _find_comparator(curr: dict, candidates: list[dict]) -> dict | None:
    """Same-form filing accepted 300-430d before `curr`, nearest to 365d."""
    curr_ts = curr["_accepted_ts"]
    best = None
    best_gap = None
    for c in candidates:
        if c["form"] != curr["form"] or c["accession"] == curr["accession"]:
            continue
        lag = (curr_ts - c["_accepted_ts"]).days
        if COMP_MIN_DAYS <= lag <= COMP_MAX_DAYS:
            gap = abs(lag - COMP_IDEAL_DAYS)
            if best_gap is None or gap < best_gap:
                best, best_gap = c, gap
    return best


async def _process_ticker(
    client,
    ticker: str,
    cik: int,
    window_start: pd.Timestamp,
    window_end: pd.Timestamp,
) -> tuple[list[dict], int, int]:
    """Returns (records, n_filings_kept, n_text_cache_hits)."""
    rows = await _all_filing_rows(client, cik, window_start)
    lo = window_start - pd.Timedelta(days=HISTORY_PAD_DAYS + COMPARATOR_PAD_DAYS)
    score_lo = window_start - pd.Timedelta(days=HISTORY_PAD_DAYS)

    kept: list[dict] = []
    seen: set[str] = set()
    for r in rows:
        if r["form"] not in ("10-K", "10-Q"):
            continue  # exact match -> excludes 10-K/A, 10-Q/A
        if r["accession"] in seen:
            continue
        ts = _parse_ts(r["accepted"])
        if not (lo <= ts <= window_end):
            continue
        r["_accepted_ts"] = ts
        kept.append(r)
        seen.add(r["accession"])

    kept.sort(key=lambda r: r["_accepted_ts"])

    records: list[dict] = []
    cache_hits = 0
    # Cache item text per accession to avoid re-extracting comparators.
    items_by_acc: dict[str, dict[str, str]] = {}

    async def items_for(row: dict) -> dict[str, str]:
        nonlocal cache_hits
        acc = row["accession"]
        if acc in items_by_acc:
            return items_by_acc[acc]
        was_cached = (FILINGS_TEXT_CACHE / f"{acc}.html").exists()
        raw = await _filing_text(client, cik, row)
        if was_cached:
            cache_hits += 1
        items = _extract_items(_strip_html(raw), row["form"]) if raw else {}
        items_by_acc[acc] = items
        return items

    for curr in kept:
        # Score only filings accepted in [window_start-420d, window_end]; older
        # entries in `kept` exist solely as comparator candidates.
        if curr["_accepted_ts"] < score_lo:
            continue
        curr_items = await items_for(curr)
        if not curr_items:
            # NEITHER item extracted -> similarity null, never filled.
            records.append(_record(ticker, cik, curr, None, {}, None, []))
            continue

        comp = _find_comparator(curr, kept)
        if comp is None:
            records.append(
                _record(ticker, cik, curr, None, {}, None, sorted(curr_items.keys()))
            )
            continue
        comp_items = await items_for(comp)

        sim_items: dict[str, float] = {}
        for key in curr_items:
            if key in comp_items:
                sim_items[key] = round(_cosine_tf(curr_items[key], comp_items[key]), 6)
        # Concatenate the located items (in canonical order) for the headline sim.
        order = ["1A", "7", "2"]
        keys = [k for k in order if k in curr_items and k in comp_items]
        if keys:
            curr_cat = " ".join(curr_items[k] for k in keys)
            comp_cat = " ".join(comp_items[k] for k in keys)
            similarity = round(_cosine_tf(curr_cat, comp_cat), 6)
        else:
            similarity = None  # items found but none shared with comparator

        records.append(
            _record(
                ticker, cik, curr, similarity, sim_items,
                comp["accession"], sorted(curr_items.keys()),
            )
        )

    return records, len(kept), cache_hits


def _record(
    ticker: str,
    cik: int,
    row: dict,
    similarity: float | None,
    sim_items: dict[str, float],
    comparator_accession: str | None,
    items_found: list[str],
) -> dict:
    return {
        "ticker": ticker,
        "cik": int(cik),
        "accession": row["accession"],
        "form": row["form"],
        "accepted": row["_accepted_ts"].isoformat(),
        "report_date": row.get("report_date") or None,
        "similarity": similarity,
        "sim_items": sim_items,
        "comparator_accession": comparator_accession,
        "items_found": items_found,
    }


# --- Stage 0 coverage --------------------------------------------------------


def _coverage(records: list[dict], tickers: list[str], window_start: pd.Timestamp,
              window_end: pd.Timestamp) -> dict:
    """% of manifest tickers with a non-null similarity from a filing accepted
    <= grid date within trailing COVERAGE_TRAILING_DAYS, on a 21-day grid."""
    # ticker -> sorted list of (accepted_ts, similarity) with non-null similarity
    by_ticker: dict[str, list[tuple[pd.Timestamp, float]]] = {}
    for r in records:
        if r["similarity"] is None:
            continue
        by_ticker.setdefault(r["ticker"], []).append(
            (pd.Timestamp(r["accepted"]), r["similarity"])
        )
    for t in by_ticker:
        by_ticker[t].sort(key=lambda x: x[0])

    grid = pd.date_range(window_start, window_end, freq=f"{COVERAGE_GRID_DAYS}D")
    n = len(tickers)
    per_date: list[dict] = []
    for d in grid:
        trail_lo = d - pd.Timedelta(days=COVERAGE_TRAILING_DAYS)
        covered = 0
        for t in tickers:
            hits = by_ticker.get(t, [])
            if any(trail_lo <= ts <= d for ts, _ in hits):
                covered += 1
        per_date.append({
            "date": d.date().isoformat(),
            "covered": covered,
            "pct": round(100.0 * covered / n, 2) if n else 0.0,
        })
    pcts = [p["pct"] for p in per_date]
    return {
        "n_tickers": n,
        "grid_days": COVERAGE_GRID_DAYS,
        "trailing_days": COVERAGE_TRAILING_DAYS,
        "bar_pct": 90.0,
        "min_pct": min(pcts) if pcts else 0.0,
        "per_date": per_date,
    }


async def main() -> int:
    ap = argparse.ArgumentParser(description="Build Lazy-Prices filing-delta sidecar")
    ap.add_argument("--snapshot-id", required=True)
    ap.add_argument("--forms", default="10-K,10-Q", help="comma list (default 10-K,10-Q)")
    ap.add_argument("--items", default="1A,7", help="documentation only; items are fixed by form")
    ap.add_argument("--limit", type=int, default=0, help="first N tickers only (smoke test)")
    ap.add_argument("--rebuild", action="store_true", help="ignore existing sidecar")
    args = ap.parse_args()

    load_dotenv()  # STOCKNEW_EDGAR_USER_AGENT

    from src.market_data.edgar.client import EDGARClient, get_ticker_to_cik

    snap_dir = SNAP_ROOT / args.snapshot_id
    manifest = json.loads((snap_dir / "manifest.json").read_text(encoding="utf-8"))
    tickers: list[str] = manifest["tickers"]
    window_start = pd.Timestamp(manifest["window"]["start"])
    window_end = pd.Timestamp(manifest["window"]["end"])
    if args.limit:
        tickers = tickers[: args.limit]

    forms = set(f.strip().upper() for f in args.forms.split(","))
    if forms != {"10-K", "10-Q"}:
        log.warning("forms %s != fixed {10-K,10-Q}; spec fixes the form set", forms)

    out_path = snap_dir / "filing_delta_signal.json"
    if out_path.exists() and not args.rebuild and not args.limit:
        print(f"{out_path} exists; pass --rebuild to overwrite")
        return 0

    CACHE.mkdir(parents=True, exist_ok=True)
    t2c_path = CACHE / "ticker_cik.json"
    if t2c_path.exists():
        t2c = {k: int(v) for k, v in json.loads(t2c_path.read_text(encoding="utf-8")).items()}
    else:
        client0 = EDGARClient()
        t2c = await get_ticker_to_cik(client0)
        await client0.aclose()
        t2c_path.write_text(json.dumps(t2c), encoding="utf-8")

    client = EDGARClient()
    all_records: list[dict] = []
    missing_cik: list[str] = []
    total_hits = 0
    try:
        for i, t in enumerate(tickers, 1):
            cik = _resolve_cik(t, t2c)
            if cik is None:
                missing_cik.append(t)
                continue
            recs, n_filings, hits = await _process_ticker(
                client, t, cik, window_start, window_end
            )
            all_records.extend(recs)
            total_hits += hits
            if i % 25 == 0:
                print(
                    f"  [{i}/{len(tickers)}] {t}: filings={n_filings} "
                    f"cache_hits={hits} records_total={len(all_records)} "
                    f"text_cache_hits_total={total_hits}",
                    flush=True,
                )
    finally:
        await client.aclose()

    all_records.sort(key=lambda r: (r["ticker"], r["accepted"]))
    coverage = _coverage(all_records, tickers, window_start, window_end)

    payload = {
        "snapshot_id": args.snapshot_id,
        "window": {"start": window_start.date().isoformat(),
                   "end": window_end.date().isoformat()},
        "forms": sorted(forms),
        "n_universe": len(tickers),
        "n_records": len(all_records),
        "n_with_similarity": sum(1 for r in all_records if r["similarity"] is not None),
        "missing_cik": missing_cik,
        "records": all_records,
        "coverage": coverage,
    }
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    n_sim = payload["n_with_similarity"]
    print(
        f"\nWrote {out_path}\n"
        f"  universe={len(tickers)} records={len(all_records)} "
        f"with_similarity={n_sim} missing_cik={len(missing_cik)} "
        f"text_cache_hits={total_hits}"
    )
    print(f"  Stage-0 coverage (bar >=90%): min={coverage['min_pct']}%")
    for p in coverage["per_date"]:
        print(f"    {p['date']}  {p['pct']:5.1f}%  ({p['covered']}/{coverage['n_tickers']})")
    if missing_cik:
        print(f"  missing CIK (sample): {missing_cik[:10]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
