"""Parse a DERA financial-statement-dataset quarter zip into
``list[FundamentalSnapshot]``.

The bulk format (sub.txt + num.txt) is pre-resolved by filing — one row
per ``(adsh, tag)`` in num.txt vs companyfacts' "everything for one CIK"
JSON. That lets us flatten directly to one snapshot per filing without
the companyfacts parser's per-concept latest-filed dedup pass.

Concept priority still matters when a filing tags the same line item
under multiple concepts (Revenues vs SalesRevenueNet, etc.) — we honor
the order in ``CONCEPT_MAP`` / ``DERIVED_CONCEPTS`` and let later
concepts overwrite earlier ones only when the later concept is
strictly higher-priority.

Chaining + YoY: replicates the second-pass logic from
``src.market_data.edgar.parser`` per ticker. We re-implement the small
helpers here rather than reach into the existing module so the bulk
path stays decoupled (the same arithmetic; verified in test parity).
"""

from __future__ import annotations

import logging
import zipfile
from datetime import datetime, timezone
from io import TextIOWrapper
from typing import Iterable, Mapping

import pandas as pd

from src.contracts.entities.fundamentals import FundamentalSnapshot, FundamentalsSource
from src.market_data.edgar.concept_map import CONCEPT_MAP, DERIVED_CONCEPTS

logger = logging.getLogger(__name__)

# Forms we ingest. 10-K/A and 10-Q/A amendments are skipped — the original
# filings already populated the snapshot and amendments rarely change the
# scoring-relevant numbers materially. (Same policy as the companyfacts parser.)
TARGET_FORMS = frozenset({"10-K", "10-Q"})

NUM_CHUNKSIZE = 250_000
"""How many num.txt rows pandas reads per chunk. Quarter num.txt has ~5-10M
rows so we never want it all in memory. 250k is ~30MB of dataframe each."""


def _form_to_source(form: str) -> FundamentalsSource | None:
    """Same mapping as the companyfacts parser. Bulk dataset uses the
    same raw form strings."""
    form_norm = form.upper().strip()
    if form_norm == "10-K":
        return "edgar_10k"
    if form_norm == "10-Q":
        return "edgar_10q"
    return None


def _parse_filed(filed_int: int | str) -> datetime:
    """Bulk sub.txt encodes ``filed`` as ``YYYYMMDD`` int. Companyfacts parser
    uses noon-UTC to dodge day-rollover with valid_to chaining; mirror it."""
    s = str(filed_int)
    dt = datetime.strptime(s, "%Y%m%d")
    return dt.replace(hour=12, tzinfo=timezone.utc)


# Concept → (field_name, priority). Lower number = higher priority. Built
# once from CONCEPT_MAP + DERIVED_CONCEPTS so we can do a single dict
# lookup per num.txt row.
_FIELD_BY_TAG: dict[str, tuple[str, int]] = {}


def _build_tag_index() -> None:
    if _FIELD_BY_TAG:
        return
    for field, concepts in CONCEPT_MAP:
        for prio, c in enumerate(concepts):
            # First (existing) wins ties — CONCEPT_MAP entries shouldn't
            # collide across fields, but be defensive.
            _FIELD_BY_TAG.setdefault(c, (field, prio))
    for field, concepts in DERIVED_CONCEPTS.items():
        for prio, c in enumerate(concepts):
            _FIELD_BY_TAG.setdefault(c, (field, prio))


_build_tag_index()
TAG_SET: frozenset[str] = frozenset(_FIELD_BY_TAG.keys())
"""All us-gaap concepts the parser cares about — pre-filtered against num.txt
to keep ~95% of rows from ever entering pandas."""


def _safe_ratio(num: float | None, denom: float | None) -> float | None:
    if num is None or denom in (None, 0):
        return None
    try:
        return float(num) / float(denom)
    except (TypeError, ZeroDivisionError):
        return None


def _pct_change(current: float | None, prior: float | None) -> float | None:
    """Same semantics as the companyfacts parser's ``_pct_change``:
    sign-flips return None (loss → profit doesn't have a well-defined
    growth percentage)."""
    if current is None or prior is None or prior == 0:
        return None
    if (current >= 0) != (prior >= 0):
        return None
    return (current - prior) / abs(prior)


def _compute_yoy(
    current: FundamentalSnapshot, prior: list[FundamentalSnapshot]
) -> tuple[float | None, float | None]:
    """365d ± ~65d same-source match. Mirrors the companyfacts parser."""
    if not prior:
        return None, None
    target_delta_days = 365
    window_lo, window_hi = 300, 430
    same_source = [
        p for p in prior
        if p.source == current.source
        and window_lo <= (current.valid_from - p.valid_from).days <= window_hi
    ]
    if not same_source:
        return None, None
    prior_row = min(
        same_source,
        key=lambda p: abs((current.valid_from - p.valid_from).days - target_delta_days),
    )
    rev_yoy = _pct_change(current.revenue, prior_row.revenue)
    eps_yoy = _pct_change(current.eps_diluted, prior_row.eps_diluted)
    return rev_yoy, eps_yoy


