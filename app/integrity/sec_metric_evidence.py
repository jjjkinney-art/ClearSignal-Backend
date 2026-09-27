"""Convert comparable SEC XBRL observations into claim-level evidence."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Sequence

from ..providers.sec_client import SecFactRecord
from ..schemas import RetrievedEvidence


def _money(value: int | float) -> str:
    amount = Decimal(str(value))
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    for divisor, suffix in ((Decimal("1e12"), "T"), (Decimal("1e9"), "B"),
                            (Decimal("1e6"), "M")):
        if amount >= divisor:
            rendered = f"{amount / divisor:.1f}".rstrip("0").rstrip(".")
            return f"{sign}${rendered}{suffix}"
    rendered = format(amount, ",f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return f"{sign}${rendered}"


def _duration(record: SecFactRecord) -> int | None:
    if not record.start:
        return None
    try:
        return (date.fromisoformat(record.end) - date.fromisoformat(record.start)).days
    except (TypeError, ValueError):
        return None


def comparable_metric_evidence(
    records: Sequence[SecFactRecord], *, ticker: str, expected_cik: str,
    concepts: tuple[str, ...], metric_name: str,
) -> RetrievedEvidence | None:
    """Return a latest-versus-prior-period fact, or fail closed on ambiguity."""
    if not ticker or not expected_cik.isdigit() or not concepts or not metric_name:
        return None
    eligible = [
        record for record in records
        if record.cik.lstrip("0") == expected_cik.lstrip("0")
        and record.concept in concepts and record.unit == "USD"
        and _duration(record) is not None
    ]
    if not eligible:
        return None

    latest_end = max(record.end for record in eligible)
    latest_period = [record for record in eligible if record.end == latest_end]
    latest_filed = max(record.filed for record in latest_period)
    latest_rows = [record for record in latest_period if record.filed == latest_filed]
    if len({(r.concept, r.start, r.value, r.accession) for r in latest_rows}) != 1:
        return None
    current = latest_rows[0]
    current_days = _duration(current)
    current_family = "annual" if current.form.startswith("10-K") else "quarterly"

    candidates = []
    current_end = date.fromisoformat(current.end)
    for prior in eligible:
        if prior.concept != current.concept or prior.end >= current.end:
            continue
        prior_family = "annual" if prior.form.startswith("10-K") else "quarterly"
        prior_days = _duration(prior)
        gap = (current_end - date.fromisoformat(prior.end)).days
        if (prior_family == current_family and prior_days is not None
                and abs(prior_days - current_days) <= 7 and 350 <= gap <= 380):
            candidates.append(prior)
    if not candidates:
        return None
    prior_end = max(record.end for record in candidates)
    comparable = [record for record in candidates if record.end == prior_end]
    prior_filed = max(record.filed for record in comparable)
    comparable = [record for record in comparable if record.filed == prior_filed]
    if len({(r.start, r.value, r.accession) for r in comparable}) != 1:
        return None
    prior = comparable[0]
    if prior.value == 0:
        return None

    change = ((Decimal(str(current.value)) - Decimal(str(prior.value)))
              / abs(Decimal(str(prior.value))) * 100)
    direction = "increased" if change >= 0 else "decreased"
    summary = (
        f"{ticker} {metric_name} {direction} {abs(change):.1f}% to "
        f"{_money(current.value)} for the period ended {current.end}, from "
        f"{_money(prior.value)} in the comparable prior-year period ended "
        f"{prior.end}."
    )
    return RetrievedEvidence(
        title=f"{ticker} {metric_name}: {_money(current.value)} ({current.end})",
        source="SEC EDGAR — structured XBRL fact", summary=summary,
        timestamp=current.filed, url=current.filing_url, relevance_score=0.99,
    )
