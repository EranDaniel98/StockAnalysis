"""Parse SEC Form 4 XML into typed ``InsiderTransaction`` records.

Form 4 XML structure (excerpt):

    <ownershipDocument>
      <documentType>4</documentType>
      <periodOfReport>2024-01-15</periodOfReport>
      <issuer>
        <issuerCik>0000320193</issuerCik>
        <issuerName>Apple Inc.</issuerName>
        <issuerTradingSymbol>AAPL</issuerTradingSymbol>
      </issuer>
      <reportingOwner>
        <reportingOwnerId>
          <rptOwnerCik>0001214156</rptOwnerCik>
          <rptOwnerName>COOK TIMOTHY D</rptOwnerName>
        </reportingOwnerId>
        <reportingOwnerRelationship>
          <isDirector>0</isDirector>
          <isOfficer>1</isOfficer>
          <isTenPercentOwner>0</isTenPercentOwner>
          <officerTitle>Chief Executive Officer</officerTitle>
        </reportingOwnerRelationship>
      </reportingOwner>
      <nonDerivativeTable>
        <nonDerivativeTransaction>
          <transactionDate><value>2024-01-15</value></transactionDate>
          <transactionCoding>
            <transactionCode>P</transactionCode>
          </transactionCoding>
          <transactionAmounts>
            <transactionShares><value>1000</value></transactionShares>
            <transactionPricePerShare><value>175.50</value></transactionPricePerShare>
            <transactionAcquiredDisposedCode>
              <value>A</value>
            </transactionAcquiredDisposedCode>
          </transactionAmounts>
        </nonDerivativeTransaction>
      </nonDerivativeTable>
    </ownershipDocument>

A single Form 4 can carry multiple transactions across multiple owners
(joint filings are rare but legal). We emit one ``InsiderTransaction``
per <nonDerivativeTransaction>; derivative-table entries (options
exercises etc.) are skipped — the cluster-buy signal we care about is
open-market common-stock activity.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InsiderTransaction:
    """One row of an insider's reported transaction.

    Mirrors the ``insider_transactions`` table schema. Decimal for share
    counts because Form 4 reports fractional shares for DRIP/ESPP.
    """

    issuer_cik: str
    issuer_name: Optional[str]
    ticker: Optional[str]  # may be missing on older/non-public-issuer filings
    accession_no: str
    filing_date: date
    owner_cik: str
    owner_name: str
    owner_role: str  # comma-joined: officer,director,ten_percent_owner
    officer_title: Optional[str]
    transaction_date: date
    transaction_code: str
    acquired_disposed: str  # 'A' or 'D'
    shares: Decimal
    price_per_share: Optional[Decimal]
    value_usd: Optional[Decimal]


def _text(elem: Optional[ET.Element]) -> Optional[str]:
    if elem is None:
        return None
    txt = (elem.text or "").strip()
    return txt or None


def _text_value(parent: Optional[ET.Element], path: str) -> Optional[str]:
    """Form 4 fields are usually wrapped as <field><value>X</value></field>.
    Resolve both the wrapped and unwrapped shapes so the parser doesn't
    care about minor schema variations across X0306 / X0508 / X0603."""
    if parent is None:
        return None
    elem = parent.find(path)
    if elem is None:
        return None
    val = elem.find("value")
    return _text(val if val is not None else elem)


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _parse_decimal(s: Optional[str]) -> Optional[Decimal]:
    if s is None:
        return None
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


def _parse_bool_flag(s: Optional[str]) -> bool:
    """Form 4 uses '1'/'0' or 'true'/'false' for relationship flags
    inconsistently across versions."""
    if s is None:
        return False
    return s.strip().lower() in ("1", "true", "yes")


def _normalize_cik(raw: Optional[str]) -> Optional[str]:
    """CIKs in Form 4 sometimes arrive zero-padded ('0000320193'),
    sometimes bare ('320193'). Normalize to zero-padded 10-digit so
    joins/lookups are deterministic across all callers."""
    if not raw:
        return None
    digits = "".join(c for c in raw if c.isdigit())
    if not digits:
        return None
    return digits.zfill(10)


def _owner_roles(rel: Optional[ET.Element]) -> str:
    """Collapse Form 4's three relationship flags into a comma-joined
    string for storage. Empty string when none are set (rare)."""
    if rel is None:
        return ""
    roles: list[str] = []
    if _parse_bool_flag(_text_value(rel, "isOfficer")):
        roles.append("officer")
    if _parse_bool_flag(_text_value(rel, "isDirector")):
        roles.append("director")
    if _parse_bool_flag(_text_value(rel, "isTenPercentOwner")):
        roles.append("ten_percent_owner")
    if _parse_bool_flag(_text_value(rel, "isOther")):
        roles.append("other")
    return ",".join(roles)


def parse_form4(
    xml_text: str,
    *,
    accession_no: str,
    filing_date: date,
) -> list[InsiderTransaction]:
    """Parse one Form 4 XML document.

    Returns an empty list (and logs a warning) on parse errors or
    unexpected document types — caller treats that as "nothing to
    ingest for this accession" rather than an exception, so a
    single malformed filing doesn't crash a batch backfill.

    Derivative transactions (option grants, RSU vesting, etc.) are
    intentionally skipped: the cluster-buy signal works on common-
    stock activity. Form 4 also lists a derivativeTable; we ignore it.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.warning("Form 4 %s: XML parse error: %s", accession_no, e)
        return []

    doc_type = _text(root.find("documentType"))
    if doc_type not in ("4", "4/A"):
        # Not a Form 4 — could be a Form 3 (initial statement) or 5
        # (annual statement). We don't ingest those today.
        return []

    issuer = root.find("issuer")
    issuer_cik = _normalize_cik(_text(issuer.find("issuerCik")) if issuer is not None else None)
    issuer_name = _text(issuer.find("issuerName")) if issuer is not None else None
    ticker_raw = _text(issuer.find("issuerTradingSymbol")) if issuer is not None else None
    ticker = ticker_raw.upper() if ticker_raw else None

    if not issuer_cik:
        logger.warning("Form 4 %s: missing issuerCik", accession_no)
        return []

    # Form 4 can have multiple reporting owners on a single filing.
    owners: list[tuple[str, str, str, Optional[str]]] = []  # (cik, name, roles, officer_title)
    for owner in root.findall("reportingOwner"):
        owner_id = owner.find("reportingOwnerId")
        owner_cik = _normalize_cik(_text(owner_id.find("rptOwnerCik")) if owner_id is not None else None)
        owner_name = _text(owner_id.find("rptOwnerName")) if owner_id is not None else None
        if not owner_cik or not owner_name:
            continue
        rel = owner.find("reportingOwnerRelationship")
        owners.append((
            owner_cik,
            owner_name,
            _owner_roles(rel),
            _text_value(rel, "officerTitle"),
        ))

    if not owners:
        logger.warning("Form 4 %s: no reporting owners parsed", accession_no)
        return []

    out: list[InsiderTransaction] = []
    table = root.find("nonDerivativeTable")
    if table is None:
        # All-derivative filings (pure option grants) — nothing to ingest.
        return []

    for tx in table.findall("nonDerivativeTransaction"):
        tx_date = _parse_date(_text_value(tx, "transactionDate"))
        if tx_date is None:
            continue

        coding = tx.find("transactionCoding")
        tx_code = _text(coding.find("transactionCode")) if coding is not None else None
        if not tx_code:
            continue

        amounts = tx.find("transactionAmounts")
        shares = _parse_decimal(_text_value(amounts, "transactionShares"))
        if shares is None or shares <= 0:
            continue
        price = _parse_decimal(_text_value(amounts, "transactionPricePerShare"))
        ad_code = (_text_value(amounts, "transactionAcquiredDisposedCode") or "").strip().upper()
        if ad_code not in ("A", "D"):
            # Form 4 occasionally has malformed rows — skip rather
            # than guess direction.
            continue

        value_usd = (
            (shares * price).quantize(Decimal("0.01"))
            if price is not None
            else None
        )

        # Emit one record per (transaction × owner). Joint filings rare
        # but legal; replicating per-owner keeps the cluster-detector
        # math straightforward downstream.
        for owner_cik, owner_name, roles, title in owners:
            out.append(InsiderTransaction(
                issuer_cik=issuer_cik,
                issuer_name=issuer_name,
                ticker=ticker,
                accession_no=accession_no,
                filing_date=filing_date,
                owner_cik=owner_cik,
                owner_name=owner_name,
                owner_role=roles,
                officer_title=title,
                transaction_date=tx_date,
                transaction_code=tx_code,
                acquired_disposed=ad_code,
                shares=shares,
                price_per_share=price,
                value_usd=value_usd,
            ))

    return out
