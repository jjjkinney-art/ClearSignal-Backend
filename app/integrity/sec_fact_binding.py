"""Bind a precisely identified reported claim to its SEC XBRL observation.

This is deliberately opt-in. Text extraction's generic metric and rounded
figures cannot establish the identity of an XBRL fact.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import Optional

from ..providers.sec_client import SecFactRecord
from .provenance import ClaimDocumentReference, Provenance, QuantitativeClaim


def bind_sec_fact(
    claim: QuantitativeClaim,
    record: SecFactRecord,
    *,
    expected_cik: str,
    period_start: Optional[str],
) -> Optional[QuantitativeClaim]:
    """Return a cited copy only when every available identity agrees.

    ``expected_cik`` must come from the trusted symbol-to-registrant lookup,
    and ``period_start`` must be explicitly supplied by the claim producer.
    A null start denotes an instant fact, never an unspecified duration.
    The SEC filing index identifies the filing, not the position of a fact
    within the document.
    """
    if not isinstance(claim, QuantitativeClaim) or not isinstance(record, SecFactRecord):
        return None
    if (claim.provenance is not Provenance.REPORTED or claim.document_ref is not None
            or not claim.ticker or not expected_cik or not expected_cik.isdigit()
            or not record.cik.isdigit() or int(expected_cik) != int(record.cik)
            or record.taxonomy != "us-gaap" or not record.concept
            or claim.metric != f"us-gaap:{record.concept}"
            or claim.unit != record.unit or claim.as_of != record.end
            or period_start != record.start or claim.source != record.form
            or record.form not in ("10-K", "10-Q", "10-K/A", "10-Q/A")
            or not record.accession or not record.filed):
        return None

    # A record constructed outside the SEC parser cannot substitute another
    # filing's URL. Reject rather than quietly linking the wrong document.
    accession = record.accession
    if (len(accession) != 20 or accession[10] != "-" or accession[13] != "-"
            or not accession.replace("-", "").isdigit()):
        return None
    expected_url = (f"https://www.sec.gov/Archives/edgar/data/{int(record.cik)}/"
                    f"{accession.replace('-', '')}/{accession}-index.htm")
    if record.filing_url != expected_url:
        return None

    try:
        date.fromisoformat(record.end)
        date.fromisoformat(record.filed)
        if record.start is not None:
            date.fromisoformat(record.start)
    except (TypeError, ValueError):
        return None

    try:
        if (claim.raw_value is None or isinstance(claim.raw_value, bool)
                or isinstance(record.value, bool)
                or not isfinite(float(claim.raw_value))
                or not isfinite(float(record.value))
                or Decimal(str(claim.raw_value)) != Decimal(str(record.value))):
            return None
    except (ValueError, TypeError, OverflowError, InvalidOperation):
        return None

    # The displayed text must denote the same unscaled value. A raw_value
    # of one million paired with "$9M" must never inherit the fact's link.
    if record.unit not in ("USD", "shares"):
        return None
    displayed = format(Decimal(str(record.value)), ",f")
    if "." in displayed:
        displayed = displayed.rstrip("0").rstrip(".")
    expected_display = (f"${displayed}" if record.unit == "USD"
                        else f"{displayed} shares")
    if claim.value_text != expected_display:
        return None

    reference = ClaimDocumentReference(
        reference_id=f"sec:{record.cik}:{accession}:{record.taxonomy}:{record.concept}",
        title=f"{record.form} filed {record.filed} · {record.label}",
        provider="SEC EDGAR", url=expected_url, published_at=record.filed,
    )
    return replace(claim, document_ref=reference)
