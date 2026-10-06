"""Bounded issuer-disclosed Services risks from Apple's SEC Risk Factors.

A quoted disclosure establishes that the issuer stated a possibility. It does
not establish its likelihood, current impact or a directional thesis change.
"""
from __future__ import annotations

from datetime import date
import re
from urllib.parse import urlsplit

from ..integrity.provenance import ClaimDocumentReference
from ..schemas import RetrievedEvidence
from .public_document_ingestion import PublicDocument

_START = re.compile(r"\bItem\s+1A\s*[.:—–-]?\s*Risk\s+Factors\b", re.I)
_END = re.compile(r"\bItem\s+(?:1B|1C|2)\s*[.:—–-]?\s+(?:Unresolved|Cybersecurity|Properties|Legal|Unregistered)\b", re.I)
_SCOPE = re.compile(r"\b(?:services|app store|icloud|apple music|digital content)\b", re.I)
_POSSIBILITY = re.compile(r"\b(?:may|could|can|might)\b", re.I)
_ADVERSE = re.compile(r"\b(?:adverse|adversely|harm|loss|lost|reduce|reduced|decline|disrupt|unable|cease|fail)\b", re.I)


def _qualifying_quote(quote: str) -> bool:
    return bool(40 <= len(quote) <= 300 and quote[-1] in ".!?" and not re.search(r"\d|[$%]", quote)
                and _SCOPE.search(quote) and _POSSIBILITY.search(quote)
                and _ADVERSE.search(quote)
                # Generic company-wide product/service warnings do not establish
                # a Services operating mechanism for this bounded evidence view.
                and not re.search(r"\bproducts and services\b", quote, re.I)
                and not re.match(r"(?:this|these|that|those|it|they|such)\b", quote, re.I)
                and not re.search(r"\b(?:see|refer to|no material changes|ignore|instructions?|system prompt)\b", quote, re.I))


def requests_services_operating_risk(question: str) -> bool:
    return bool(_SCOPE.search(question or "") and re.search(
        r"\b(?:risks?|invalidate|invalidating)\b", question or "", re.I))


def _issuer_url(url: str) -> bool:
    if not isinstance(url, str):
        return False
    try:
        parsed = urlsplit(url)
        return bool(parsed.scheme == "https" and parsed.hostname == "www.sec.gov"
                    and not (parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment)
                    and re.fullmatch(r"/Archives/edgar/data/320193/\d{18}/[^/]+\.html?", parsed.path)
                    and not any(ord(c) < 33 or c == "\\" for c in url))
    except (TypeError, ValueError):
        return False


def extract_services_risk_evidence(document: PublicDocument, *, ticker: str) -> list[RetrievedEvidence]:
    """Extract at most two complete, nonnumeric risk sentences; no model calls.

    Coverage is deliberately limited to Apple's recognized 10-K/10-Q section.
    TOCs, cross-references, other sections, unsupported issuers and ambiguous
    or overlong sentences produce no claim. Never truncate a risk sentence.
    """
    if (ticker.strip().upper() != "AAPL" or not _issuer_url(document.final_url)
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
        end = _END.search(text, heading.end())
        # An explicit closing section is required; truncated text fails closed.
        if end is None or end.start() - heading.end() > 80_000:
            continue
        section = text[heading.end():end.start()]
        for sentence in re.finditer(r"(?:^|(?<=[.!?])\s+)([^.!?]+[.!?])", section):
            quote = sentence.group(1).strip()
            if not _qualifying_quote(quote) or quote in seen:
                continue
            offset = heading.end() + sentence.start(1)
            # Retain the exact normalized-document span, not a generated paraphrase.
            offset += len(sentence.group(1)) - len(sentence.group(1).lstrip())
            reference = ClaimDocumentReference(
                reference_id=f"document:{document.content_hash}:risk:{offset}",
                title=document.title or f"AAPL {document.document_type}", provider="SEC EDGAR",
                url=document.final_url, published_at=document.published_at,
                section="Item 1A. Risk Factors", content_hash=document.content_hash, quote=quote,
            ).to_dict()
            disclosure = {"claim_kind": "issuer_disclosed_risk", "ticker": "AAPL", "scope": "Services",
                          "quote": quote, "start_offset": offset, "end_offset": offset + len(quote),
                          "document_ref": reference}
            results.append(RetrievedEvidence(
                title=f"AAPL Services risk disclosure · {filed} · {len(results) + 1}",
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
    return (f'AAPL disclosed in its {form} filed {filed}: “{disclosure["quote"]}” '
            "This is an issuer-disclosed possibility, not a verified occurrence or quantified impact.")


def bound_services_risk(item: object, *, ticker: str) -> dict | None:
    """Accept only producer-bound disclosures matching their admitted source item."""
    disclosures = getattr(item, "risk_disclosures", [])
    if (ticker != "AAPL" or not isinstance(disclosures, list) or len(disclosures) != 1
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
            or value.get("scope") != "Services" or not isinstance(quote, str)
            or not _qualifying_quote(quote) or quote != ref.get("quote")
            or ref.get("section") != "Item 1A. Risk Factors" or not ref.get("content_hash")
            or ref.get("provider") != "SEC EDGAR" or not _issuer_url(ref["url"])
            or ref["url"] != getattr(item, "url", None)
            or ref["published_at"] != getattr(item, "timestamp", None)
            or type(start) is not int or type(end) is not int or start < 0 or end - start != len(quote)
            or ref["reference_id"] != f'document:{ref["content_hash"]}:risk:{start}'
            or getattr(item, "document_type", None) not in {"10-K", "10-K/A", "10-Q", "10-Q/A"}
            or getattr(item, "summary", None) != risk_summary(value, getattr(item, "document_type"))):
        return None
    return value
