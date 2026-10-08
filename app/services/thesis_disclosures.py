"""Bounded official business descriptions and sampled risk context for broad theses."""
from datetime import date
from itertools import islice
import logging
import re

from ..integrity.provenance import ClaimDocumentReference
from ..schemas import RetrievedEvidence
from .issuer_risk_evidence import (
    RISK_TOPICS, IssuerRiskProfile, _issuer_url, bound_issuer_risk,
    extract_issuer_risk_evidence,
)
from .public_document_ingestion import fetch_public_document
from .sec_risk_sections import complete_business_window, risk_sentence_spans
from .providers import sec_provider

logger = logging.getLogger(__name__)
SECTION = "Item 1. Business"


def requests_thesis_disclosures(ticker: str, question: str) -> bool:
    from .financial_thesis_foundation import is_broad_thesis_request
    from .live_issuer_kpi_service import requested_issuer_kpi_aliases
    return (is_broad_thesis_request(question)
            and not re.search(r"\b(?:services|app store|icloud|apple music|digital content)\b", question, re.I)
            and not any(re.search(pattern, question, re.I) for pattern in RISK_TOPICS.values())
            and not requested_issuer_kpi_aliases(question))


def _business_quote(quote):
    # Exact complete, short qualitative sentences only. Numbers, forecasts and
    # promotional assertions do not become business-model facts here.
    return (isinstance(quote, str) and 60 <= len(quote) <= 300
            and bool(re.match(r"(?:We|Our company|The company)\b", quote, re.I))
            and bool(re.search(r"\b(?:design|manufactur|develop|provid|sell|operat|distribut|deliver|produc)\w*\b", quote, re.I))
            and quote.endswith(".") and not re.search(r"\d|[%$€£]|\b(?:will|may|could|expect|leading|best|superior)\b", quote, re.I))


def _business_summary(value):
    return (f'{value["ticker"]} described its business in its 10-K filed '
            f'{value["document_ref"]["published_at"]}: “{value["quote"]}” '
            'This is an issuer description; competitive advantage and future performance remain unverified.')


def extract_business_descriptions(document, *, ticker, cik):
    if (document.document_type != "10-K" or document.publisher != "SEC EDGAR"
            or document.source_type != "regulatory_filing" or document.source_tier != "primary"
            or document.extraction_method != "html" or not document.text_ready
            or not _issuer_url(document.final_url, IssuerRiskProfile(cik, "Business", ""))):
        return []
    try:
        if date.fromisoformat(document.published_at or "") > date.today():
            return []
    except (TypeError, ValueError):
        return []
    window = complete_business_window(document.text)
    if not window:
        return []
    start, end = window
    result = []
    for left, right in islice(risk_sentence_spans(document.text[start:end]), 2000):
        quote = document.text[start + left:start + right]
        if not _business_quote(quote):
            continue
        offset = start + left
        try:
            ref = ClaimDocumentReference(reference_id=f"document:{document.content_hash}:business:{offset}",
                title=document.title or f"{ticker} 10-K", provider="SEC EDGAR", url=document.final_url,
                published_at=document.published_at, section=SECTION,
                content_hash=document.content_hash, quote=quote).to_dict()
        except (TypeError, ValueError):
            return []
        value = dict(claim_kind="issuer_business_description", ticker=ticker, quote=quote,
                     start_offset=offset, end_offset=offset + len(quote), document_ref=ref)
        result.append(RetrievedEvidence(title=f"{ticker} business description · {document.published_at} · {len(result)+1}",
            source="SEC EDGAR", summary=_business_summary(value), timestamp=document.published_at,
            url=document.final_url, relevance_score=0.96, source_type="regulatory_filing",
            source_tier="primary", claim_type="reported_fact", document_type="10-K",
            filed_at=document.published_at, section=SECTION, extraction_method="html",
            business_disclosures=[value]))
        if len(result) == 2:
            break
    return result


def bound_business_description(item, *, ticker, cik):
    values = getattr(item, "business_disclosures", [])
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        return None
    value = values[0]
    try:
        ref = ClaimDocumentReference(**value["document_ref"]).to_dict()
        start, end = value["start_offset"], value["end_offset"]
        if (value.get("claim_kind") != "issuer_business_description" or value.get("ticker") != ticker
                or not _business_quote(value.get("quote")) or value["quote"] != ref.get("quote")
                or ref.get("provider") != "SEC EDGAR" or ref.get("section") != SECTION
                or not ref.get("content_hash") or not _issuer_url(ref["url"], IssuerRiskProfile(cik, "Business", ""))
                or ref["url"] != item.url or ref.get("published_at") != item.timestamp
                or date.fromisoformat(item.timestamp) > date.today()
                or type(start) is not int or type(end) is not int or start < 0 or end - start != len(value["quote"])
                or ref["reference_id"] != f'document:{ref["content_hash"]}:business:{start}'
                or item.source != "SEC EDGAR" or item.source_type != "regulatory_filing"
                or item.source_tier != "primary" or item.claim_type != "reported_fact"
                or item.document_type != "10-K" or item.section != SECTION or item.extraction_method != "html"
                or item.freshness_status in {"unavailable", "conflicting", "superseded", "stale"}
                or item.summary != _business_summary(value)):
            return None
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    return value


def bound_thesis_risk(item, *, ticker):
    values = getattr(item, "risk_disclosures", [])
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        return None
    scope = values[0].get("scope")
    if scope not in RISK_TOPICS or getattr(item, "freshness_status", None) == "stale":
        return None
    return bound_issuer_risk(item, ticker=ticker, question=f"What operating risk affects {scope}?")


def fetch_thesis_disclosures(ticker, *, question, user_agent=""):
    """One full annual filing; failures remain gaps, never ticker-specific prose."""
    if not requests_thesis_disclosures(ticker, question):
        return []
    try:
        cik = sec_provider._load_ticker_cik_map().get(ticker)
        if not cik:
            return []
        filings = sec_provider.fetch_recent_filings(ticker, forms=["10-K", "20-F"],
            limit=1, years_back=2, prefer_results=False) or []
        if not filings:
            return []
        filing = filings[0]
        if filing.document_type not in {"10-K", "20-F"}:
            return []
        document = fetch_public_document(filing.url, user_agent=user_agent, publisher="SEC EDGAR",
            published_at=filing.timestamp, document_type=filing.document_type,
            source_type="regulatory_filing", source_tier="primary", sec_periodic_limits=True,
            preserve_sec_business=True, extract_tables=False)
        business = extract_business_descriptions(document, ticker=ticker, cik=cik)
        risks = []
        seen = set()
        for scope in RISK_TOPICS:
            for item in extract_issuer_risk_evidence(document, ticker=ticker,
                    question=f"What operating risk affects {scope}?"):
                value = bound_thesis_risk(item, ticker=ticker)
                if value and value["quote"] not in seen:
                    seen.add(value["quote"])
                    risks.append(item)
        # Source order, never an assertion that these are the most material risks.
        risks.sort(key=lambda item: item.risk_disclosures[0]["start_offset"])
        return business + risks[:2]
    except Exception as exc:
        logger.warning("thesis disclosures unavailable for %s: %s", ticker, type(exc).__name__)
        return []
