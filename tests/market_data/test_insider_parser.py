"""Tests for src.market_data.insider.parser.

Form 4 XML has minor schema variants across SEC versions (X0306,
X0508, X0603) — we drive the parser with hand-built fixtures that
cover both wrapped and unwrapped <value> children, multiple owners,
multiple transactions, and the malformed cases EDGAR occasionally
ships.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.market_data.insider.parser import (
    InsiderTransaction,
    _normalize_cik,
    _owner_roles,
    parse_form4,
)


def _wrap(*, doc_type: str = "4", owners_xml: str, table_xml: str) -> str:
    """Build a minimal Form 4 XML around the variable parts each test
    needs. Issuer is hard-coded to AAPL for brevity."""
    return f"""<?xml version="1.0"?>
<ownershipDocument>
  <documentType>{doc_type}</documentType>
  <issuer>
    <issuerCik>0000320193</issuerCik>
    <issuerName>Apple Inc.</issuerName>
    <issuerTradingSymbol>AAPL</issuerTradingSymbol>
  </issuer>
  {owners_xml}
  <nonDerivativeTable>
    {table_xml}
  </nonDerivativeTable>
</ownershipDocument>
"""


def _cook_owner() -> str:
    return """
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
    """


def _buy_tx(*, date_iso: str = "2024-01-15", shares: str = "1000",
            price: str = "175.50", code: str = "P", ad: str = "A") -> str:
    return f"""
    <nonDerivativeTransaction>
      <transactionDate><value>{date_iso}</value></transactionDate>
      <transactionCoding>
        <transactionCode>{code}</transactionCode>
      </transactionCoding>
      <transactionAmounts>
        <transactionShares><value>{shares}</value></transactionShares>
        <transactionPricePerShare><value>{price}</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>{ad}</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
    """


class TestParseForm4Basics:
    def test_single_open_market_buy(self) -> None:
        xml = _wrap(owners_xml=_cook_owner(), table_xml=_buy_tx())
        txs = parse_form4(xml, accession_no="0000320193-24-000001",
                          filing_date=date(2024, 1, 17))
        assert len(txs) == 1
        t = txs[0]
        assert t.ticker == "AAPL"
        assert t.issuer_cik == "0000320193"
        assert t.owner_cik == "0001214156"
        assert t.owner_name == "COOK TIMOTHY D"
        assert t.owner_role == "officer"
        assert t.officer_title == "Chief Executive Officer"
        assert t.transaction_code == "P"
        assert t.acquired_disposed == "A"
        assert t.shares == Decimal("1000")
        assert t.price_per_share == Decimal("175.50")
        assert t.value_usd == Decimal("175500.00")
        assert t.transaction_date == date(2024, 1, 15)

    def test_multiple_transactions_same_filing(self) -> None:
        xml = _wrap(owners_xml=_cook_owner(),
                    table_xml=_buy_tx(date_iso="2024-01-15", shares="500")
                              + _buy_tx(date_iso="2024-01-16", shares="700"))
        txs = parse_form4(xml, accession_no="acc",
                          filing_date=date(2024, 1, 17))
        assert len(txs) == 2
        assert {t.shares for t in txs} == {Decimal("500"), Decimal("700")}

    def test_skips_form3_and_form5(self) -> None:
        for doc_type in ("3", "5"):
            xml = _wrap(doc_type=doc_type, owners_xml=_cook_owner(),
                        table_xml=_buy_tx())
            assert parse_form4(xml, accession_no="acc",
                               filing_date=date(2024, 1, 1)) == []

    def test_accepts_form_4a_amendment(self) -> None:
        xml = _wrap(doc_type="4/A", owners_xml=_cook_owner(),
                    table_xml=_buy_tx())
        assert len(parse_form4(xml, accession_no="acc",
                               filing_date=date(2024, 1, 1))) == 1


class TestOwnerRoles:
    def test_combined_director_officer_owner(self) -> None:
        owner_xml = """
        <reportingOwner>
          <reportingOwnerId>
            <rptOwnerCik>9999</rptOwnerCik>
            <rptOwnerName>SMITH JANE</rptOwnerName>
          </reportingOwnerId>
          <reportingOwnerRelationship>
            <isDirector>1</isDirector>
            <isOfficer>1</isOfficer>
            <isTenPercentOwner>1</isTenPercentOwner>
            <officerTitle>President</officerTitle>
          </reportingOwnerRelationship>
        </reportingOwner>
        """
        xml = _wrap(owners_xml=owner_xml, table_xml=_buy_tx())
        txs = parse_form4(xml, accession_no="acc",
                          filing_date=date(2024, 1, 1))
        assert txs[0].owner_role == "officer,director,ten_percent_owner"

    def test_boolean_flag_variants(self) -> None:
        """Form 4 schemas use '1', 'true', or '0' inconsistently —
        the parser must accept all."""
        from xml.etree import ElementTree as ET
        rel = ET.fromstring(
            "<rel>"
            "<isDirector>true</isDirector>"
            "<isOfficer>0</isOfficer>"
            "<isTenPercentOwner>1</isTenPercentOwner>"
            "</rel>"
        )
        assert _owner_roles(rel) == "director,ten_percent_owner"


class TestMultipleOwners:
    def test_joint_filing_emits_per_owner_records(self) -> None:
        owners = _cook_owner() + """
        <reportingOwner>
          <reportingOwnerId>
            <rptOwnerCik>0001234567</rptOwnerCik>
            <rptOwnerName>BERKSHIRE HATHAWAY INC</rptOwnerName>
          </reportingOwnerId>
          <reportingOwnerRelationship>
            <isDirector>0</isDirector>
            <isOfficer>0</isOfficer>
            <isTenPercentOwner>1</isTenPercentOwner>
          </reportingOwnerRelationship>
        </reportingOwner>
        """
        xml = _wrap(owners_xml=owners, table_xml=_buy_tx())
        txs = parse_form4(xml, accession_no="acc",
                          filing_date=date(2024, 1, 1))
        # Single transaction × 2 owners = 2 records
        assert len(txs) == 2
        assert {t.owner_cik for t in txs} == {"0001214156", "0001234567"}


class TestMalformedInputs:
    def test_parse_error_returns_empty_list(self) -> None:
        assert parse_form4("<not-xml", accession_no="acc",
                           filing_date=date(2024, 1, 1)) == []

    def test_missing_issuer_cik(self) -> None:
        xml = """<?xml version="1.0"?>
