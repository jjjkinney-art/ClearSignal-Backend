"""Bounded, SSRF-safe retrieval for public company documents.

Fetched content is untrusted data. This module never turns document text into
instructions or claim evidence; later extractors must bind claims to explicit
sections/pages before the content can enter synthesis.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urljoin, urlsplit

import requests


MAX_DOCUMENT_BYTES = 2_000_000
MAX_EXTRACTED_CHARS = 120_000
MAX_REDIRECTS = 3
_ALLOWED_TYPES = {
    "text/html", "application/xhtml+xml", "text/plain", "application/pdf",
}
_SENSITIVE_QUERY_KEYS = {
    "api_key", "apikey", "api-key", "key", "token", "access_token",
    "authorization", "auth", "secret", "signature", "sig",
}


class PublicDocumentError(ValueError):
    """A public document could not be retrieved safely."""


@dataclass(frozen=True)
class DocumentSection:
    heading: str
    start_offset: int


@dataclass(frozen=True)
class PublicDocument:
    requested_url: str
    final_url: str
    content_type: str
    content_hash: str
    byte_count: int
    title: str | None
    text: str
    sections: tuple[DocumentSection, ...]
    extraction_method: str
    text_ready: bool
    accessed_at: str
    publisher: str | None = None
    published_at: str | None = None
    document_type: str | None = None
    source_type: str = "unknown"
    source_tier: str = "unverified"
    trusted_for_instructions: bool = False


class _HTMLTextExtractor(HTMLParser):
    _BLOCKED = {"script", "style", "noscript", "template", "svg"}
    _HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._blocked_depth = 0
        self._in_title = False
        self._heading_depth = 0
        self._title_parts: list[str] = []
        self._parts: list[str] = []
        self._headings: list[tuple[str, int]] = []
        self._heading_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self._BLOCKED:
            self._blocked_depth += 1
        elif not self._blocked_depth and tag == "title":
            self._in_title = True
        elif not self._blocked_depth and tag in self._HEADINGS:
            self._heading_depth += 1
            self._heading_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._BLOCKED and self._blocked_depth:
            self._blocked_depth -= 1
        elif not self._blocked_depth and tag == "title":
            self._in_title = False
        elif not self._blocked_depth and tag in self._HEADINGS and self._heading_depth:
            heading = _clean_text(" ".join(self._heading_parts))
            if heading:
                self._headings.append((heading[:300], len(" ".join(self._parts))))
            self._heading_depth -= 1
            self._heading_parts = []

    def handle_data(self, data: str) -> None:
        if self._blocked_depth:
            return
        value = data.strip()
        if not value:
            return
        if self._in_title:
            self._title_parts.append(value)
        if self._heading_depth:
            self._heading_parts.append(value)
        self._parts.append(value)

    def result(self) -> tuple[str | None, str, tuple[DocumentSection, ...]]:
        title = _clean_text(" ".join(self._title_parts))[:300] or None
        text = _clean_text(" ".join(self._parts))[:MAX_EXTRACTED_CHARS]
        sections = tuple(
            DocumentSection(heading=heading, start_offset=min(offset, len(text)))
            for heading, offset in self._headings[:200]
        )
        return title, text, sections


def _clean_text(value: str) -> str:
    value = value.replace("\x00", " ")
    return re.sub(r"\s+", " ", value).strip()


def _validate_public_url(url: str) -> str:
    if not isinstance(url, str) or not url.strip():
        raise PublicDocumentError("document URL is required")
    candidate = url.strip()
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError as exc:
        raise PublicDocumentError("invalid document URL") from exc
    if parsed.scheme != "https" or not parsed.hostname:
        raise PublicDocumentError("only public HTTPS document URLs are allowed")
    if parsed.username or parsed.password or port not in (None, 443):
        raise PublicDocumentError("credentials and nonstandard ports are not allowed")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith((".localhost", ".local")):
        raise PublicDocumentError("local document hosts are not allowed")
    if parsed.fragment:
        raise PublicDocumentError("document URL fragments are not allowed")
    if any(key.lower() in _SENSITIVE_QUERY_KEYS for key, _ in parse_qsl(parsed.query)):
        raise PublicDocumentError("credential-bearing document URLs are not allowed")
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
        }
    except OSError as exc:
        raise PublicDocumentError("document host could not be resolved") from exc
    if not addresses:
        raise PublicDocumentError("document host did not resolve")
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            raise PublicDocumentError("document host returned an invalid address") from exc
        if not ip.is_global:
            raise PublicDocumentError("private or reserved document hosts are not allowed")
    return candidate


def _read_bounded(response: requests.Response) -> bytes:
    declared = response.headers.get("Content-Length")
    if declared:
        try:
            declared_size = int(declared)
        except ValueError as exc:
            raise PublicDocumentError("invalid document content length") from exc
        if declared_size < 0:
            raise PublicDocumentError("invalid document content length")
        if declared_size > MAX_DOCUMENT_BYTES:
            raise PublicDocumentError("document exceeds the size limit")
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > MAX_DOCUMENT_BYTES:
            raise PublicDocumentError("document exceeds the size limit")
        chunks.append(chunk)
    return b"".join(chunks)


def fetch_public_document(
    url: str,
    *,
    user_agent: str = "",
    publisher: str | None = None,
    published_at: str | None = None,
    document_type: str | None = None,
    source_type: str = "unknown",
    source_tier: str = "unverified",
) -> PublicDocument:
    """Fetch one public document with bounded redirects and content."""
    requested_url = _validate_public_url(url)
    current_url = requested_url
    response = None
    try:
        for redirect_count in range(MAX_REDIRECTS + 1):
            current_url = _validate_public_url(current_url)
            response = requests.get(
                current_url,
                headers={"User-Agent": user_agent or "ClearSignal/1.0 public-document-research"},
                timeout=(5, 15), stream=True, allow_redirects=False,
            )
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("Location")
                response.close()
                if not location or redirect_count == MAX_REDIRECTS:
                    raise PublicDocumentError("document redirect limit exceeded")
                current_url = urljoin(current_url, location)
                continue
            response.raise_for_status()
            break
        if response is None:
            raise PublicDocumentError("document request failed")
        media_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if media_type not in _ALLOWED_TYPES:
            raise PublicDocumentError("unsupported document content type")
        body = _read_bounded(response)
        encoding = response.encoding or "utf-8"
    except PublicDocumentError:
        raise
    except requests.RequestException as exc:
        raise PublicDocumentError("public document request failed") from exc
    finally:
        if response is not None:
            response.close()

    digest = hashlib.sha256(body).hexdigest()
    accessed_at = datetime.now(timezone.utc).isoformat()
    if media_type == "application/pdf":
        return PublicDocument(
            requested_url=requested_url, final_url=current_url,
            content_type=media_type, content_hash=digest, byte_count=len(body),
            title=None, text="", sections=(), extraction_method="unknown",
            text_ready=False,
            accessed_at=accessed_at, publisher=publisher,
            published_at=published_at, document_type=document_type,
            source_type=source_type, source_tier=source_tier,
        )
    decoded = body.decode(encoding, errors="replace")
    if media_type in {"text/html", "application/xhtml+xml"}:
        parser = _HTMLTextExtractor()
        parser.feed(decoded)
        title, text, sections = parser.result()
        method = "html"
    else:
        title, text, sections, method = None, _clean_text(decoded)[:MAX_EXTRACTED_CHARS], (), "manual"
    if not text:
        raise PublicDocumentError("document contained no extractable text")
    return PublicDocument(
        requested_url=requested_url, final_url=current_url,
        content_type=media_type, content_hash=digest, byte_count=len(body),
        title=title, text=text, sections=sections, extraction_method=method,
        text_ready=True,
        accessed_at=accessed_at, publisher=publisher,
        published_at=published_at, document_type=document_type,
        source_type=source_type, source_tier=source_tier,
    )


def deduplicate_documents(documents: list[PublicDocument]) -> list[PublicDocument]:
    """Keep the first document for each byte-identical SHA-256 body."""
    seen: set[str] = set()
    unique: list[PublicDocument] = []
    for document in documents:
        if document.content_hash in seen:
            continue
        seen.add(document.content_hash)
        unique.append(document)
    return unique
