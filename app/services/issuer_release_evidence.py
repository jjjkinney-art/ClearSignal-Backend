"""Bounded issuer-controlled release retrieval; first adapter: Tesla deliveries.

URLs and figures are discovered from current publisher documents, never from
question text or a hardcoded quarterly release. Unsupported layouts fail closed.
"""
from __future__ import annotations

import calendar
import logging
import re
from datetime import date, datetime, timezone
from urllib.parse import urlsplit

from ..integrity.provenance import ClaimDocumentReference, Provenance, QuantitativeClaim
from ..schemas import RetrievedEvidence
from .public_document_ingestion import PublicDocument, PublicDocumentError, fetch_public_document

logger = logging.getLogger(__name__)
_INDEX = "https://ir.tesla.com/press"
_TITLE = re.compile(
    r"Tesla (First|Second|Third|Fourth) Quarter (20\d{2}) Production,? Deliveries (?:&|and) Deployments",
    re.I,
)
_QUARTERS = {"first": 1, "second": 2, "third": 3, "fourth": 4}


def requests_issuer_release(ticker: str, question: str) -> bool:
    return (ticker.strip().upper() == "TSLA" and bool(re.search(
        r"\b(?:deliveries|vehicle production|production volume)\b", question, re.I)))


def _official_url(url: str, *, index: bool = False) -> bool:
    try:
        p = urlsplit(url)
        return (p.scheme == "https" and p.netloc == "ir.tesla.com"
                and not p.query and not p.fragment
                and (p.path == "/press" if index else bool(re.fullmatch(
                    r"/press-release/tesla-[a-z0-9-]+", p.path))))
    except ValueError:
        return False


def extract_delivery_release(document: PublicDocument, *, question: str,
                             evaluated_on: date | None = None) -> list[RetrievedEvidence]:
    """Bind exact total-row values to issuer, publication date and quarter."""
    if (not document.text_ready or document.extraction_method != "html"
            or not _official_url(document.requested_url) or not _official_url(document.final_url)
            or document.source_type != "issuer_release" or document.source_tier != "primary"
            or document.publisher != "Tesla Investor Relations"
            or not re.fullmatch(r"[0-9a-f]{64}", document.content_hash)):
        return []
    headings = [(section, _TITLE.fullmatch(section.heading)) for section in document.sections
                if _TITLE.fullmatch(section.heading)]
    if len(headings) != 1:
        return []
    heading_section, heading = headings[0]
    if document.text[heading_section.start_offset:heading_section.start_offset + len(heading_section.heading)] != heading_section.heading:
        return []
    # Publisher's dateline, not an index timestamp, retrieval time, or URL year.
    dates = re.findall(r"AUSTIN, Texas, ([A-Za-z]+ \d{1,2}, 20\d{2})\s*[–—-]",
                       document.text[heading_section.start_offset:heading_section.start_offset + 1000])
    if len(dates) != 1:
        return []
    try:
        published = datetime.strptime(dates[0], "%B %d, %Y").date()
    except ValueError:
        return []
    return _delivery_table_evidence(document, question=question, heading=heading,
                                    published=published, evaluated_on=evaluated_on)