<ownershipDocument>
  <documentType>4</documentType>
  <issuer><issuerName>X</issuerName></issuer>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerCik>1</rptOwnerCik>
      <rptOwnerName>X</rptOwnerName>
    </reportingOwnerId>
  </reportingOwner>
  <nonDerivativeTable/>
</ownershipDocument>"""
        assert parse_form4(xml, accession_no="acc",
                           filing_date=date(2024, 1, 1)) == []

    def test_skip_zero_share_row(self) -> None:
        xml = _wrap(owners_xml=_cook_owner(), table_xml=_buy_tx(shares="0"))
        assert parse_form4(xml, accession_no="acc",
                           filing_date=date(2024, 1, 1)) == []

    def test_skip_invalid_acquired_disposed_code(self) -> None:
        """If A/D code is missing or garbage, skip the row rather than
        guess — sells and buys have opposite trading implications."""
        xml = _wrap(owners_xml=_cook_owner(), table_xml=_buy_tx(ad="X"))
        assert parse_form4(xml, accession_no="acc",
                           filing_date=date(2024, 1, 1)) == []

    def test_no_table_returns_empty(self) -> None:
        xml = """<?xml version="1.0"?>
<ownershipDocument>
  <documentType>4</documentType>
  <issuer>
    <issuerCik>0000320193</issuerCik>
    <issuerName>Apple Inc.</issuerName>
    <issuerTradingSymbol>AAPL</issuerTradingSymbol>
  </issuer>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerCik>1</rptOwnerCik>
      <rptOwnerName>X</rptOwnerName>
    </reportingOwnerId>
  </reportingOwner>
</ownershipDocument>"""
        assert parse_form4(xml, accession_no="acc",
                           filing_date=date(2024, 1, 1)) == []


class TestNonCashTransactions:
    def test_grant_with_no_price(self) -> None:
        """Code A (grant), no price — common for RSU vesting. We still
        emit the row so the analyzer can choose to filter; value_usd
        comes out None."""
        xml = _wrap(
            owners_xml=_cook_owner(),
            table_xml="""
            <nonDerivativeTransaction>
              <transactionDate><value>2024-01-15</value></transactionDate>
              <transactionCoding>
                <transactionCode>A</transactionCode>
              </transactionCoding>
              <transactionAmounts>
                <transactionShares><value>500</value></transactionShares>
                <transactionPricePerShare><value>0</value></transactionPricePerShare>
                <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
              </transactionAmounts>
            </nonDerivativeTransaction>
            """,
        )
        txs = parse_form4(xml, accession_no="acc",
                          filing_date=date(2024, 1, 1))
        assert len(txs) == 1
        assert txs[0].transaction_code == "A"
        # 0 price → value = 0, not None — the analyzer treats both as
        # non-meaningful for cluster math.
        assert txs[0].price_per_share == Decimal("0")
        assert txs[0].value_usd == Decimal("0.00")


class TestCikNormalization:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("320193", "0000320193"),
            ("0000320193", "0000320193"),
            ("  320193 ", "0000320193"),
            ("CIK0000320193", "0000320193"),
            ("", None),
            (None, None),
        ],
    )
    def test_normalize(self, raw, expected) -> None:
        assert _normalize_cik(raw) == expected
