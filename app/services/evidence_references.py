"""Safe, presentation-ready references for retrieved evidence.

The analysis pipeline may use provider request URLs containing credentials.
Those URLs are never serialized. Only explicit public evidence URLs, or the
legacy ``[Source: https://...]`` marker used by NewsAPI evidence, are accepted.
"""

from __future__ import annotations

import re
from typing import Iterable
from urllib.parse import parse_qsl, urlsplit


_LEGACY_SOURCE_RE = re.compile(r"\[Source:\s*(https?://[^\]\s]+)\]", re.IGNORECASE)
_SENSITIVE_QUERY_KEYS = {
    "api_key", "apikey", "api-key", "key", "token", "access_token",
    "authorization", "auth", "secret",
}


def _safe_public_url(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return None
    if parsed.scheme != "https" or not parsed.hostname:
        return None
    if parsed.username or parsed.password:
        return None
    if any(key.lower() in _SENSITIVE_QUERY_KEYS for key, _ in parse_qsl(parsed.query)):
        return None
    return candidate


def _evidence_url(item: object) -> str | None:
    explicit = _safe_public_url(getattr(item, "url", None))
    if explicit:
        return explicit
    summary = getattr(item, "summary", "")
    if not isinstance(summary, str):
        return None
    match = _LEGACY_SOURCE_RE.search(summary)
    return _safe_public_url(match.group(1)) if match else None


def _metadata(item: object) -> dict:
    """Return explicit metadata, with conservative legacy-source fallbacks."""
    source = str(getattr(item, "source", "") or "").lower()
    source_type = str(getattr(item, "source_type", "unknown") or "unknown")
    source_tier = str(getattr(item, "source_tier", "unverified") or "unverified")
    claim_type = str(getattr(item, "claim_type", "unknown") or "unknown")
    extraction_method = str(
        getattr(item, "extraction_method", "unknown") or "unknown"
    )
    if source_type == "unknown":
        if "sec edgar" in source:
            source_type = "regulatory_filing"
            source_tier = "primary"
            claim_type = (
                "reported_fact" if "structured xbrl" in source else "filing_metadata"
            )
        elif "fred" in source:
            source_type, source_tier = "government_dataset", "primary"
        elif "reuters" in source or "associated press" in source:
            source_type, source_tier = "news", "reputable_secondary"
        elif "fmp" in source or "financial modeling prep" in source:
            source_type, source_tier = "market_data", "authoritative_secondary"
    return {
        "source_type": source_type,
        "source_tier": source_tier,
        "claim_type": claim_type,
        "document_type": getattr(item, "document_type", None),
        "reporting_period_start": getattr(item, "reporting_period_start", None),
        "reporting_period_end": getattr(item, "reporting_period_end", None),
        "filed_at": getattr(item, "filed_at", None),
        "retrieved_at": getattr(item, "retrieved_at", None),
        "observed_at": getattr(item, "observed_at", None),
        "section": getattr(item, "section", None),
        "page": getattr(item, "page", None),
        "extraction_method": extraction_method,
    }


def _build_references(material: list[object]) -> list[dict]:
    references: list[dict] = []
    seen: set[tuple[str, str, str, str | None]] = set()
    for item_index, item in enumerate(material):
        title = str(getattr(item, "title", "") or "Untitled evidence").strip()
        source = str(getattr(item, "source", "") or "Unknown source").strip()
        published_at = str(getattr(item, "timestamp", "") or "").strip()
        url = _evidence_url(item)
        identity = (title, source, published_at, url)
        if identity in seen:
            continue
        seen.add(identity)
        references.append({
            "_item_index": item_index,
            "id": f"E{len(references) + 1}",
            "title": title[:300],
            "source": source[:120],
            "published_at": published_at[:40] or None,
            "url": url,
            "inspectable": bool(url),
            **_metadata(item),
        })
    return references


def build_evidence_references(items: Iterable[object]) -> list[dict]:
    """Return bounded, non-secret evidence metadata in retrieval order."""
    material = list(items)
    references = _build_references(material)
    from .evidence_integrity import apply_evidence_integrity
    apply_evidence_integrity(material, references)
    for reference in references:
        reference.pop("_item_index", None)
    return references


def build_evidence_contract(
    items: Iterable[object], *, as_of: str | None = None,
    evaluated_at: str | None = None,
) -> tuple[list[dict], dict]:
    """Return presentation references plus their shared integrity summary."""
    material = list(items)
    references = _build_references(material)
    from .evidence_integrity import apply_evidence_integrity
    integrity = apply_evidence_integrity(
        material, references, as_of=as_of, evaluated_at=evaluated_at,
    )
    for reference in references:
        reference.pop("_item_index", None)
    return references, integrity