def _read_sub(zf: zipfile.ZipFile) -> pd.DataFrame:
    """Load sub.txt fully — it's ~5-15k rows per quarter (one row per filing).

    We keep ``adsh, cik, form, filed`` and drop everything else. The CIK
    column is int in the DERA spec; cast explicitly so the downstream
    map lookup doesn't need to normalize.
    """
    with zf.open("sub.txt") as raw:
        # Tab-separated, despite the .txt extension. Quoting disabled because
        # SEC fields can contain stray quotes in company names.
        df = pd.read_csv(
            raw,
            sep="\t",
            dtype={"adsh": str, "form": str},
            usecols=["adsh", "cik", "form", "filed"],
            na_values=["", "NULL"],
            quoting=3,  # csv.QUOTE_NONE
            on_bad_lines="skip",
        )
    df = df.dropna(subset=["adsh", "cik", "form", "filed"])
    df["cik"] = df["cik"].astype("int64")
    df["filed"] = df["filed"].astype("int64")
    df = df[df["form"].isin(TARGET_FORMS)]
    return df.reset_index(drop=True)


def _iter_num_chunks(zf: zipfile.ZipFile) -> Iterable[pd.DataFrame]:
    """Stream num.txt in chunks, filtered to our concept set in-memory.

    Filtering by tag list FIRST keeps the join-side small — a quarter's
    raw num.txt is ~5-10M rows, of which only ~3-5% match our ~25 concepts.
    """
    with zf.open("num.txt") as raw:
        # zipfile.open returns a binary stream; pandas needs text for the
        # chunked iterator over a streaming handle. TextIOWrapper makes
        # it line-oriented.
        text = TextIOWrapper(raw, encoding="utf-8", errors="replace", newline="")
        reader = pd.read_csv(
            text,
            sep="\t",
            usecols=["adsh", "tag", "ddate", "uom", "value"],
            dtype={"adsh": str, "tag": str, "uom": str},
            na_values=["", "NULL"],
            quoting=3,
            on_bad_lines="skip",
            chunksize=NUM_CHUNKSIZE,
        )
        for chunk in reader:
            chunk = chunk[chunk["tag"].isin(TAG_SET)]
            if not chunk.empty:
                yield chunk


def _select_value(
    existing: tuple[float, int] | None, new_value: float, new_prio: int
) -> tuple[float, int]:
    """Concept-priority resolution within one filing. Lower prio wins."""
    if existing is None or new_prio < existing[1]:
        return (new_value, new_prio)
    return existing


def _build_snapshot(
    ticker: str,
    source: FundamentalsSource,
    filed_int: int,
    fields: dict[str, float],
) -> FundamentalSnapshot:
    """Apply the same derived-ratio formulas as the companyfacts parser.

    Fields not present leave their FundamentalSnapshot column at None.
    The repository's upsert is happy with partial rows.
    """
    revenue = fields.get("revenue")
    gross = fields.get("gross_margin")  # raw GrossProfit value, divided below
    net_income = fields.get("net_income")
    equity = fields.get("stockholders_equity")
    assets = fields.get("total_assets")
    long_term_debt = fields.get("long_term_debt")
    current_debt = fields.get("current_debt")
    cash = fields.get("total_cash")
    ocf = fields.get("operating_cash_flow")
    capex = fields.get("capex")
    eps_diluted = fields.get("eps_diluted")
    operating_income = fields.get("operating_income")
    current_assets = fields.get("current_assets")
    current_liabilities = fields.get("current_liabilities")

    # Tier-1 audit #9 (D#5 + D#6): mirrors the companyfacts parser so the
    # two ingest paths produce identical FundamentalSnapshot rows. See
    # src/market_data/edgar/parser.py for the why.
    from src.market_data.edgar.parser import _compute_fcf, _sum_optional_components

    total_debt = _sum_optional_components(long_term_debt, current_debt)
    free_cash_flow = _compute_fcf(
        ocf, capex, ticker=ticker, filed=str(filed_int),
    )

    gross_margin_pct = _safe_ratio(gross, revenue)
    profit_margin_pct = _safe_ratio(net_income, revenue)
    operating_margin_pct = _safe_ratio(operating_income, revenue)
    roe = _safe_ratio(net_income, equity)
    roa = _safe_ratio(net_income, assets)
    debt_to_equity = _safe_ratio(total_debt, equity)
    current_ratio = _safe_ratio(current_assets, current_liabilities)

    return FundamentalSnapshot(
        ticker=ticker,
        valid_from=_parse_filed(filed_int),
        valid_to=None,  # filled in chain pass
        source=source,
        revenue=float(revenue) if revenue is not None else None,
        eps_diluted=float(eps_diluted) if eps_diluted is not None else None,
        gross_margin=gross_margin_pct,
        operating_margin=operating_margin_pct,
        profit_margin=profit_margin_pct,
        roe=roe,
        roa=roa,
        debt_to_equity=debt_to_equity,
        current_ratio=current_ratio,
        free_cash_flow=free_cash_flow,
        total_cash=float(cash) if cash is not None else None,
        total_debt=total_debt,
    )