def _delivery_table_evidence(document: PublicDocument, *, question: str, heading,
                             published: date, evaluated_on: date | None = None,
                             sec_layout: bool = False) -> list[RetrievedEvidence]:
    quarter, year = _QUARTERS[heading[1].lower()], int(heading[2])
    month = quarter * 3
    period_end = date(year, month, calendar.monthrange(year, month)[1])
    period_start = date(year, month - 2, 1)
    if (published > (evaluated_on or datetime.now(timezone.utc).date())
            or not 0 <= (published - period_end).days <= 45):
        return []
    candidates = []
    for table in document.tables:
        if set(re.findall(r"\bQ([1-4])\s+(20\d{2})\b", table.context)) != {(str(quarter), str(year))}:
            continue
        rows = table.rows
        if sec_layout:
            # Reviewed EDGAR layout: one 15-cell spacer row, four five-cell
            # data rows with an empty trailing spacer, then two blank rows.
            # Never remove arbitrary cells or infer shifted numeric columns.
            if (len(rows) != 7 or rows[0] != ("",) * 15
                    or rows[-2:] != (("",) * 5,) * 2
                    or any(len(row) != 5 or row[-1] != "" for row in rows[1:5])):
                continue
            rows = tuple(row[:4] for row in rows[1:5])
        if len(rows) != 4:
            continue
        header = tuple(cell.strip() for cell in rows[0])
        if header != ("", "Production", "Deliveries", "Subject to operating lease accounting"):
            continue
        if any(len(row) != 4 for row in rows[1:]):
            continue
        if [row[0] for row in rows[1:]] != ["Model 3/Y", "Other Models", "Total"]:
            continue
        if any(not re.fullmatch(r"\d{1,3}(?:,\d{3})*|\d+", row[col])
               for row in rows[1:] for col in (1, 2)):
            continue
        values = [[int(row[col].replace(",", "")) for col in (1, 2)] for row in rows[1:]]
        if any(values[0][col] + values[1][col] != values[2][col] for col in (0, 1)):
            continue
        # Bind parsed cells to the visible text, excluding hidden-only tables.
        total_quote = " ".join(rows[-1])
        visible = " ".join(document.text.split())
        if (" ".join(header).strip() not in visible
                or any(" ".join(row) not in visible for row in rows[1:])):
            continue
        candidates.append((table, values[2], total_quote, header))
    if len(candidates) != 1:
        return []
    table, totals, quote, header = candidates[0]
    evidence = []
    metrics = []
    if re.search(r"\bdeliveries\b", question, re.I):
        metrics.append(("vehicle deliveries", 1))
    if re.search(r"\b(?:vehicle production|production volume)\b", question, re.I):
        metrics.append(("vehicle production", 0))
    for metric, col in metrics:
        section = f"Q{quarter} {year} Production and Deliveries — table {table.table_number}"
        ref = ClaimDocumentReference(
            reference_id=f"document:{document.content_hash}:table:{table.table_number}:{metric}",
            title=heading[0], provider=document.publisher, url=document.final_url,
            published_at=published.isoformat(), section=section,
            content_hash=document.content_hash, quote=quote,
        )
        claim = QuantitativeClaim(
            value_text=f"{totals[col]:,}", raw_value=totals[col], unit="vehicles",
            provenance=Provenance.REPORTED, as_of=period_end.isoformat(),
            ticker="TSLA", metric=f"issuer:{metric}", confidence="high",
            source="press_release", document_ref=ref,
        ).to_dict()
        claim.update(period_start=period_start.isoformat(), period_end=period_end.isoformat(),
                     table_columns=list(header), table_number=table.table_number,
                     row_label="Total")
        evidence.append(RetrievedEvidence(
            title=f"TSLA Q{quarter} {year} {metric}: {totals[col]:,}",
            source=document.publisher,
            summary=(f"Tesla reported {totals[col]:,} {metric} for Q{quarter} {year} "
                     f"(period ended {period_end.isoformat()}) in its {published.isoformat()} release. "
                     "Deliveries alone do not establish profitability or competitive advantage."),
            timestamp=published.isoformat(), retrieved_at=document.accessed_at,
            url=document.final_url, source_type=document.source_type, source_tier="primary",
            claim_type="reported_fact", document_type="press_release", section=section,
            reporting_period_start=period_start.isoformat(), reporting_period_end=period_end.isoformat(),
            extraction_method="html", relevance_score=0.98, verified_claims=[claim],
        ))
    return evidence


