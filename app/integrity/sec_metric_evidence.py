"""Convert comparable SEC XBRL observations into claim-level evidence."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Sequence

from ..providers.sec_client import SecFactRecord
from ..providers.sec_fact_policy import ANNUAL_FORM_PREFIXES, REPORTING_CURRENCIES
from ..schemas import RetrievedEvidence
from .provenance import Provenance, QuantitativeClaim
from .sec_fact_binding import bind_sec_fact


def _scaled(value: int | float, *, prefix: str = "", suffix: str = "") -> str:
    amount = Decimal(str(value))
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    for divisor, scale in ((Decimal("1e12"), "T"), (Decimal("1e9"), "B"),
                           (Decimal("1e6"), "M")):
        if amount >= divisor:
            rendered = f"{amount / divisor:.1f}".rstrip("0").rstrip(".")
            return f"{sign}{prefix}{rendered}{scale}{suffix}"
    rendered = format(amount, ",f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return f"{sign}{prefix}{rendered}{suffix}"


def _value(value: int | float, unit: str) -> str:
    if unit == "USD":
        return _scaled(value, prefix="$")
    if unit == "EUR":
        return _scaled(value, suffix=" EUR")
    if unit == "shares":
        return _scaled(value, suffix=" shares")
    if unit == "USD/shares":
        amount = Decimal(str(value))
        return f"${amount:,.2f} per share"
    raise ValueError("unsupported SEC fact unit")


def _duration(record: SecFactRecord) -> int | None:
    if not record.start:
        return None
    try:
        return (date.fromisoformat(record.end) - date.fromisoformat(record.start)).days
    except (TypeError, ValueError):
        return None


def _duration_matches_form(record: SecFactRecord) -> bool:
    """Reject duration facts that cannot represent the filing's period family."""
    days = _duration(record)
    if days is None:
        return False
    if record.form.startswith(ANNUAL_FORM_PREFIXES):
        return 330 <= days <= 385
    if record.form.startswith("10-Q"):
        # A 10-Q may expose a discrete quarter or a year-to-date duration.
        return 70 <= days <= 300
    return False


def _latest_unambiguous_fact(
    records: Sequence[SecFactRecord], *, include_start: bool,
) -> SecFactRecord | None:
    """Resolve duplicate filing observations without hiding real conflicts."""
    if not records:
        return None
    latest_filed = max(record.filed for record in records)
    latest = [record for record in records if record.filed == latest_filed]
    amendments = [record for record in latest if record.form.endswith("/A")]
    if amendments:
        latest = amendments
    signatures = {
        (
            record.concept,
            record.start if include_start else None,
            record.end,
            record.unit,
            Decimal(str(record.value)),
        )
        for record in latest
    }
    if len(signatures) != 1:
        return None
    # Byte-equivalent observations can be repeated under multiple accessions.
    # Bind the deterministic newest accession after proving their semantics agree.
    return max(latest, key=lambda record: record.accession)


def _verified_claim(
    record: SecFactRecord, *, ticker: str, expected_cik: str,
) -> dict | None:
    amount = Decimal(str(record.value))
    exact = format(amount, ",f")
    if "." in exact:
        exact = exact.rstrip("0").rstrip(".")
    if record.unit == "USD":
        value_text = f"${exact}"
    elif record.unit == "EUR":
        value_text = f"{exact} EUR"
    elif record.unit == "shares":
        value_text = f"{exact} shares"
    elif record.unit == "USD/shares":
        value_text = f"${exact} per share"
    else:
        return None
    claim = QuantitativeClaim(
        value_text=value_text,
        provenance=Provenance.REPORTED,
        raw_value=record.value,
        unit=record.unit,
        ticker=ticker,
        metric=f"us-gaap:{record.concept}",
        as_of=record.end,
        source=record.form,
    )
    bound = bind_sec_fact(
        claim, record, expected_cik=expected_cik, period_start=record.start,
    )
    if bound is None:
        return None
    output = bound.to_dict()
    output.update({
        "period_start": record.start,
        "period_end": record.end,
        "period": (
            f"FY{record.end[:4]}" if record.form.startswith(ANNUAL_FORM_PREFIXES)
            else (f"quarter ended {record.end}" if _duration(record) is not None and _duration(record) <= 100
                  else f"year-to-date period {record.start} to {record.end}")
        ),
        "scope": "consolidated",
        "currency": record.unit if record.unit in REPORTING_CURRENCIES else "USD" if record.unit == "USD/shares" else None,
        "label": record.label,
    })
    if record.inline_binding is not None:
        output["inline_binding"] = dict(record.inline_binding)
    return output


