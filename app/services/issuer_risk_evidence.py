"""Bounded, topic-specific issuer disclosures from SEC Risk Factors.

A quoted disclosure preserves the issuer's reported events and potential risks.
It does not independently establish occurrence, impact or a thesis change.
"""
from __future__ import annotations

from datetime import date
from dataclasses import dataclass
import re
from urllib.parse import urlsplit

from ..integrity.provenance import ClaimDocumentReference
from ..schemas import RetrievedEvidence
from .public_document_ingestion import PublicDocument
from .sec_risk_sections import (
    RISK_START as _START, MAX_ISSUER_RISK_SECTION_CHARS,
    rejected_risk_heading, find_risk_closing,
)

_SCOPE = re.compile(r"\b(?:services|app store|icloud|apple music|digital content)\b", re.I)
_POSSIBILITY = re.compile(r"\b(?:may|could|can|might)\b", re.I)
_ADVERSE = re.compile(r"\b(?:adverse|adversely|harm|loss|lost|reduce|reduced|decline|disrupt(?:ion|ions|ed|s|ing)?|unable|cease|fail|shortage|damage|suffer|delay|constraints?|shortfalls?|insufficient)\b", re.I)
_NON_TOPIC_PREFIX = re.compile(r"\bnon[\s\-‐‑‒–—]*$", re.I)


@dataclass(frozen=True)
class IssuerRiskProfile:
    cik: str
    scope: str
    terms: re.Pattern


# Compatibility profiles for the previously reviewed issuer/topic slices.
RISK_PROFILES = {
    "AAPL": IssuerRiskProfile("320193", "Services", _SCOPE),
    "MSFT": IssuerRiskProfile("789019", "Cloud", re.compile(r"\b(?:azure|cloud(?:-based)?)\b", re.I)),
    "NVDA": IssuerRiskProfile("1045810", "Data Center", re.compile(r"\b(?:data[\s\-‐‑‒–—]*centers?|AI[\s\-‐‑‒–—]+infrastructure)\b", re.I)),
    "DOCU": IssuerRiskProfile("1261333", "Subscription renewals", re.compile(r"\b(?:subscriptions?|renew(?:al|als|s)?|retention)\b", re.I)),
}

# Topic rules are shared across issuers. Identity must still come from an exact
# SEC directory entry; adding a security no longer requires a code change.
# Narrow phrases avoid treating every mention of customers, demand, facilities
# or products as support for a specific mechanism in the question.
RISK_TOPICS = {
    "Cloud": r"\b(?:azure|cloud(?:-based)?)\b",
    "Data Center": r"\b(?:data[\s\-‐‑‒–—]*centers?|AI[\s\-‐‑‒–—]+infrastructure)\b",
    "Subscription renewals": r"\b(?:subscriptions?|renew(?:al|als|s)?|customer retention|retention rates?)\b",
    "Staffing demand": r"\b(?:staffing|recruit(?:ing|ment)|temporary (?:workers|employment)|contingent work(?:ers|force))\b",
    "Energy supply": r"\b(?:energy|electricity|power (?:supply|supplies|costs?|prices?|contracts?|outages?))\b",
    "Patient safety": r"\b(?:patient safety|facility safety|quality of care|patient care|medical malpractice|patient injuries)\b",
    "Customer concentration": r"\b(?:customer concentration|concentrat\w*[^.!?]{0,50}customers?|(?:single|largest|major|significant|limited number of|small number of) customers?)\b",
    "Distribution": r"\b(?:distribution|distributors?|resellers?|channel partners?)\b",
    "Supply chain": r"\b(?:supply[ -]chain|suppliers?|raw materials?|components? supply)\b",
    "Cybersecurity": r"\b(?:cyber\w*|data breaches?|security breaches?|ransomware)\b",
    "Credit losses": r"\b(?:credit losses?|loan losses?|defaults?|nonperforming loans?|borrower\w*)\b",
    "Liquidity": r"\b(?:liquidity|refinancing|debt maturit\w*|funding access)\b",
    "Interest rates": r"\b(?:interest rates?|net interest (?:income|margin))\b",
    "Drug development": r"\b(?:clinical trials?|drug development|regulatory approval|FDA approval)\b",
    "Patents": r"\b(?:patents?|patent expir\w*|intellectual property)\b",
    "Membership renewals": r"\b(?:memberships?|member renewal\w*)\b",
    "Marketplace sellers": r"\b(?:sellers?|merchants?|marketplace)\b",
    "Commodity prices": r"\b(?:commodity prices?|oil prices?|gas prices?|aluminum prices?|alumina prices?)\b",
    "Occupancy": r"\b(?:occupancy|hotel demand|room demand|RevPAR)\b",
    "Production quality": r"\b(?:production quality|product defects?|product quality|aircraft safety|quality control)\b",
    "Export controls": r"\b(?:export controls?|export restrictions?|export licens\w*|sanctions?)\b",
    "Government contracts": r"\b(?:government contracts?|government customers?|government spending|defen[cs]e spending)\b",
}
_TOPICS = {scope: re.compile(terms, re.I) for scope, terms in RISK_TOPICS.items()}
_RISK_QUESTION = re.compile(r"\b(?:risks?|invalidate(?:s|d)?|invalidating)\b", re.I)


