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
from .issuer_succession import reviewed_predecessor_annual

logger = logging.getLogger(__name__)
SECTION = "Item 1. Business"
_BUSINESS_HEADING_PREFIX = re.compile(
    r"^(?:(?:Company Background|Business Overview|Company Overview|Overview|General|Our Business|Business Description|Segment Information|Business segments (?:&|and) Corporate)\s+){1,3}"
    r"(?=(?:For management reporting purposes,\s+)?(?:We|Our company|The company|The firm)\b)", re.I)
_BUSINESS_ASPIRATION_OR_PROMOTION = re.compile(
    r"\b(?:committed to|focused on|seeks? to|aims? to|strives? to|intend\w*|"
    r"plan\w* to|working to|continue\w* to grow|value[- ]creating|"
    r"creating long[- ]term value|strong returns|profitably|"
    r"high[- ]quality|cost[- ]effective)\b", re.I)
_CURRENT_BUSINESS_PREDICATE = re.compile(
    r"^(?:We|Our company|The company|The firm)\s+"
    r"(?:(?:also|primarily|principally|currently|generally)\s+){0,2}"
    r"(?:designs?|manufactures?|develops?|provides?|sells?|operates?|"
    r"distributes?|delivers?|produces?|markets?|"
    r"(?:are|is) (?:a|an) (?:manufacturer|provider|producer|distributor|"
    r"operator|developer|retailer))\b|"
    r"^(?:Our company|The company|The firm)['\u2019]s\s+"
    r"(?:operations|business|(?:line|range|portfolio) of [^.]{1,100})\s+"
    r"(?:(?:are|is) (?:comprised of|organized into)|"
    r"includes?|comprises?|consists? of)\b", re.I)
_CURRENT_SEGMENT_STRUCTURE = re.compile(
    r"^(?:Our company|The company|The firm)['\u2019]s\s+"
    r"(?:(?:consumer|wholesale|retail|commercial)\s+)?business segments?\s+"
    r"(?:is|are)\s+(?!expected\b|planned\b|proposed\b|potential\b|intended\b)", re.I)
_NAMED_SEGMENT_STRUCTURE = re.compile(
    r"^(?:For management reporting purposes,\s+)?"
    r"(?:We|Our company|The company|The firm)\s+(?:has|have)\s+"
    r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+"
    r"reportable business segments?\s*[\u2013\u2014:-]\s+"
    # Require spelled-out names, rather than interpreting unfamiliar acronyms.
    r"(?=(?-i:[A-Z][a-z]{2,})\b)", re.I)
_INTERNAL_EMPLOYEE_ACTIVITY = re.compile(
    r"\b(?:for|to)\s+our\s+(?:employees|staff|workforce)\b|"
    r"\b(?:skills|professional|career) development across our "
    r"(?:organization|workforce)\b", re.I)
_GENERIC_RISK_INTRODUCTION = re.compile(
    r"^(?:(?:Any|All|Some|One|Each)\s+(?:of\s+)?(?:the\s+|these\s+|our\s+)?"
    r"(?:risk factors|risks)\s+(?:discussed|described|listed|set forth)\s+"
    r"(?:above|below|herein)\b|"
    r"(?:Additional|Other) risks and uncertainties not "
    r"(?:presently|currently) known to us\b|"
    r"Our operations and financial results are subject to "
    r"(?:various|certain) risks and uncertainties,? including those described below\b)", re.I)



def _business_issuer_url(url, cik):
    """Compare numeric issuer identity using SEC archive-path representation."""
    # The directory pads to ten digits; archive URLs omit those zeroes.
    # Validate before normalization so malformed identities cannot become
    # regex patterns or authorize a different issuer.
    if not isinstance(cik, str) or not re.fullmatch(r"[0-9]{1,10}", cik) or int(cik) <= 0:
        return False
    return _issuer_url(url, IssuerRiskProfile(str(int(cik)), "Business", ""))


def requests_thesis_disclosures(ticker: str, question: str) -> bool:
    from .financial_thesis_foundation import is_broad_thesis_request
    from .live_issuer_kpi_service import requested_issuer_kpi_aliases
    return (is_broad_thesis_request(question)
            and not re.search(r"\b(?:services|app store|icloud|apple music|digital content)\b", question, re.I)
            and not any(re.search(pattern, question, re.I) for pattern in RISK_TOPICS.values())
            and not requested_issuer_kpi_aliases(question))


def _business_quote(quote):
    return _business_quote_rejection(quote) is None


def _bare_segment_list(quote):
    """Recognize only segment predicates whose objects are bare acronyms."""
    for clause in re.split(r",\s+and\s+", quote[:-1], flags=re.I):
        predicate = _CURRENT_SEGMENT_STRUCTURE.match(clause)
        if not predicate or not re.fullmatch(
                r"[A-Z]{2,8}(?:,\s*[A-Z]{2,8})*(?:\s+and\s+[A-Z]{2,8})?",
                clause[predicate.end():]):
            return False
    return True


