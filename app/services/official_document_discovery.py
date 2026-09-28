"""Conservative discovery of official issuer and SEC documents.

Discovery only promotes links from an explicitly allowlisted issuer host or the
SEC archive. Classification is deterministic and records why a candidate was
accepted; ambiguous links remain excluded rather than becoming primary evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from .public_document_ingestion import PublicDocument


_SEC_ARCHIVE_PATH = re.compile(
    r"^/Archives/edgar/data/\d+/\d+/[^/]+\.(?:html?|txt|pdf)$", re.IGNORECASE,
)
_CLASSIFIERS = (
    ("earnings_release", "issuer_release", (
        "earnings release", "financial results", "quarterly results", "full year results",
    )),
    ("investor_presentation", "investor_presentation", (
        "investor presentation", "earnings presentation", "results presentation",
    )),
    ("shareholder_letter", "issuer_release", (
        "shareholder letter", "letter to shareholders", "letter to stockholders",
    )),
    ("press_release", "issuer_release", ("press release", "news release")),
)


@dataclass(frozen=True)
class OfficialDocumentCandidate:
    url: str
    title: str
    document_type: str
    source_type: str
    source_tier: str
    publisher: str | None
    published_at: str | None
    discovery_reason: str


def _normalized_host(value: str) -> str | None:
    candidate = value.strip().lower().rstrip(".")
    if not candidate or "." not in candidate or "/" in candidate or "@" in candidate:
        return None
    try:
        return candidate.encode("idna").decode("ascii")
    except UnicodeError:
        return None


def _host_is_allowed(host: str, allowed_hosts: tuple[str, ...]) -> bool:
    normalized = _normalized_host(host)
    if not normalized:
        return False
    for allowed in allowed_hosts:
        base = _normalized_host(allowed)
        if base and (normalized == base or normalized.endswith("." + base)):
            return True
    return False


def _classify(label: str, url: str) -> tuple[str, str] | None:
    haystack = f"{label} {url}".lower().replace("_", "-")
    for document_type, source_type, phrases in _CLASSIFIERS:
        if any(phrase in haystack for phrase in phrases):
            return document_type, source_type
    return None


def discover_official_documents(
    index_document: PublicDocument,
    *,
    issuer_hosts: tuple[str, ...],
    publisher: str | None = None,
    published_at: str | None = None,
    limit: int = 25,
) -> list[OfficialDocumentCandidate]:
    """Return unambiguous primary-document links from one official index page."""
    if limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")
    try:
        index_host = urlsplit(index_document.final_url).hostname or ""
    except ValueError:
        return []
    if not _host_is_allowed(index_host, issuer_hosts):
        return []

    candidates: list[OfficialDocumentCandidate] = []
    seen: set[str] = set()
    for link in index_document.links:
        try:
            parsed = urlsplit(link.url)
            host = parsed.hostname or ""
        except ValueError:
            continue
        sec_document = host == "www.sec.gov" and bool(_SEC_ARCHIVE_PATH.fullmatch(parsed.path))
        issuer_document = _host_is_allowed(host, issuer_hosts)
        if not (sec_document or issuer_document):
            continue
        classified = _classify(link.label, link.url)
        if not classified:
            continue
        document_type, source_type = classified
        if sec_document:
            source_type = "regulatory_filing"
        if link.url in seen:
            continue
        seen.add(link.url)
        candidates.append(OfficialDocumentCandidate(
            url=link.url,
            title=link.label or document_type.replace("_", " ").title(),
            document_type=document_type,
            source_type=source_type,
            source_tier="primary",
            publisher="SEC EDGAR" if sec_document else (publisher or index_document.publisher),
            published_at=published_at,
            discovery_reason=(
                "official SEC archive link from allowlisted issuer index"
                if sec_document else "allowlisted issuer-controlled document link"
            ),
        ))
        if len(candidates) >= limit:
            break
    return candidates