def _without_issuer_name(ticker: str, question: str, issuer_name: str | None) -> str:
    """Remove only a verified possessive name span; retain earlier topics.

    Passive cache access keeps topic selection free of network I/O. This does
    not authorize identity: extraction/binding still requires the current CIK.
    """
    from . import issuer_identity
    if not issuer_name:
        cache = issuer_identity._cache
        issuer = cache.symbols.get(issuer_identity.symbol(ticker)) if cache else None
        issuer_name = issuer.name if issuer else None
    if not issuer_name:
        return question
    expected = issuer_identity.name_key(issuer_name)
    spans = []
    for possessive in re.finditer(r"['’](?:s)?(?=\s)", question):
        prefix = question[:possessive.start()]
        words = list(re.finditer(r"[A-Za-z0-9]+", prefix))[-12:]
        for word in words:
            if issuer_identity.name_key(prefix[word.start():]) == expected:
                spans.append((word.start(), possessive.end()))
                break
    for start, end in reversed(spans):
        question = question[:start] + " " + question[end:]
    return question


def requested_risk_topic(ticker: str, question: str, *, issuer_name: str | None = None) -> tuple[str, re.Pattern] | None:
    """Select an explicit topic without network I/O or guessing an issuer.

    Multiple requested topics are withheld until per-topic completeness can be
    represented. The legacy reviewed topics retain their original wording.
    """
    if not _RISK_QUESTION.search(question or ""):
        return None
    # Topic words inside a possessive company name (e.g. Liquidity Services,
    # Inc.'s marketplace sellers) are identity, not another requested topic.
    topic_text = _without_issuer_name(ticker, question or "", issuer_name)
    legacy = RISK_PROFILES.get(str(ticker).strip().upper())
    matches = [(scope, terms) for scope, terms in _TOPICS.items()
               if _has_topic_scope(topic_text, IssuerRiskProfile("", scope, terms))]
    if legacy and _has_topic_scope(topic_text, legacy):
        matches = [(scope, terms) for scope, terms in matches if scope != legacy.scope]
        # Membership renewals must not be mistaken for software subscriptions.
        if legacy.scope == "Subscription renewals" and any(s == "Membership renewals" for s, _ in matches):
            return None
        matches.insert(0, (legacy.scope, legacy.terms))
    # Explicit membership renewal wording overlaps with the subscription rule;
    # prefer the more specific membership topic.
    if any(scope == "Membership renewals" for scope, _ in matches):
        matches = [(scope, terms) for scope, terms in matches if scope != "Subscription renewals"]
    return matches[0] if len(matches) == 1 else None


def _has_topic_scope(text: str, profile: IssuerRiskProfile) -> bool:
    """A non-topic mention alone cannot establish the requested business scope."""
    return any(not _NON_TOPIC_PREFIX.search(text[:match.start()])
               for match in profile.terms.finditer(text))


def requested_risk_profile(ticker: str, question: str) -> IssuerRiskProfile | None:
    if not _RISK_QUESTION.search(question or ""):
        return None
    ticker = str(ticker).strip().upper()
    legacy = RISK_PROFILES.get(ticker)
    issuer_name = None
    if legacy:
        cik = legacy.cik
    else:
        # Do not load identity for questions without any recognized topic.
        if not any(_has_topic_scope(question or "", IssuerRiskProfile("", scope, terms))
                   for scope, terms in _TOPICS.items()):
            return None
        from .issuer_identity import _load_directory, symbol
        issuer = _load_directory().symbols.get(symbol(ticker))
        if issuer is None:
            return None
        cik = str(int(issuer.cik))
        issuer_name = issuer.name
    topic = requested_risk_topic(ticker, question, issuer_name=issuer_name)
    return IssuerRiskProfile(cik, *topic) if topic else None


