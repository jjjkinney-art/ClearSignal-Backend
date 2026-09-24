"""Select a source-backed revenue fact without interpreting generated prose."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Sequence

from ..providers.sec_client import SecFactRecord
from .provenance import Provenance, QuantitativeClaim
from .sec_fact_binding import bind_sec_fact


REVENUE_CONCEPTS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
)


def latest_sec_revenue_claim(
    records: Sequence[SecFactRecord], *, ticker: str, expected_cik: str,
) -> dict | None:
    """Return one exact SEC claim or None on absent/ambiguous observations.

    Only full annual 10-K or three-month 10-Q revenue periods qualify. An
    amendment can replace the original filing; the most recently filed
    observation for the latest period wins. Conflicting concepts within the
    selected period fail closed.
    """
    if not ticker or not expected_cik or not expected_cik.isdigit():
        return None
    eligible: list[SecFactRecord] = []
    for record in records:
        if record.concept not in REVENUE_CONCEPTS or record.unit != "USD" or not record.start:
            continue
        try:
            days = (date.fromisoformat(record.end) - date.fromisoformat(record.start)).days
        except (TypeError, ValueError):
            continue
        if record.form in ("10-Q", "10-Q/A") and 70 <= days <= 110:
            eligible.append(record)
        elif record.form in ("10-K", "10-K/A") and 330 <= days <= 390:
            eligible.append(record)
    if not eligible:
        return None

    latest_end = max(record.end for record in eligible)
    same_period = [record for record in eligible if record.end == latest_end]
    latest_filed = max(record.filed for record in same_period)
    latest = [record for record in same_period if record.filed == latest_filed]
    # Two taxonomy concepts can describe subtly different revenue measures.
    # Never pick one by arbitrary ordering when both exist in the same filing.
    if len({(record.concept, record.start, record.value, record.accession)
            for record in latest}) != 1:
        return None
    record = latest[0]
    value = format(Decimal(str(record.value)), ",f")
    if "." in value:
        value = value.rstrip("0").rstrip(".")
    claim = QuantitativeClaim(
        value_text=f"${value}", provenance=Provenance.REPORTED,
        raw_value=record.value, unit="USD", ticker=ticker,
        metric=f"us-gaap:{record.concept}", as_of=record.end,
        source=record.form,
    )
    bound = bind_sec_fact(
        claim, record, expected_cik=expected_cik, period_start=record.start,
    )
    if bound is None:
        return None
    result = bound.to_dict()
    result["period_start"] = record.start
    result["period_end"] = record.end
    result["label"] = record.label
    return result