def _chain_and_yoy(snapshots: list[FundamentalSnapshot]) -> list[FundamentalSnapshot]:
    """Sort by valid_from, set valid_to = next snapshot's valid_from, compute
    YoY growth. Same logic as the companyfacts parser's second pass."""
    snapshots.sort(key=lambda s: s.valid_from)
    out: list[FundamentalSnapshot] = []
    for i, snap in enumerate(snapshots):
        updates: dict[str, object] = {}
        if i + 1 < len(snapshots):
            updates["valid_to"] = snapshots[i + 1].valid_from
        rev_yoy, eps_yoy = _compute_yoy(snap, snapshots[:i])
        if rev_yoy is not None:
            updates["revenue_growth_yoy"] = rev_yoy
        if eps_yoy is not None:
            updates["earnings_growth_yoy"] = eps_yoy
        out.append(snap.model_copy(update=updates) if updates else snap)
    return out


def parse_quarter_zip(
    zip_path,
    cik_to_ticker: Mapping[int, str],
) -> list[FundamentalSnapshot]:
    """Open a DERA quarter zip and emit ``FundamentalSnapshot`` rows for every
    in-universe filing. Tickers absent from ``cik_to_ticker`` are dropped.

    Returns one snapshot per (ticker, filing). ``valid_to`` is chained within
    each ticker only — cross-ticker chaining doesn't make sense. YoY fields
    populate only when a prior-year same-source row exists *in the same zip*;
    cross-quarter YoY enrichment is the orchestrator's job (it can pass the
    accumulated snapshots back through ``_chain_and_yoy`` once all quarters
    are loaded — see ingest.py).
    """
    cik_to_ticker = {int(k): v.upper() for k, v in cik_to_ticker.items()}

    with zipfile.ZipFile(zip_path) as zf:
        sub = _read_sub(zf)
        # Filter to in-universe CIKs early. Use a Python set lookup vectorized
        # via isin — pandas handles this faster than a row-wise apply.
        sub = sub[sub["cik"].isin(cik_to_ticker.keys())]
        if sub.empty:
            logger.info("Bulk zip %s: no in-universe filings", zip_path)
            return []

        # adsh → (cik, ticker, source, filed_int)
        adsh_to_meta: dict[str, tuple[int, str, FundamentalsSource, int]] = {}
        for _, row in sub.iterrows():
            source = _form_to_source(row["form"])
            if source is None:
                continue
            adsh = row["adsh"]
            cik = int(row["cik"])
            ticker = cik_to_ticker[cik]
            adsh_to_meta[adsh] = (cik, ticker, source, int(row["filed"]))

        adsh_set = frozenset(adsh_to_meta.keys())

        # For each filing, accumulate (field → (value, priority))
        per_filing: dict[str, dict[str, tuple[float, int]]] = {}
        for chunk in _iter_num_chunks(zf):
            chunk = chunk[chunk["adsh"].isin(adsh_set)]
            if chunk.empty:
                continue
            # value can be NaN for footnote-only rows — drop those before we
            # even materialize them. Dropping null values also catches the
            # rare uom="USD/shares" rows where we still want to take the
            # numeric value (CONCEPT_MAP doesn't differentiate units; EPS
            # is the only USD/shares-tagged field we touch, so this is fine).
            chunk = chunk.dropna(subset=["value"])
            for row in chunk.itertuples(index=False):
                adsh = row.adsh
                tag = row.tag
                value = float(row.value)
                field_prio = _FIELD_BY_TAG.get(tag)
                if field_prio is None:
                    continue
                field, prio = field_prio
                bucket = per_filing.setdefault(adsh, {})
                bucket[field] = _select_value(bucket.get(field), value, prio)

    # Flatten to FundamentalSnapshots per ticker, then chain.
    by_ticker: dict[str, list[FundamentalSnapshot]] = {}
    for adsh, meta in adsh_to_meta.items():
        fields_raw = per_filing.get(adsh)
        if not fields_raw:
            # Filing had no concepts we care about. Skip — no rows to write.
            continue
        fields = {k: v[0] for k, v in fields_raw.items()}
        _, ticker, source, filed_int = meta
        snap = _build_snapshot(ticker, source, filed_int, fields)
        by_ticker.setdefault(ticker, []).append(snap)

    results: list[FundamentalSnapshot] = []
    for tkr, snaps in by_ticker.items():
        results.extend(_chain_and_yoy(snaps))
    return results