def risk_quote_rejections(quote: str, profile: IssuerRiskProfile) -> tuple[str, ...]:
    """Stable reason codes for the existing admission rules; never source prose."""
    max_chars = 300 if profile.scope == "Services" else 900
    checks = (
        ("length", 40 <= len(quote) <= max_chars),
        ("sentence_start", bool(re.match(r"[A-Z]", quote))),
        ("sentence_end", bool(quote) and quote[-1] in ".!?"),
        ("numeric_content", not re.search(r"\d|[$%]", quote)),
        ("topic_scope", _has_topic_scope(quote, profile)),
        ("possibility_language", bool(_POSSIBILITY.search(quote))),
        ("adverse_mechanism", bool(_ADVERSE.search(quote))),
        ("generic_products_and_services", not re.search(r"\bproducts and services\b", quote, re.I)),
        ("unresolved_reference", not re.match(r"(?:this|these|that|those|it|they|such)\b", quote, re.I)),
        ("cross_reference_or_instruction", not re.search(
            r"\b(?:see|refer to|no material changes|ignore|instructions?|system prompt)\b", quote, re.I)),
    )
    return tuple(reason for reason, passed in checks if not passed)


def _qualifying_quote(quote: str, profile: IssuerRiskProfile) -> bool:
    return not risk_quote_rejections(quote, profile)


def _issuer_url(url: str, profile: IssuerRiskProfile) -> bool:
    if not isinstance(url, str):
        return False
    try:
        parsed = urlsplit(url)
        return bool(parsed.scheme == "https" and parsed.hostname == "www.sec.gov"
                    and not (parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment)
                    and re.fullmatch(rf"/Archives/edgar/data/{profile.cik}/\d{{18}}/[^/]+\.html?", parsed.path)
                    and not any(ord(c) < 33 or c == "\\" for c in url))
    except (TypeError, ValueError):
        return False


def extract_issuer_risk_evidence(document: PublicDocument, *, ticker: str,
                                 question: str, diagnostics: dict | None = None) -> list[RetrievedEvidence]:
    """Extract at most two complete, nonnumeric risk sentences; no model calls.

    Coverage is limited to explicit supported topics and 10-K/10-Q sections.
    TOCs, cross-references, other sections, unsupported issuers and ambiguous
    or overlong sentences produce no claim. Never truncate a risk sentence.
    """
    ticker = str(ticker).strip().upper()
    profile = requested_risk_profile(ticker, question)
    # Counts only: never export source prose, questions, headers or credentials.
    stats = diagnostics if diagnostics is not None else {}
    stats.update(status="document_ineligible", risk_headings=0, complete_sections=0,
                 rejected_heading_prefixes=0, missing_closing_sections=0,
                 oversized_sections=0, sentences=0, topic_sentences=0,
                 qualifying_sentences=0, extracted_disclosures=0,
                 topic_rejection_counts={}, scan_stopped_at_limit=False)
    if (not profile or not _issuer_url(document.final_url, profile)
            or not document.text_ready or document.extraction_method != "html"
            or document.source_type != "regulatory_filing" or document.source_tier != "primary"
            or document.publisher != "SEC EDGAR"
            or document.document_type not in {"10-K", "10-K/A", "10-Q", "10-Q/A"}
            or not isinstance(document.content_hash, str)
            or not re.fullmatch(r"[0-9a-f]{64}", document.content_hash)):
        return []
    try:
        filed = date.fromisoformat(document.published_at or "")
    except (TypeError, ValueError):
        return []
    if filed > date.today():
        return []
    stats["status"] = "no_qualifying_risk"
    results: list[RetrievedEvidence] = []
    seen: set[str] = set()
    text = document.text
    for heading in _START.finditer(text):
        stats["risk_headings"] += 1
        # Exclude TOC page numbers and quoted/cross-referenced headings. A
        # reference to Risk Factors is not the start of that section.
        if rejected_risk_heading(text, heading.end(), start=heading.start()):
            stats["rejected_heading_prefixes"] += 1
            continue
        end = find_risk_closing(text, heading.end())
        # An explicit closing section is required; truncated text fails closed.
        section_limit = 80_000 if ticker == "AAPL" else MAX_ISSUER_RISK_SECTION_CHARS
        if end is None:
            stats["missing_closing_sections"] += 1
            continue
        if end.start() - heading.end() > section_limit:
            stats["oversized_sections"] += 1
            continue
        stats["complete_sections"] += 1
        section = text[heading.end():end.start()]
        for sentence in re.finditer(r"(?:^|(?<=[.!?])\s+)([^.!?]+[.!?])", section):
            quote = sentence.group(1).strip()
            stats["sentences"] += 1
            is_topic = _has_topic_scope(quote, profile)
            stats["topic_sentences"] += int(is_topic)
            reasons = risk_quote_rejections(quote, profile)
            if is_topic:
                for reason in reasons:
                    counts = stats["topic_rejection_counts"]
                    counts[reason] = counts.get(reason, 0) + 1
            if reasons or quote in seen:
                continue
            stats["qualifying_sentences"] += 1
            offset = heading.end() + sentence.start(1)
            # Retain the exact normalized-document span, not a generated paraphrase.
            offset += len(sentence.group(1)) - len(sentence.group(1).lstrip())
            reference = ClaimDocumentReference(
                reference_id=f"document:{document.content_hash}:risk:{offset}",
                title=document.title or f"{ticker} {document.document_type}", provider="SEC EDGAR",
                url=document.final_url, published_at=document.published_at,
                section="Item 1A. Risk Factors", content_hash=document.content_hash, quote=quote,
            ).to_dict()
            disclosure = {"claim_kind": "issuer_disclosed_risk", "ticker": ticker, "scope": profile.scope,
                          "quote": quote, "start_offset": offset, "end_offset": offset + len(quote),
                          "document_ref": reference}
            results.append(RetrievedEvidence(
                title=f"{ticker} {profile.scope} risk disclosure · {filed} · {len(results) + 1}",
                source="SEC EDGAR", summary=risk_summary(disclosure, document.document_type),
                timestamp=document.published_at, url=document.final_url, relevance_score=0.97,
                source_type="regulatory_filing", source_tier="primary", claim_type="reported_fact",
                document_type=document.document_type, filed_at=document.published_at,
                section="Item 1A. Risk Factors", extraction_method="html",
                risk_disclosures=[disclosure],
            ))
            seen.add(quote)
            stats.update(status="risk_extracted", extracted_disclosures=len(results))
            if len(results) == 2:
                stats["scan_stopped_at_limit"] = True
                return results
    return results


