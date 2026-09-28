"""Extract explicitly requested issuer KPIs with exact document anchors."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from ..integrity.provenance import (
    ClaimDocumentReference, Provenance, QuantitativeClaim,
)
from ..schemas import RetrievedEvidence
from .public_document_ingestion import PublicDocument


_ALLOWED_SOURCE_TYPES = {"issuer_release", "investor_presentation", "regulatory_filing"}
_ALLOWED_DOCUMENT_TYPES = {
    "earnings_release", "investor_presentation", "shareholder_letter",
    "press_release", "sec_exhibit", "8-K", "8-K/A", "6-K", "6-K/A",
}
_VALUE = (
    r"(?P<value>\$?\s*-?\d[\d,]*(?:\.\d+)?\s*"
    r"(?:%|x|basis points|bps|thousand|million|billion|trillion|[KMBT])?)"
)
_VERB = (
    r"(?:was|were|reached|totaled|stood\s+at|grew\s+to|increased\s+to|"
    r"decreased\s+to|rose\s+to|fell\s+to|of|:)"
)


@dataclass(frozen=True)
class SourceBoundKpi:
    metric: str
    matched_alias: str
    value_text: str
    raw_value: float
    unit: str
    quote: str
    page: int | None
    section: str | None
    claim: QuantitativeClaim


def _parse_value(value: str) -> tuple[float, str] | None:
    compact = re.sub(r"\s+", " ", value.strip())
    lowered = compact.lower()
    currency = compact.startswith("$")
    number_match = re.search(r"-?\d[\d,]*(?:\.\d+)?", compact)
    if not number_match:
        return None
    try:
        amount = Decimal(number_match.group(0).replace(",", ""))
    except InvalidOperation:
        return None
    scale = Decimal(1)
    if re.search(r"(?:\bthousand\b|\bK\b)", compact, re.IGNORECASE):
        scale = Decimal("1e3")
    elif re.search(r"(?:\bmillion\b|\bM\b)", compact, re.IGNORECASE):
        scale = Decimal("1e6")
    elif re.search(r"(?:\bbillion\b|\bB\b)", compact, re.IGNORECASE):
        scale = Decimal("1e9")
    elif re.search(r"(?:\btrillion\b|\bT\b)", compact, re.IGNORECASE):
        scale = Decimal("1e12")
    if "%" in compact:
        unit = "%"
    elif lowered.endswith("x"):
        unit = "x"
    elif "basis points" in lowered or lowered.endswith("bps"):
        unit = "bp"
    elif currency:
        unit = "USD"
    elif scale != 1:
        unit = "count"
    else:
        return None
    return float(amount * scale), unit


def _bounded_statement(text: str, start: int, end: int) -> str:
    left = max(text.rfind(". ", 0, start), text.rfind("? ", 0, start),
               text.rfind("! ", 0, start))
    left = left + 2 if left >= 0 else 0
    endings = [position for token in (". ", "? ", "! ")
               if (position := text.find(token, end)) >= 0]
    right = min(endings) + 1 if endings else len(text)
    statement = text[left:right].strip()
    if len(statement) <= 300:
        return statement
    window_start = max(0, start - 120)
    window_end = min(len(text), end + 120)
    return text[window_start:window_end].strip()[:300]


def _anchor(
    document: PublicDocument, start: int, end: int,
) -> tuple[int | None, str | None, str] | None:
    for page in document.pages:
        if page.start_offset <= start and end <= page.end_offset:
            return page.page_number, None, _bounded_statement(
                page.text, start - page.start_offset, end - page.start_offset,
            )
    for index, section in enumerate(document.sections):
        section_end = (
            document.sections[index + 1].start_offset
            if index + 1 < len(document.sections) else len(document.text)
        )
        if section.start_offset <= start and end <= section_end:
            section_text = document.text[section.start_offset:section_end]
            return None, section.heading, _bounded_statement(
                section_text, start - section.start_offset, end - section.start_offset,
            )
    return None


def extract_source_bound_kpis(
    document: PublicDocument,
    *,
    ticker: str,
    metric_aliases: dict[str, tuple[str, ...]],
) -> list[SourceBoundKpi]:
    """Extract only requested KPIs that resolve to one unambiguous value."""
    if (not isinstance(ticker, str) or not ticker.strip()
            or len(metric_aliases) > 25 or not document.text_ready or not document.text
            or document.source_tier != "primary"
            or document.source_type not in _ALLOWED_SOURCE_TYPES
            or document.document_type not in _ALLOWED_DOCUMENT_TYPES
            or not re.fullmatch(r"[0-9a-f]{64}", document.content_hash)):
        return []
    try:
        date.fromisoformat(document.published_at or "")
    except (TypeError, ValueError):
        return []

    results: list[SourceBoundKpi] = []
    for metric, aliases in metric_aliases.items():
        clean_aliases = tuple(dict.fromkeys(
            alias.strip() for alias in aliases
            if isinstance(alias, str) and 1 <= len(alias.strip()) <= 100
        ))
        clean_aliases = clean_aliases[:10]
        if not metric.strip() or not clean_aliases:
            continue
        alias_pattern = "|".join(
            sorted((re.escape(alias) for alias in clean_aliases), key=len, reverse=True)
        )
        pattern = re.compile(
            rf"(?P<alias>{alias_pattern})\s*(?:\([^)]{{1,80}}\))?\s*{_VERB}\s*{_VALUE}",
            re.IGNORECASE,
        )
        matches = []
        for match in pattern.finditer(document.text):
            parsed = _parse_value(match.group("value"))
            anchored = _anchor(document, match.start(), match.end())
            if not parsed or not anchored:
                continue
            raw_value, unit = parsed
            page, section, quote = anchored
            if not quote or match.group(0).lower() not in quote.lower():
                continue
            matches.append((match, raw_value, unit, page, section, quote))
        identities = {(raw, unit) for _, raw, unit, _, _, _ in matches}
        if len(identities) != 1:
            continue
        match, raw_value, unit, page, section, quote = matches[0]
        value_text = re.sub(r"\s+", " ", match.group("value").strip())
        anchor = f"p{page}" if page is not None else f"section:{section}"
        reference = ClaimDocumentReference(
            reference_id=f"document:{document.content_hash}:{anchor}:{metric.strip().lower()}",
            title=document.title or document.document_type.replace("_", " ").title(),
            provider=document.publisher or "Issuer",
            url=document.final_url,
            published_at=document.published_at,
            page=page,
            section=section,
            content_hash=document.content_hash,
            quote=quote,
        )
        claim = QuantitativeClaim(
            value_text=value_text,
            provenance=Provenance.REPORTED,
            as_of=document.published_at,
            confidence="high",
            raw_value=raw_value,
            unit=unit,
            source=document.document_type,
            ticker=ticker.upper().strip(),
            metric=f"issuer:{metric.strip()}",
            document_ref=reference,
        )
        results.append(SourceBoundKpi(
            metric=metric.strip(), matched_alias=match.group("alias"),
            value_text=value_text, raw_value=raw_value, unit=unit,
            quote=quote, page=page, section=section, claim=claim,
        ))
    return results


def kpi_as_evidence(kpi: SourceBoundKpi, document: PublicDocument) -> RetrievedEvidence:
    """Promote a bound KPI into analysis evidence without losing its anchor."""
    reference = kpi.claim.document_ref
    if reference is None or reference.content_hash != document.content_hash:
        raise ValueError("KPI is not bound to this document")
    location = f"page {kpi.page}" if kpi.page is not None else f"section {kpi.section}"
    return RetrievedEvidence(
        title=f"{kpi.claim.ticker} {kpi.metric}: {kpi.value_text}",
        source=document.publisher or "Issuer",
        summary=(
            f"{kpi.claim.ticker} reported {kpi.metric} as {kpi.value_text} "
            f"in the cited primary document ({location})."
        ),
        timestamp=document.published_at or "",
        url=document.final_url,
        relevance_score=0.98,
        source_type=document.source_type,
        source_tier="primary",
        claim_type="reported_fact",
        document_type=document.document_type,
        page=kpi.page,
        section=kpi.section,
        extraction_method=document.extraction_method,
    )
