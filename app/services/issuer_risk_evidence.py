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

_START = re.compile(r"\bItem\s+1A\s*[.:—–-]?\s*Ris\s*k\s+Factors\b", re.I)
_END = re.compile(r"\bItem\s+(?:1B|1C|2)\s*[.:—–-]?\s+(?:Unresolve\s*d|Cy\s*bersecurity|Properties|Legal|Unregistered)\b", re.I)
_SCOPE = re.compile(r"\b(?:services|app store|icloud|apple music|digital content)\b", re.I)
_POSSIBILITY = re.compile(r"\b(?:may|could|can|might)\b", re.I)
_ADVERSE = re.compile(r"\b(?:adverse|adversely|harm|loss|lost|reduce|reduced|decline|disrupt|unable|cease|fail|shortage|damage|suffer|delay|constraints?|shortfalls?|insufficient)\b", re.I)
_NON_TOPIC_PREFIX = re.compile(r"\bnon[\s\-‐‑‒–—]*$", re.I)


@dataclass(frozen=True)
class RiskProfile:
    cik: str
    scope: str
    terms: re.Pattern


# Reviewed issuer identities and explicit business topics. This registry is
# coverage, not a claim of universal risk extraction or impact assessment.
RISK_PROFILES = {
    "AAPL": RiskProfile("320193", "Services", _SCOPE),
    "MSFT": RiskProfile("789019", "Cloud", re.compile(r"\b(?:azure|cloud(?:-based)?)\b", re.I)),
    "NVDA": RiskProfile("1045810", "Data Center", re.compile(r"\b(?:data[\s\-‐‑‒–—]*centers?|AI[\s\-‐‑‒–—]+infrastructure)\b", re.I)),
    "DOCU": RiskProfile("1261333", "Subscription renewals", re.compile(r"\b(?:subscriptions?|renew(?:al|als|s)?|retention)\b", re.I)),
}


def _has_topic_scope(text: str, profile: RiskProfile) -> bool:
    """A non-topic mention alone cannot establish the requested business scope."""
    return any(not _NON_TOPIC_PREFIX.search(text[:match.start()])
               for match in profile.terms.finditer(text))


def requested_risk_profile(ticker: str, question: str) -> RiskProfile | None:
    profile = RISK_PROFILES.get(str(ticker).strip().upper())
    if (profile and _has_topic_scope(question or "", profile)
            and re.search(r"\b(?:risks?|invalidate|invalidating)\b", question or "", re.I)):
        return profile
    return None


def _qualifying_quote(quote: str, profile: RiskProfile) -> bool:
    return bool(40 <= len(quote) <= 300 and re.match(r"[A-Z]", quote)
                and quote[-1] in ".!?" and not re.search(r"\d|[$%]", quote)
                and _has_topic_scope(quote, profile) and _POSSIBILITY.search(quote)
                and _ADVERSE.search(quote)
                # Generic company-wide product/service warnings do not establish
                # a topic-specific operating mechanism for this evidence view.
                and not re.search(r"\bproducts and services\b", quote, re.I)
                and not re.match(r"(?:this|these|that|those|it|they|such)\b", quote, re.I)
                and not re.search(r"\b(?:see|refer to|no material changes|ignore|instructions?|system prompt)\b", quote, re.I))


def _issuer_url(url: str, profile: RiskProfile) -> bool:
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
                                 question: str) -> list[RetrievedEvidence]:
    """Extract at most two complete, nonnumeric risk sentences; no model calls.

    Coverage is limited to reviewed issuer/topic pairs and 10-K/10-Q sections.
    TOCs, cross-references, other sections, unsupported issuers and ambiguous
    or overlong sentences produce no claim. Never truncate a risk sentence.
    """
    ticker = str(ticker).strip().upper()
    profile = requested_risk_profile(ticker, question)
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
    results: list[RetrievedEvidence] = []
    seen: set[str] = set()
    text = document.text
    for heading in _START.finditer(text):
        # Exclude TOC page numbers and quoted/cross-referenced headings. A
        # reference to Risk Factors is not the start of that section.
        if re.match(r'[\d"”\u2013\u2014-]', text[heading.end():].lstrip()):
            continue
        end = _END.search(text, heading.end())
        # An explicit closing section is required; truncated text fails closed.
        section_limit = 80_000 if ticker == "AAPL" else 160_000
        if end is None or end.start() - heading.end() > section_limit:
            continue
        section = text[heading.end():end.start()]
        for sentence in re.finditer(r"(?:^|(?<=[.!?])\s+)([^.!?]+[.!?])", section):
            quote = sentence.group(1).strip()
            if not _qualifying_quote(quote, profile) or quote in seen:
                continue
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
            if len(results) == 2:
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
