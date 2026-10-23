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
from .public_document_ingestion import fetch_public_document, PublicDocumentError
from .thesis_risk_relevance import eligible_thesis_risk_quote
from .sec_risk_sections import complete_business_window, risk_sentence_spans, business_section_label
from .reviewed_annual_layouts import reviewed_annual_layout, layout_binding
from .providers import sec_provider
from .issuer_succession import reviewed_predecessor_annual

logger = logging.getLogger(__name__)
SECTION = "Item 1. Business"
_BUSINESS_HEADING_PREFIX = re.compile(
    r"^(?:(?:Navigating challenges in advanced lithography|Company Background|Business Overview|Company Overview|Overview|General|Our Business|Our Products|Business Description|Segment Information|Business segments (?:&|and) Corporate)\s+){1,3}"
    r"(?=(?:For management reporting purposes,\s+)?[A-Z])", re.I)
_BUSINESS_ASPIRATION_OR_PROMOTION = re.compile(
    r"\b(?:committed to|focused on|seeks? to|aims? to|strives? to|intend\w*|"
    r"plan\w* to|working to|continue\w* to grow|value[- ]creating|"
    r"creating long[- ]term value|strong returns|profitably|"
    r"high[- ]quality|cost[- ]effective)\b", re.I)
_CURRENT_BUSINESS_PREDICATE = re.compile(
    r"^(?:We|Our company|The company|The firm)\s+"
    r"(?:(?:also|primarily|principally|currently|generally)\s+){0,2}"
    r"(?:designs?|manufactures?|develops?|provides?|sells?|operates?|"
    r"distributes?|delivers?|produces?|markets?|offers?|"
    r"(?:are|is) (?:a|an) (?:manufacturer|provider|producer|distributor|"
    r"operator|developer|retailer))\b|"
    r"^(?:Our company|The company|The firm)['\u2019]s\s+"
    r"(?:operations|business|(?:line|range|portfolio) of [^.]{1,100})\s+"
    r"(?:(?:are|is) (?:comprised of|organized into)|"
    r"includes?|comprises?|consists? of)\b", re.I)
_CURRENT_REVENUE_MODEL = re.compile(
    r"^(?:We|Our company|The company|The firm)\s+"
    r"(?:(?:also|primarily|principally|currently|generally)\s+){0,2}"
    r"generates? revenue (?:primarily |principally )?from\s+"
    r"(?:sales of (?:subscriptions|(?:our )?products|services)|"
    r"marketplace activities|(?:transaction|subscription|licensing|service) fees|"
    r"(?:professional (?:and other )?(?:non-subscription )?|subscription )services)\b", re.I)
# A complete passive product-channel statement still describes current business.
# Full-match a narrow channel grammar; do not admit arbitrary product prose,
# infer a segment identity, or clip promotional/forward-looking clauses.
_CURRENT_PRODUCT_DISTRIBUTION = re.compile(
    r"^(?:\ufeff\s*)?(?:Our )?Products are sold "
    r"(?:primarily |principally )?"
    r"(?:in [A-Za-z][A-Za-z ,'-]{2,100} )?"
    r"(?:directly to (?:retailers|wholesalers|customers|consumers)"
    r"(?: and (?:also )?through (?:independent )?(?:distributors|retailers|wholesalers))?"
    r"|through (?:independent )?(?:distributors|retailers|wholesalers))\.$", re.I)
_NAMED_ISSUER_ACTIVITY = re.compile(
    r"^(?P<subject>[a-z][a-z&'\u2019 .-]{1,79}?)\s+"
    r"(?:designs?|manufactures?|develops?|provides?|sells?|operates?|"
    r"distributes?|delivers?|produces?|markets?|offers?|enables?)\b", re.I)
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
_REPORTED_SEGMENT_LIST = re.compile(
    r"^Our (?:one|two|three|four|five|six|seven|eight|nine|ten) reportable segments are "
    r"[A-Z][a-z]+(?: [A-Z][a-z]+)*(?:, (?:and )?[A-Z][a-z]+(?: [A-Z][a-z]+)*)+\.$")