def _business_quote_rejection(quote):
    # Exact complete, short qualitative sentences only. Numbers, forecasts and
    # mixed operational/aspirational prose do not become business-model facts.
    # Do not clip a factual-looking clause out of a promotional sentence.
    if not isinstance(quote, str) or not 60 <= len(quote) <= 300:
        return "length"
    if re.search(r"\d|[%$€£]|\b(?:will|may|could|expect|leading|best|superior)\b", quote, re.I):
        return "numeric_or_forward_looking"
    if _BUSINESS_ASPIRATION_OR_PROMOTION.search(quote):
        return "aspirational_or_promotional"
    # A current 'provide' predicate can describe internal human-capital
    # programs rather than the issuer's products or customer services.
    # Withhold the complete sentence; never clip out a business-looking clause.
    if _INTERNAL_EMPLOYEE_ACTIVITY.search(quote):
        return "internal_employee_activity"
    # Activity words in a strategy, belief or potential project are not a
    # current operating predicate. Require the main subject to state the
    # activity, current business role, segment structure or product range.
    if (not (_CURRENT_BUSINESS_PREDICATE.match(quote)
             or _CURRENT_SEGMENT_STRUCTURE.match(quote)
             or _NAMED_SEGMENT_STRUCTURE.match(quote))
            or not quote.endswith(".")):
        return "subject_or_activity"
    return None


def _business_summary(value):
    return (f'{value["ticker"]} described its business in its 10-K filed '
            f'{value["document_ref"]["published_at"]}: “{value["quote"]}” '
            'This is an issuer description; competitive advantage and future performance remain unverified.')


def extract_business_descriptions(document, *, ticker, cik, diagnostics=None):
    stats = diagnostics if diagnostics is not None else {}
    stats.update(status="document_ineligible", sentences=0, heading_prefixes_removed=0,
                 extracted_descriptions=0, rejection_counts={})
    if (document.document_type != "10-K" or document.publisher != "SEC EDGAR"
            or document.source_type != "regulatory_filing" or document.source_tier != "primary"
            or document.extraction_method != "html" or not document.text_ready
            or not _business_issuer_url(document.final_url, cik)):
        return []
    try:
        if date.fromisoformat(document.published_at or "") > date.today():
            return []
    except (TypeError, ValueError):
        return []
    window = complete_business_window(document.text)
    stats["status"] = "no_complete_business_section"
    if not window:
        return []
    start, end = window
    stats["status"] = "no_qualifying_business_sentence"
    candidates = []
    for left, right in islice(risk_sentence_spans(document.text[start:end]), 2000):
        quote = document.text[start + left:start + right]
        stats["sentences"] += 1
        # Normalized HTML joins block headings to the next sentence. Remove
        # only an explicit shared heading prefix; retain the entire sentence.
        heading = _BUSINESS_HEADING_PREFIX.match(quote)
        if heading:
            left += heading.end()
            quote = document.text[start + left:start + right]
            stats["heading_prefixes_removed"] += 1
        reason = _business_quote_rejection(quote)
        if reason:
            stats["rejection_counts"][reason] = stats["rejection_counts"].get(reason, 0) + 1
            continue
        candidates.append((start + left, quote))
    # Prefer an admitted description of operations over a bare segment list.
    # This is a presentation rule, never a claim of competitive importance.
    # Preserve source order within each group and the existing two-item cap.
    if any(_NAMED_SEGMENT_STRUCTURE.match(quote) for _, quote in candidates):
        # A source-spelled segment list supersedes the redundant bare list;
        # do not expand abbreviations by guessing or by a ticker dictionary.
        candidates = [(offset, quote) for offset, quote in candidates
                      if not _bare_segment_list(quote)]
    candidates.sort(key=lambda row: (2 if _CURRENT_SEGMENT_STRUCTURE.match(row[1])
                                    else 1 if _NAMED_SEGMENT_STRUCTURE.match(row[1]) else 0,
                                    row[0]))
    result = []
    for offset, quote in candidates[:2]:
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
        stats.update(status="business_extracted", extracted_descriptions=len(result))
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
                or not ref.get("content_hash") or not _business_issuer_url(ref["url"], cik)
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
    # Broad-thesis context needs a specific sampled mechanism. A generic
    # introduction does not become useful merely by mentioning liquidity.
    # Keep the narrower topic-specific risk producer and its binding unchanged.
    quote = values[0].get("quote")
    if not isinstance(quote, str) or _GENERIC_RISK_INTRODUCTION.match(quote):
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
        relationship = None
        if filings:
            filing = filings[0]
        else:
            # Reuse the exact reviewed document authorization. It permits
            # historical risks only, never inherited business or metric facts.
            predecessor = reviewed_predecessor_annual(ticker)
            if predecessor is None:
                return []
            filing, relationship = predecessor
        if filing.document_type not in {"10-K", "20-F"}:
            return []
        document = fetch_public_document(filing.url, user_agent=user_agent, publisher="SEC EDGAR",
            published_at=filing.timestamp, document_type=filing.document_type,
            source_type="regulatory_filing", source_tier="primary", sec_periodic_limits=True,
            preserve_sec_business=True, extract_tables=False)
        diagnostics = {}
        business = (extract_business_descriptions(document, ticker=ticker, cik=cik, diagnostics=diagnostics)
                    if relationship is None else [])
        if relationship is not None:
            diagnostics["status"] = "reviewed_predecessor_risk_context_only"
        (logger.info if business else logger.warning)("thesis business extraction %s: selection=%s diagnostics=%s",
                    ticker, document.text_selection, diagnostics)
        risks = []
        seen = set()
        for scope in RISK_TOPICS:
            for item in extract_issuer_risk_evidence(document, ticker=ticker,
                    question=f"What operating risk affects {scope}?", issuer_relationship=relationship):
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