def comparable_metric_evidence(
    records: Sequence[SecFactRecord], *, ticker: str, expected_cik: str,
    concepts: tuple[str, ...], metric_name: str, unit: str = "USD",
) -> RetrievedEvidence | None:
    """Return a latest-versus-prior-period fact, or fail closed on ambiguity."""
    if (not ticker or not expected_cik.isdigit() or not concepts or not metric_name
            or unit not in {*REPORTING_CURRENCIES, "shares", "USD/shares"}):
        return None
    eligible = [
        record for record in records
        if record.cik.lstrip("0") == expected_cik.lstrip("0")
        and record.concept in concepts and record.unit == unit
        and _duration_matches_form(record)
    ]
    if not eligible:
        return None

    latest_end = max(record.end for record in eligible)
    latest_period = [record for record in eligible if record.end == latest_end]
    latest_filed = max(record.filed for record in latest_period)
    latest_rows = [record for record in latest_period if record.filed == latest_filed]
    # Income-statement Company Facts commonly expose both a discrete quarter
    # and year-to-date duration with the same end date and accession. A 10-Q
    # comparison uses the shortest duration; a 10-K comparison must use the
    # longest annual duration and never an embedded fourth-quarter fact.
    period_families = {
        "annual" if record.form.startswith(ANNUAL_FORM_PREFIXES) else "quarterly"
        for record in latest_rows
    }
    if len(period_families) != 1:
        return None
    annual = period_families == {"annual"}
    selected_days = (
        max(_duration(record) for record in latest_rows)
        if annual else min(_duration(record) for record in latest_rows)
    )
    latest_rows = [
        record for record in latest_rows
        if abs(_duration(record) - selected_days) <= 7
    ]
    current = _latest_unambiguous_fact(latest_rows, include_start=True)
    if current is None:
        return None
    current_days = _duration(current)
    current_family = "annual" if current.form.startswith(ANNUAL_FORM_PREFIXES) else "quarterly"

    candidates = []
    current_end = date.fromisoformat(current.end)
    for prior in eligible:
        if prior.concept != current.concept or prior.end >= current.end:
            continue
        prior_family = "annual" if prior.form.startswith(ANNUAL_FORM_PREFIXES) else "quarterly"
        prior_days = _duration(prior)
        gap = (current_end - date.fromisoformat(prior.end)).days
        if (prior_family == current_family and prior_days is not None
                and abs(prior_days - current_days) <= 7 and 350 <= gap <= 380):
            candidates.append(prior)
    if not candidates:
        return None
    prior_end = max(record.end for record in candidates)
    comparable = [record for record in candidates if record.end == prior_end]
    prior = _latest_unambiguous_fact(comparable, include_start=True)
    if prior is None:
        return None
    if prior.value == 0:
        return None

    change = ((Decimal(str(current.value)) - Decimal(str(prior.value)))
              / abs(Decimal(str(prior.value))) * 100)
    direction = "increased" if change >= 0 else "decreased"
    summary = (
        f"{ticker} {metric_name} {direction} {abs(change):.1f}% to "
        f"{_value(current.value, unit)} for the period {current.start} to {current.end}, from "
        f"{_value(prior.value, unit)} in the comparable prior-year period "
        f"{prior.start} to {prior.end}."
    )
    verified_claims = [
        claim for record in (current, prior)
        if (claim := _verified_claim(
            record, ticker=ticker, expected_cik=expected_cik,
        )) is not None
    ]
    if len(verified_claims) != 2:
        return None
    return RetrievedEvidence(
        title=f"{ticker} {metric_name}: {_value(current.value, unit)} ({current.end})",
        source="SEC EDGAR — structured XBRL fact", summary=summary,
        timestamp=current.filed, url=current.filing_url, relevance_score=0.99,
        source_type="regulatory_filing", source_tier="primary",
        claim_type="reported_fact", document_type=current.form,
        reporting_period_start=current.start, reporting_period_end=current.end,
        filed_at=current.filed, extraction_method="structured_xbrl",
        verified_claims=verified_claims,
    )


def comparable_instant_metric_evidence(
    records: Sequence[SecFactRecord], *, ticker: str, expected_cik: str,
    concepts: tuple[str, ...], metric_name: str, unit: str = "USD",
) -> RetrievedEvidence | None:
    """Return a latest-versus-prior-year point-in-time fact."""
    if (not ticker or not expected_cik.isdigit() or not concepts or not metric_name
            or unit not in {*REPORTING_CURRENCIES, "shares"}):
        return None
    eligible = [
        record for record in records
        if record.cik.lstrip("0") == expected_cik.lstrip("0")
        and record.concept in concepts and record.unit == unit
        and record.start is None
    ]
    if not eligible:
        return None

    latest_end = max(record.end for record in eligible)
    latest_rows = [record for record in eligible if record.end == latest_end]
    current = _latest_unambiguous_fact(latest_rows, include_start=False)
    if current is None:
        return None
    current_family = "annual" if current.form.startswith(ANNUAL_FORM_PREFIXES) else "quarterly"
    current_end = date.fromisoformat(current.end)
    candidates = [
        record for record in eligible
        if record.concept == current.concept and record.end < current.end
        and ("annual" if record.form.startswith(ANNUAL_FORM_PREFIXES) else "quarterly") == current_family
        and 350 <= (current_end - date.fromisoformat(record.end)).days <= 380
    ]
    if not candidates:
        return None
    prior_end = max(record.end for record in candidates)
    prior_rows = [record for record in candidates if record.end == prior_end]
    prior = _latest_unambiguous_fact(prior_rows, include_start=False)
    if prior is None:
        return None
    if prior.value == 0:
        return None

    change = ((Decimal(str(current.value)) - Decimal(str(prior.value)))
              / abs(Decimal(str(prior.value))) * 100)
    direction = "increased" if change >= 0 else "decreased"
    summary = (
        f"{ticker} {metric_name} {direction} {abs(change):.1f}% to "
        f"{_value(current.value, unit)} as of {current.end}, from "
        f"{_value(prior.value, unit)} as of the comparable prior-year date "
        f"{prior.end}."
    )
    verified_claims = [
        claim for record in (current, prior)
        if (claim := _verified_claim(
            record, ticker=ticker, expected_cik=expected_cik,
        )) is not None
    ]
    if len(verified_claims) != 2:
        return None
    return RetrievedEvidence(
        title=f"{ticker} {metric_name}: {_value(current.value, unit)} ({current.end})",
        source="SEC EDGAR — structured XBRL fact", summary=summary,
        timestamp=current.filed, url=current.filing_url, relevance_score=0.99,
        source_type="regulatory_filing", source_tier="primary",
        claim_type="reported_fact", document_type=current.form,
        reporting_period_end=current.end, filed_at=current.filed,
        extraction_method="structured_xbrl",
        verified_claims=verified_claims,
    )