# Complete, explicitly named segment + one source-spelled legal organization.
# This reports composition only; it does not resolve a subsidiary to the issuer
# or infer products, ownership, consolidation, revenue or relative importance.
_NAMED_SEGMENT_COMPOSITION = re.compile(
    r'^(?:\ufeff\s*)*The (?P<label>[A-Z][A-Za-z]*(?:(?: |/|-| & )[A-Za-z]+){0,5}) segment '
    r'(?:is (?:currently )?comprised of|consists of|comprises) '
    r'(?P<component>[A-Z][A-Za-z\x27\u2019&-]*(?: [A-Z][A-Za-z\x27\u2019&-]*){0,7},? '
    r'(?:Inc\.|Corporation|Corp\.|LLC|Ltd\.))'
    # A suffix period can also terminate the sentence. An alias needs its own
    # terminal period; unpunctuated Corporation/LLC suffixes need one as well.
    r'(?: \("[A-Z][A-Za-z&-]{0,39}"\)\.|(?<=[A-Za-z])\.|(?<=\.))$')


def _segment_business_scope(quote):
    match = _NAMED_SEGMENT_COMPOSITION.fullmatch(quote)
    return {'kind': 'named_segment', 'label': match['label']} if match else None


_INTERNAL_EMPLOYEE_ACTIVITY = re.compile(
    r"\b(?:for|to)\s+our\s+(?:employees|staff|workforce)\b|"
    r"^(?:We|Our company|The company|The firm)\s+"
    r"(?:(?:also|primarily|principally|currently|generally)\s+){0,2}"
    r"offers?\s+(?:our\s+)?(?:employees|staff|workforce)\s+"
    r"(?:(?:a|an|the)\s+(?:[a-z-]+\s+){0,3})?"
    r"(?:package of benefits|benefits|healthcare|stipends)\b|"
    r"\b(?:skills|professional|career) development across our "
    r"(?:organization|workforce)\b", re.I)
_INTERNAL_HOSTING_ACTIVITY = re.compile(
    r"\b(?:migrate|host|run) our (?:production|internal) "
    r"(?:services|systems|applications)\b", re.I)



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


def _business_quote(quote, *, ticker=None, cik=None):
    reason = _business_quote_rejection(quote)
    return reason is None or (reason == "subject_or_activity"
                             and _named_issuer_quote(quote, ticker=ticker, cik=cik))


def _named_issuer_quote(quote, *, ticker, cik):
    """A named subject requires exact current directory identity, never an alias guess."""
    match = _NAMED_ISSUER_ACTIVITY.match(quote)
    if not match or not quote.endswith(".") or not ticker or not isinstance(cik, str) or not cik.isdigit():
        return False
    from . import issuer_identity
    try:
        issuer = issuer_identity._load_directory().symbols.get(ticker)
        return bool(issuer and int(issuer.cik) == int(cik)
                    and issuer_identity.name_key(match['subject']) == issuer_identity.name_key(issuer.name))
    except Exception:
        return False


def _bare_segment_list(quote):
    """Recognize only segment predicates whose objects are bare acronyms."""
    for clause in re.split(r",\s+and\s+", quote[:-1], flags=re.I):
        predicate = _CURRENT_SEGMENT_STRUCTURE.match(clause)
        if not predicate or not re.fullmatch(
                r"[A-Z]{2,8}(?:,\s*[A-Z]{2,8})*(?:\s+and\s+[A-Z]{2,8})?",
                clause[predicate.end():]):
            return False
    return True


def _customer_purpose_activity(quote):
    # Retain the complete sentence; this lead identifies customers and does
    # not authorize strategy, belief or forecast clauses as current activity.
    lead = re.match(r"^To help our customers [^.;]{1,100},\s+", quote, re.I)
    return bool(lead and _CURRENT_BUSINESS_PREDICATE.match(quote[lead.end():]))


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
    if _INTERNAL_HOSTING_ACTIVITY.search(quote):
        return "internal_hosting_activity"
    # Activity words in a strategy, belief or potential project are not a
    # current operating predicate. Require the main subject to state the
    # activity, current business role, segment structure or product range.
    if (not (_CURRENT_BUSINESS_PREDICATE.match(quote)
             or _customer_purpose_activity(quote)
             or _CURRENT_REVENUE_MODEL.match(quote)
             or _CURRENT_PRODUCT_DISTRIBUTION.fullmatch(quote)
             or _CURRENT_SEGMENT_STRUCTURE.match(quote)
             or _NAMED_SEGMENT_COMPOSITION.fullmatch(quote)
             or _REPORTED_SEGMENT_LIST.fullmatch(quote)
             or _NAMED_SEGMENT_STRUCTURE.match(quote))
            or not quote.endswith(".")):
        return "subject_or_activity"
    return None