def risk_summary(disclosure: dict, form: str) -> str:
    filed = disclosure["document_ref"]["published_at"]
    return (f'{disclosure["ticker"]} disclosed in its {form} filed {filed}: “{disclosure["quote"]}” '
            "This is an issuer disclosure, not an independent assessment of whether the "
            "described effects occurred or will occur, or of their financial impact.")


def bound_issuer_risk(item: object, *, ticker: str, question: str) -> dict | None:
    """Accept only producer-bound disclosures matching their admitted source item."""
    disclosures = getattr(item, "risk_disclosures", [])
    profile = requested_risk_profile(ticker, question)
    if (not profile or not isinstance(disclosures, list) or len(disclosures) != 1
            or getattr(item, "source", None) != "SEC EDGAR"
            or getattr(item, "source_tier", None) != "primary"
            or getattr(item, "source_type", None) != "regulatory_filing"
            or getattr(item, "claim_type", None) != "reported_fact"
            or getattr(item, "section", None) != "Item 1A. Risk Factors"
            or getattr(item, "extraction_method", None) != "html"
            or getattr(item, "freshness_status", None) in {"unavailable", "conflicting", "superseded"}):
        return None
    value = disclosures[0]
    if not isinstance(value, dict):
        return None
    ref = value.get("document_ref")
    if not isinstance(ref, dict):
        return None
    try:
        ref = ClaimDocumentReference(**ref).to_dict()
        if date.fromisoformat(ref.get("published_at") or "") > date.today():
            return None
    except (TypeError, ValueError, AttributeError):
        return None
    quote = value.get("quote")
    start, end = value.get("start_offset"), value.get("end_offset")
    if (value.get("claim_kind") != "issuer_disclosed_risk" or value.get("ticker") != ticker
            or value.get("scope") != profile.scope or not isinstance(quote, str)
            or not _qualifying_quote(quote, profile) or quote != ref.get("quote")
            or ref.get("section") != "Item 1A. Risk Factors" or not ref.get("content_hash")
            or ref.get("provider") != "SEC EDGAR" or not _issuer_url(ref["url"], profile)
            or ref["url"] != getattr(item, "url", None)
            or ref["published_at"] != getattr(item, "timestamp", None)
            or type(start) is not int or type(end) is not int or start < 0 or end - start != len(quote)
            or ref["reference_id"] != f'document:{ref["content_hash"]}:risk:{start}'
            or getattr(item, "document_type", None) not in {"10-K", "10-K/A", "10-Q", "10-Q/A"}
            or getattr(item, "summary", None) != risk_summary(value, getattr(item, "document_type"))):
        return None
    return value