def fetch_issuer_release_evidence(ticker: str, *, question: str,
                                user_agent: str = "") -> list[RetrievedEvidence]:
    """Fetch one reviewed index and at most two linked actual delivery releases."""
    if not requests_issuer_release(ticker, question):
        return []
    try:
        index = fetch_public_document(_INDEX, user_agent=user_agent, extract_tables=False)
        if not index.text_ready or not _official_url(index.final_url, index=True):
            return []
        urls = []
        for link in index.links:
            if (_official_url(link.url) and _TITLE.fullmatch(link.label.strip())
                    and link.url not in urls):
                urls.append(link.url)
            if len(urls) == 2:
                break
        evidence = []
        for url in urls:
            try:
                document = fetch_public_document(
                    url, user_agent=user_agent, publisher="Tesla Investor Relations",
                    document_type="press_release", source_type="issuer_release", source_tier="primary",
                )
                evidence.extend(extract_delivery_release(document, question=question))
            except PublicDocumentError as exc:
                logger.info("Issuer release skipped: %s", exc.failure_kind)
        return sorted(evidence, key=lambda item: item.timestamp, reverse=True)
    except PublicDocumentError as exc:
        logger.info("Issuer release discovery unavailable: %s; http_status=%s error_class=%s",
                    exc.failure_kind, exc.http_status, exc.error_class)
        return []


_SEC_TESLA_PATH = re.compile(r"/Archives/edgar/data/0*1318605/(\d{18})/[^/]+\.htm(?:l)?")


def _tesla_sec_accession(url: str) -> str | None:
    try:
        parsed = urlsplit(url)
        match = _SEC_TESLA_PATH.fullmatch(parsed.path)
        return (match[1] if parsed.scheme == "https" and parsed.netloc == "www.sec.gov"
                and not parsed.query and not parsed.fragment and match else None)
    except ValueError:
        return None


def extract_sec_delivery_release(document: PublicDocument, *, cover: PublicDocument,
                                 ticker: str, question: str,
                                 evaluated_on: date | None = None) -> list[RetrievedEvidence]:
    """Read the reviewed EDGAR table only through its issuer's dated 8-K link."""
    if not requests_issuer_release(ticker, question):
        return []
    accession = _tesla_sec_accession(cover.final_url)
    if not accession or cover.document_type != "8-K":
        return []
    for doc in (cover, document):
        if (not doc.text_ready or doc.extraction_method != "html"
                or doc.publisher != "SEC EDGAR" or doc.source_type != "regulatory_filing"
                or doc.source_tier != "primary"
                or not re.fullmatch(r"[0-9a-f]{64}", doc.content_hash)
                or _tesla_sec_accession(doc.requested_url) != accession
                or _tesla_sec_accession(doc.final_url) != accession):
            return []
    if document.final_url == cover.final_url:
        return []
    links = [link for link in cover.links if link.url == document.requested_url
             and re.search(r"Press release of Tesla, Inc\., dated", link.label, re.I)]
    if not links:
        return []
    visible_cover = " ".join(cover.text.split())
    dates = re.findall(
        r"On ([A-Za-z]+ \d{1,2}, 20\d{2}), Tesla, Inc\. published the press release "
        r"which is attached hereto as Exhibit 99\.1 and is incorporated herein by reference\.",
        visible_cover,
    )
    if len(dates) != 1 or not re.search(r"\bTSLA\b", visible_cover):
        return []
    try:
        published = datetime.strptime(dates[0], "%B %d, %Y").date()
        filed = date.fromisoformat(str(cover.published_at)[:10])
    except (ValueError, TypeError):
        return []
    if not 0 <= (filed - published).days <= 7 or document.published_at != cover.published_at:
        return []
    visible = " ".join(document.text.split())
    headings = list(_TITLE.finditer(visible))
    if len(headings) != 1 or not re.search(r"\bExhibit 99\.1\b", visible):
        return []
    evidence = _delivery_table_evidence(document, question=question, heading=headings[0],
                                        published=published, evaluated_on=evaluated_on,
                                        sec_layout=True)
    for item in evidence:
        item.verified_claims[0]["publication_binding"] = {
            "cover_url": cover.final_url, "cover_content_hash": cover.content_hash,
            "quote": f"On {dates[0]}, Tesla, Inc. published the press release "
                     "which is attached hereto as Exhibit 99.1 and is incorporated herein by reference.",
            "exhibit": "99.1",
        }
    return evidence