def _business_summary(value):
    return (f'{value["ticker"]} described its business in its {value.get("document_type", "10-K")} filed '
            f'{value["document_ref"]["published_at"]}: “{value["quote"]}” '
            + ('This is issuer-reported composition of the named segment only; operating activities, '
               'ownership, revenue contribution and segment economics are not established by this statement; '
               if value.get('business_scope') else 'This is an issuer description; ')
            + 'competitive advantage and future performance remain unverified.')


def extract_business_descriptions(document, *, ticker, cik, diagnostics=None):
    stats = diagnostics if diagnostics is not None else {}
    stats.update(status="document_ineligible", sentences=0, heading_prefixes_removed=0,
                 extracted_descriptions=0, rejection_counts={})
    if (document.document_type not in {"10-K", "20-F", "10-Q"} or document.publisher != "SEC EDGAR"
            or document.source_type != "regulatory_filing" or document.source_tier != "primary"
            or document.extraction_method != "html" or not document.text_ready
            or not _business_issuer_url(document.final_url, cik)):
        return []
    try:
        if date.fromisoformat(document.published_at or "") > date.today():
            return []
    except (TypeError, ValueError):
        return []
    layout = reviewed_annual_layout(document.final_url, document.document_type, document.published_at,
        content_hash=document.content_hash, canonical_content_hash=document.canonical_content_hash, cik=cik)
    section = business_section_label(document.document_type, layout)
    if layout and layout.get("business_mapping") not in document.text:
        # The mapping can be outside a selected text window; ingestion verifies
        # the full-text mapping before truncation and the canonical hash binds it.
        if not document.canonical_content_hash or document.canonical_content_hash != layout['canonical_content_hash']:
            return []
    window = complete_business_window(document.text, form=document.document_type, layout=layout)
    stats["status"] = "no_complete_business_section"
    if not window:
        return []
    start, end = window
    stats["status"] = "no_qualifying_business_sentence"
    candidates = []
    named_offsets = set()
    for left, right in islice(risk_sentence_spans(document.text[start:end]), 2000):
        quote = document.text[start + left:start + right]
        stats["sentences"] += 1
        # Normalized HTML joins block headings to the next sentence. Remove
        # only an explicit shared heading prefix; retain the entire sentence.
        heading = _BUSINESS_HEADING_PREFIX.match(quote)
        after_heading = quote[heading.end():] if heading else ""
        if heading and (re.match(r"(?:For management reporting purposes,\s+)?(?:We|Our company|The company|The firm)\b", after_heading, re.I)
                        or _customer_purpose_activity(after_heading)
                        or _named_issuer_quote(after_heading, ticker=ticker, cik=cik)):
            left += heading.end()
            quote = document.text[start + left:start + right]
            stats["heading_prefixes_removed"] += 1
        reason = _business_quote_rejection(quote)
        if reason == "subject_or_activity" and _named_issuer_quote(quote, ticker=ticker, cik=cik):
            reason = None
            named_offsets.add(start + left)
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
    candidates.sort(key=lambda row: (-1 if row[0] in named_offsets else
                                    2 if _CURRENT_SEGMENT_STRUCTURE.match(row[1])
                                    else 1 if (_NAMED_SEGMENT_STRUCTURE.match(row[1])
                                               or _NAMED_SEGMENT_COMPOSITION.fullmatch(row[1])) else 0,
                                    row[0]))
    result = []
    from .business_context import complementary_candidates
    for offset, quote in complementary_candidates(candidates):
        try:
            ref = ClaimDocumentReference(reference_id=f"document:{document.content_hash}:business:{offset}",
                title=document.title or f"{ticker} {document.document_type}", provider="SEC EDGAR", url=document.final_url,
                published_at=document.published_at, section=section,
                content_hash=document.content_hash, quote=quote).to_dict()
        except (TypeError, ValueError):
            return []
        value = dict(claim_kind="issuer_business_description", ticker=ticker, quote=quote,
                     start_offset=offset, end_offset=offset + len(quote), document_ref=ref)
        scope = _segment_business_scope(quote)
        if scope:
            value['business_scope'] = scope
        if document.document_type != "10-K":
            value["document_type"] = document.document_type
        if layout:
            value["reviewed_layout"] = layout_binding(layout, document.content_hash)
        result.append(RetrievedEvidence(title=f"{ticker} business description · {document.published_at} · {len(result)+1}",
            source="SEC EDGAR", summary=_business_summary(value), timestamp=document.published_at,
            url=document.final_url, relevance_score=0.96, source_type="regulatory_filing",
            source_tier="primary", claim_type="reported_fact", document_type=document.document_type,
            filed_at=document.published_at, section=section, extraction_method="html",
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
        binding = value.get("reviewed_layout")
        if binding is not None and (not isinstance(binding, dict)
                or binding.get("raw_content_hash") != ref.get("content_hash")):
            return None
        layout = reviewed_annual_layout(item.url, item.document_type, item.timestamp,
            content_hash=ref.get("content_hash"),
            canonical_content_hash=binding.get("canonical_content_hash") if binding else None, cik=cik)
        if (layout is not None and binding is None) or (binding is not None and (
                not layout or binding != layout_binding(layout, ref.get("content_hash")))):
            return None
        section = business_section_label(item.document_type, layout)
        if (value.get("claim_kind") != "issuer_business_description" or value.get("ticker") != ticker
                or value.get('business_scope') != _segment_business_scope(value.get('quote', ''))
                or not _business_quote(value.get("quote"), ticker=ticker, cik=cik) or value["quote"] != ref.get("quote")
                or ref.get("provider") != "SEC EDGAR" or ref.get("section") != section
                or not ref.get("content_hash") or not _business_issuer_url(ref["url"], cik)
                or ref["url"] != item.url or ref.get("published_at") != item.timestamp
                or date.fromisoformat(item.timestamp) > date.today()
                or type(start) is not int or type(end) is not int or start < 0 or end - start != len(value["quote"])
                or ref["reference_id"] != f'document:{ref["content_hash"]}:business:{start}'
                or item.source != "SEC EDGAR" or item.source_type != "regulatory_filing"
                or item.source_tier != "primary" or item.claim_type != "reported_fact"
                or item.document_type not in {"10-K", "20-F", "10-Q"} or value.get("document_type", "10-K") != item.document_type or item.section != section or item.extraction_method != "html"
                or item.availability_status != 'available'
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
    # A transition word does not resolve which actions or measures failed.
    # Withhold this standalone sample instead of inventing the missing context.
    if not eligible_thesis_risk_quote(quote):
        return None
    return bound_issuer_risk(item, ticker=ticker, question=f"What operating risk affects {scope}?")


def fetch_thesis_disclosures(ticker, *, question, user_agent=""):
    # Structured status/counts only; never persist prose, URLs or exception text.
    stats = {"stage": "eligibility", "status": "not_requested"}
    items = _fetch_thesis_disclosures(ticker, question=question, user_agent=user_agent,
                                     stats=stats)
    stats.update(business_count=sum(bool(item.business_disclosures) for item in items),
                 competition_count=sum(bool(getattr(item, 'competition_disclosures', [])) for item in items),
                 segment_context_count=sum(bool(item.segment_disclosures) for item in items),
                 operating_context_count=sum(bool(item.operating_disclosures) for item in items),
                 risk_count=sum(bool(item.risk_disclosures) for item in items))
    logger.info("thesis disclosure retrieval diagnostic",
                extra={"thesis_disclosure_diagnostics": stats})
    return items


def _fetch_thesis_disclosures(ticker, *, question, user_agent, stats):
    """Annual context, or one current quarter plus authorized historical risks."""
    if not requests_thesis_disclosures(ticker, question):
        return []
    quarterly_business = []
    try:
        stats.update(stage="identity", status="identity_unavailable")
        cik = sec_provider._load_ticker_cik_map().get(ticker)
        if not cik:
            return []
        stats.update(stage="annual_discovery", status="annual_metadata_absent")
        filings = sec_provider.fetch_recent_filings(ticker, forms=["10-K", "20-F"],
            limit=1, years_back=2, prefer_results=False) or []
        relationship = None
        if filings:
            filing = filings[0]
        else:
            stats.update(stage="quarterly_discovery", status="annual_metadata_absent")
            # Current issuer context must come from its own filing, never an
            # inherited predecessor description. One bounded quarterly attempt.
            quarters = sec_provider.fetch_recent_filings(ticker, forms=["10-Q"],
                limit=1, years_back=2, prefer_results=False) or []
            if quarters and quarters[0].document_type == "10-Q":
                quarter = quarters[0]
                try:
                    stats["stage"] = "quarterly_document"
                    quarterly_document = fetch_public_document(quarter.url, user_agent=user_agent,
                        publisher="SEC EDGAR", published_at=quarter.timestamp, document_type="10-Q",
                        source_type="regulatory_filing", source_tier="primary", sec_periodic_limits=True,
                        preserve_sec_business=True, extract_tables=False)
                    quarterly_business = extract_business_descriptions(quarterly_document,
                        ticker=ticker, cik=cik)
                except Exception as exc:
                    stats["status"] = "quarterly_document_unavailable"
                    logger.warning("quarterly business context unavailable for %s: %s", ticker, type(exc).__name__)
            # Reuse the exact reviewed document authorization. It permits
            # historical risks only, never inherited business or metric facts.
            predecessor = reviewed_predecessor_annual(ticker)
            if predecessor is None:
                return quarterly_business
            filing, relationship = predecessor
        if filing.document_type not in {"10-K", "20-F"}:
            stats["status"] = "unsupported_form"
            return []
        stats.update(stage="annual_document", status="document_unavailable")
        document = fetch_public_document(filing.url, user_agent=user_agent, publisher="SEC EDGAR",
            published_at=filing.timestamp, document_type=filing.document_type,
            source_type="regulatory_filing", source_tier="primary", sec_periodic_limits=True,
            preserve_sec_business=True, extract_tables=False,
            segment_fact_cik=cik if relationship is None else None)
        diagnostics = {}
        stats.update(stage="extraction", status="extraction_complete")
        business = (extract_business_descriptions(document, ticker=ticker, cik=cik, diagnostics=diagnostics)
                    if relationship is None else [])
        stats["business_extraction"] = diagnostics
        from .thesis_competition import extract_competition_descriptions
        competition = (extract_competition_descriptions(document, ticker=ticker, cik=cik)
                       if relationship is None else [])
        from .segment_order_context import extract_order_context
        orders = (extract_order_context(document, ticker=ticker, cik=cik)
                  if relationship is None else [])
        from .segment_financial_context import extract_segment_financial_context
        segments = (extract_segment_financial_context(document, ticker=ticker, cik=cik)
                    if relationship is None else [])
        from .segment_product_context import extract_segment_products
        products = (extract_segment_products(document, ticker=ticker, cik=cik)
                    if relationship is None else [])
        from .segment_organisation_context import extract_organisation_activities
        organisations = (extract_organisation_activities(document, ticker=ticker, cik=cik)
                         if relationship is None else [])
        from .deposit_impairment_context import extract_deposit_impairment
        impairments = (extract_deposit_impairment(document, ticker=ticker, cik=cik)
                       if relationship is None else [])
        if relationship is not None:
            diagnostics["status"] = "reviewed_predecessor_risk_context_only"
        (logger.info if business else logger.warning)("thesis business extraction %s: selection=%s diagnostics=%s",
                    ticker, document.text_selection, diagnostics)
        risks = []
        seen = set()
        for scope in RISK_TOPICS:
            for item in extract_issuer_risk_evidence(document, ticker=ticker,
                    question=f"What operating risk affects {scope}?", issuer_relationship=relationship,
                    broad_thesis=True):
                value = bound_thesis_risk(item, ticker=ticker)
                if value and value["quote"] not in seen:
                    seen.add(value["quote"])
                    risks.append(item)
        # Source order, never an assertion that these are the most material risks.
        risks.sort(key=lambda item: item.risk_disclosures[0]["start_offset"])
        return (quarterly_business + business)[:2] + competition + risks[:2] + orders + segments + products + organisations + impairments
    except Exception as exc:
        stats["status"] = "document_error" if isinstance(exc, PublicDocumentError) else "retrieval_or_extraction_error"
        if isinstance(exc, PublicDocumentError):
            stats["document_failure_kind"] = exc.failure_kind
            stats["http_status"] = exc.http_status
        logger.warning("thesis disclosures unavailable for %s: %s", ticker, type(exc).__name__)
        return quarterly_business
