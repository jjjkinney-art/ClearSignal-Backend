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
from io import BytesIO
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urldefrag, urljoin, urlsplit

import requests
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from .sec_risk_sections import complete_risk_window, RISK_FORMS
from .reviewed_annual_layouts import reviewed_annual_layout, reviewed_body_hash
from .reviewed_incorporations import registered_incorporation


MAX_DOCUMENT_BYTES = 2_000_000
# Observed SEC primary JPM annual/quarterly HTML files are 12.93/11.51 MB.
# Only eligible periodic HTML uses this finite ceiling; ordinary files use 2 MB.
MAX_SEC_PERIODIC_BYTES = 15_000_000
MAX_SEC_PERIODIC_CHARS = 360_000
MAX_EXTRACTED_CHARS = 120_000
MAX_REDIRECTS = 3
MAX_PDF_PAGES = 250
_ALLOWED_TYPES = {
    "text/html", "application/xhtml+xml", "text/plain", "application/pdf",
}
_SENSITIVE_QUERY_KEYS = {
    "api_key", "apikey", "api-key", "key", "token", "access_token",
    "authorization", "auth", "secret", "signature", "sig",
}


class PublicDocumentError(ValueError):
    """A public document could not be retrieved safely."""

    def __init__(self, message: str, *, failure_kind: str = "document_rejected",
                 http_status: int | None = None, error_class: str | None = None,
                 size_limit_bytes: int | None = None, declared_bytes: int | None = None,
                 observed_bytes: int | None = None):
        super().__init__(message)
        self.failure_kind = failure_kind
        self.http_status = http_status
        self.error_class = error_class
        self.size_limit_bytes = size_limit_bytes
        self.declared_bytes = declared_bytes
        self.observed_bytes = observed_bytes


def _request_failure(exc: requests.RequestException, response) -> PublicDocumentError:
    """Expose bounded failure metadata without exception URLs, bodies or headers."""
    if isinstance(exc, requests.exceptions.SSLError):
        kind, error_class = "tls_error", "SSLError"
    elif isinstance(exc, requests.Timeout):
        kind, error_class = "timeout", "Timeout"
    elif isinstance(exc, requests.HTTPError):
        kind, error_class = "http_error", "HTTPError"
    elif isinstance(exc, requests.ConnectionError):
        kind, error_class = "connection_error", "ConnectionError"
    else:
        kind, error_class = "request_error", "RequestException"
    status = getattr(response, "status_code", None) if kind == "http_error" else None
    if not isinstance(status, int) or isinstance(status, bool) or not 100 <= status <= 599:
        status = None
    return PublicDocumentError(
        "public document request failed", failure_kind=kind,
        http_status=status, error_class=error_class,
    )


@dataclass(frozen=True)
class DocumentSection:
    heading: str
    start_offset: int


@dataclass(frozen=True)
class DocumentPage:
    page_number: int
    start_offset: int
    end_offset: int
    text: str


@dataclass(frozen=True)
class DocumentLink:
    url: str
    label: str


@dataclass(frozen=True)
class DocumentTable:
    table_number: int
    context: str
    rows: tuple[tuple[str, ...], ...]


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
    pages: tuple[DocumentPage, ...]
    links: tuple[DocumentLink, ...]
    extraction_method: str
    text_ready: bool
    accessed_at: str
    publisher: str | None = None
    published_at: str | None = None
    document_type: str | None = None
    source_type: str = "unknown"
    source_tier: str = "unverified"
    trusted_for_instructions: bool = False
    tables: tuple[DocumentTable, ...] = ()
    normalized_text_chars_total: int | None = None
    text_window_start: int = 0
    text_selection: str = "prefix"
    canonical_content_hash: str | None = None
    inline_xbrl_facts: tuple[dict, ...] = ()


class _VisibleHTMLParser(HTMLParser):
    """Exclude explicit hidden markup, including SEC Inline XBRL metadata.

    This is not a CSS renderer. External stylesheets are not evaluated; only
    hidden elements, inline display/visibility declarations and metadata tags
    are excluded. Visible ix:nonNumeric/nonFraction values remain intact.
    """
    _BLOCKED = {"script", "style", "noscript", "template", "svg", "ix:header", "ix:hidden"}
    _VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
    _HIDDEN_STYLE = re.compile(r"(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden)\s*(?:!important\s*)?(?:;|$)", re.I)

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._visibility_stack: list[tuple[str, bool]] = []
        self._hidden_depth = 0

    def _visible_start(self, tag, attrs):
        hidden = tag in self._BLOCKED or any(
            key.lower() == "hidden" or (key.lower() == "style" and self._HIDDEN_STYLE.search(value or ""))
            for key, value in attrs)
        visible = not self._hidden_depth and not hidden
        if tag not in self._VOID:
            self._visibility_stack.append((tag, bool(hidden)))
            self._hidden_depth += bool(hidden)
        return visible

    def _visible_end(self, tag):
        visible = not self._hidden_depth
        for index in range(len(self._visibility_stack) - 1, -1, -1):
            if self._visibility_stack[index][0] == tag:
                self._hidden_depth -= sum(hidden for _, hidden in self._visibility_stack[index:])
                del self._visibility_stack[index:]
                break
        return visible

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag.lower() not in self._VOID:
            self.handle_endtag(tag)


class _HTMLTableExtractor(_VisibleHTMLParser):
    """Keep bounded visible rows; nested or incomplete tables are excluded.

    Cell spans are deliberately not expanded. Consumers must recognize exact
    header/value layouts before assigning a cell to a reporting period.
    """

    def __init__(self) -> None:
        super().__init__()
        self._depth = 0
        self._number = 0
        self._context = ""
        self._table_context = ""
        self._rows: list[tuple[str, ...]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._invalid = False
        self._tables: list[DocumentTable] = []
        self._chars = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if not self._visible_start(tag, attrs):
            return
        if tag == "table":
            self._depth += 1
            if self._depth == 1:
                self._number += 1
                self._table_context = _clean_text(self._context)[-1000:]
                self._rows, self._row, self._cell = [], None, None
                self._invalid = False
            else:
                self._invalid = True
        elif self._depth == 1 and tag == "tr":
            if self._row is not None:
                self._invalid = True
            self._row = []
        elif self._depth == 1 and tag in {"td", "th"}:
            if self._cell is not None or self._row is None:
                self._invalid = True
            # Multi-row cells can change the apparent row identity.
            if any(key == "rowspan" and value not in {None, "1"} for key, value in attrs):
                self._invalid = True
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._hidden_depth:
            return
        if not self._depth:
            self._context = (self._context + " " + data)[-2000:]
        elif self._depth == 1 and self._cell is not None:
            if sum(map(len, self._cell)) + len(data) > 500:
                self._invalid = True
            else:
                self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if not self._visible_end(tag):
            return
        if self._depth == 1 and tag in {"td", "th"} and self._cell is not None:
            if self._row is not None and len(self._row) < 64:
                self._row.append(_clean_text(" ".join(self._cell)))
            else:
                self._invalid = True
            self._cell = None
        elif self._depth == 1 and tag == "tr" and self._row is not None:
            if self._cell is not None or len(self._rows) >= 250:
                self._invalid = True
            else:
                self._rows.append(tuple(self._row))
            self._row = None
        elif tag == "table" and self._depth:
            self._depth -= 1
            if not self._depth:
                size = sum(len(cell) for row in self._rows for cell in row)
                if (not self._invalid and self._row is None and self._cell is None
                        and self._rows and len(self._tables) < 200
                        and self._chars + size <= MAX_EXTRACTED_CHARS):
                    self._tables.append(DocumentTable(
                        self._number, self._table_context, tuple(self._rows),
                    ))
                    self._chars += size

    def result(self) -> tuple[DocumentTable, ...]:
        return tuple(self._tables)


class _ReviewedRiskTableExtractor(_HTMLTableExtractor):
    """One hash-verified table; only empty decorative row spans may be ignored.

    Existing generic table rules remain intact. Reviewed layout cells have a
    separate 2k ceiling, and nonempty row-spanned cells still invalidate a table.
    """
    def __init__(self, table_number: int):
        super().__init__()
        self._reviewed_number = table_number
        self._decorative_span = False

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"td", "th"} and self._number == self._reviewed_number and self._depth == 1:
            self._decorative_span = any(k == "rowspan" and v not in {None, "1"} for k, v in attrs)
            attrs = [(k, v) for k, v in attrs if k != "rowspan"]
        super().handle_starttag(tag, attrs)

    def handle_data(self, data):
        if self._number == self._reviewed_number and self._depth == 1 and self._cell is not None:
            if self._hidden_depth:
                return
            if sum(map(len, self._cell)) + len(data) > 2000:
                self._invalid = True
            else:
                self._cell.append(data)
        else:
            super().handle_data(data)

    def handle_endtag(self, tag):
        if (tag.lower() in {"td", "th"} and self._number == self._reviewed_number
                and self._depth == 1 and self._decorative_span):
            if _clean_text(" ".join(self._cell or [])):
                self._invalid = True
            self._decorative_span = False
        super().handle_endtag(tag)

    def result(self):
        return tuple(t for t in super().result() if t.table_number == self._reviewed_number)


class _HTMLTextExtractor(_VisibleHTMLParser):
    _HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self) -> None:
        super().__init__()
        self.normalized_text_chars_total = 0
        self.text_window_start = 0
        self.text_selection = "prefix"
        self._in_title = False
        self._heading_depth = 0
        self._title_parts: list[str] = []
        self._parts: list[str] = []
        self._text_chars = 0
        self._headings: list[tuple[str, int]] = []
        self._heading_parts: list[str] = []
        self._heading_start = 0
        self._active_link: str | None = None
        self._link_parts: list[str] = []
        self._links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if not self._visible_start(tag, attrs):
            return
        if tag == "title":
            self._in_title = True
        elif tag in self._HEADINGS:
            self._heading_depth += 1
            self._heading_parts = []
            self._heading_start = self._text_chars + bool(self._parts)
        elif tag == "a":
            href = next((value for key, value in attrs if key.lower() == "href"), None)
            self._active_link = href.strip() if href else None
            self._link_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if not self._visible_end(tag):
            return
        if tag == "title":
            self._in_title = False
        elif tag in self._HEADINGS and self._heading_depth:
            heading = _clean_text(" ".join(self._heading_parts))
            if heading:
                self._headings.append((heading[:300], self._heading_start))
            self._heading_depth -= 1
            self._heading_parts = []
        elif tag == "a" and self._active_link:
            label = _clean_text(" ".join(self._link_parts))[:300]
            self._links.append((self._active_link, label))
            self._active_link = None
            self._link_parts = []

    def handle_data(self, data: str) -> None:
        if self._hidden_depth:
            return
        value = _clean_text(data)
        if not value:
            return
        if self._in_title:
            self._title_parts.append(value)
        if self._heading_depth:
            self._heading_parts.append(value)
        if self._active_link:
            self._link_parts.append(value)
        self._text_chars += len(value) + bool(self._parts)
        self._parts.append(value)

    def normalized_visible_text(self, *, preserve_sec_risk: bool = False) -> str:
        text = _clean_text(" ".join(self._parts))
        if preserve_sec_risk:
            # Remove only the observed SEC pagination token, never substantive
            # numbers, bare page numbers or arbitrary numeric sentence content.
            text = _SEC_PAGE_FOOTER.sub('', text)
        return text

    def result(self, *, max_chars: int = MAX_EXTRACTED_CHARS, preserve_sec_risk: bool = False, preserve_sec_business: bool = False, risk_form: str = "10-K", risk_layout: dict | None = None) -> tuple[
        str | None, str, tuple[DocumentSection, ...], tuple[tuple[str, str], ...],
    ]:
        title = _clean_text(" ".join(self._title_parts))[:300] or None
        original_text = _clean_text(" ".join(self._parts))
        removed = list(_SEC_PAGE_FOOTER.finditer(original_text)) if preserve_sec_risk else []
        # Reuse the normalized full text: joining and normalizing a large filing
        # a second time adds work without changing text or source offsets.
        full_text = _SEC_PAGE_FOOTER.sub('', original_text) if preserve_sec_risk else original_text
        self.normalized_text_chars_total = len(full_text)
        start, end = 0, max_chars
        if preserve_sec_risk and len(full_text) > max_chars:
            window = complete_risk_window(full_text, form=risk_form, layout=risk_layout)
            if preserve_sec_business and risk_form == "10-K" and window:
                from .sec_risk_sections import complete_business_window
                business = complete_business_window(full_text)
                if business and business[1] <= window[0] and window[1] - business[0] <= max_chars:
                    # Retain the opening heading so downstream extraction can
                    # establish the same complete Item 1 boundary.
                    from .sec_risk_sections import BUSINESS_START
                    opening = next((m for m in BUSINESS_START.finditer(full_text)
                                    if m.end() == business[0]), None)
                    if opening and window[1] - opening.start() <= max_chars:
                        window = (opening.start(), window[1])
                        self.text_selection = "complete_sec_business_and_risk_section"
            if window and window[1] > max_chars and window[1] - window[0] <= max_chars:
                start, end = window
                if self.text_selection != "complete_sec_business_and_risk_section":
                    self.text_selection = "complete_sec_risk_section"
        self.text_window_start = start
        text = full_text[start:end]
        headings = [(heading, offset - sum(m.end() - m.start() for m in removed if m.end() <= offset))
                    for heading, offset in self._headings[:200]
                    if not any(m.start() <= offset < m.end() for m in removed)]
        sections = tuple(
            DocumentSection(heading=heading, start_offset=min(offset - start, len(text)))
            for heading, offset in headings
            if start <= offset and offset + len(heading) <= min(end, len(full_text))
        )
        return title, text, sections, tuple(self._links[:500])


def _normalize_links(
    base_url: str, links: tuple[tuple[str, str], ...],
) -> tuple[DocumentLink, ...]:
    normalized: list[DocumentLink] = []
    seen: set[str] = set()
    for href, label in links:
        try:
            resolved, _ = urldefrag(urljoin(base_url, href))
            parsed = urlsplit(resolved)
            port = parsed.port
        except ValueError:
            continue
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or port not in (None, 443)):
            continue
        if any(key.lower() in _SENSITIVE_QUERY_KEYS for key, _ in parse_qsl(parsed.query)):
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        normalized.append(DocumentLink(url=resolved, label=label))
    return tuple(normalized)


def _clean_text(value: str) -> str:
    value = value.replace("\x00", " ")
    return re.sub(r"\s+", " ", value).strip()


_SEC_PAGE_FOOTER = re.compile(r'\b\d{1,4} Table of Contents(?: |$)')


def _extract_pdf(
    body: bytes,
) -> tuple[str | None, str, tuple[DocumentPage, ...]]:
    if not body.startswith(b"%PDF-"):
        raise PublicDocumentError("document content did not match PDF media type")
    try:
        reader = PdfReader(BytesIO(body), strict=False)
        if reader.is_encrypted:
            raise PublicDocumentError("encrypted PDF documents are not supported")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise PublicDocumentError("PDF exceeds the page limit")
        title_value = getattr(reader.metadata, "title", None) if reader.metadata else None
        title = _clean_text(str(title_value))[:300] if title_value else None
        page_texts: list[str] = []
        extracted_chars = 0
        for page in reader.pages:
            value = _clean_text(page.extract_text() or "")
            extracted_chars += len(value)
            if extracted_chars > MAX_EXTRACTED_CHARS:
                raise PublicDocumentError("PDF extracted text exceeds the limit")
            page_texts.append(value)
    except PublicDocumentError:
        raise
    except (PdfReadError, ValueError, TypeError, OSError, KeyError, RecursionError) as exc:
        raise PublicDocumentError("PDF could not be parsed safely") from exc

    text_parts: list[str] = []
    pages: list[DocumentPage] = []
    offset = 0
    for page_number, value in enumerate(page_texts, start=1):
        if not value:
            continue
        if text_parts:
            offset += 1
        start = offset
        text_parts.append(value)
        offset += len(value)
        pages.append(DocumentPage(page_number, start, offset, value))
    return title, " ".join(text_parts), tuple(pages)


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
        raise PublicDocumentError(
            "document host could not be resolved", failure_kind="dns_error",
            error_class="DNSLookupError",
        ) from exc
    if not addresses:
        raise PublicDocumentError("document host did not resolve", failure_kind="dns_error")
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            raise PublicDocumentError("document host returned an invalid address") from exc
        if not ip.is_global:
            raise PublicDocumentError("private or reserved document hosts are not allowed")
    return candidate


def _read_bounded(response: requests.Response, *, max_bytes: int = MAX_DOCUMENT_BYTES) -> bytes:
    declared = response.headers.get("Content-Length")
    if declared:
        try:
            declared_size = int(declared)
        except ValueError as exc:
            raise PublicDocumentError("invalid document content length") from exc
        if declared_size < 0:
            raise PublicDocumentError("invalid document content length")
        if declared_size > max_bytes:
            raise PublicDocumentError("document exceeds the size limit",
                                      size_limit_bytes=max_bytes, declared_bytes=declared_size)
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            raise PublicDocumentError("document exceeds the size limit",
                                      size_limit_bytes=max_bytes, observed_bytes=total)
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
    sec_periodic_limits: bool = False,
    preserve_sec_business: bool = False,
    extract_tables: bool = True,
    inline_fact_cik: str | None = None,
    inline_fact_concepts: tuple[str, ...] = (),
) -> PublicDocument:
    """Fetch one public document with bounded redirects and content."""
    requested_url = _validate_public_url(url)
    if inline_fact_cik is not None and not sec_periodic_limits:
        raise PublicDocumentError("Inline XBRL extraction requires SEC periodic limits")
    current_url = requested_url
    response = None
    layout = None
    try:
        for redirect_count in range(MAX_REDIRECTS + 1):
            current_url = _validate_public_url(current_url)
            incorporation = registered_incorporation(current_url, document_type, published_at) if sec_periodic_limits else None
            if sec_periodic_limits:
                parsed = urlsplit(current_url)
                if (publisher != "SEC EDGAR" or source_type != "regulatory_filing"
                        or source_tier != "primary"
                        or (document_type not in RISK_FORMS and not incorporation)
                        or parsed.hostname != "www.sec.gov" or parsed.query or parsed.fragment
                        or not re.fullmatch(r"/Archives/edgar/data/\d+/\d{18}/[^/]+\.html?", parsed.path)):
                    raise PublicDocumentError("expanded limits require a SEC periodic HTML filing")
            layout = (reviewed_annual_layout(current_url, document_type, published_at)
                      if sec_periodic_limits else None)
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
        if sec_periodic_limits and media_type not in {"text/html", "application/xhtml+xml"}:
            raise PublicDocumentError("expanded limits require HTML content")
        body = _read_bounded(response, max_bytes=(layout["max_bytes"] if layout else MAX_SEC_PERIODIC_BYTES
                                                if sec_periodic_limits else MAX_DOCUMENT_BYTES))
        encoding = response.encoding or "utf-8"
    except PublicDocumentError:
        raise
    except requests.RequestException as exc:
        raise _request_failure(exc, response) from exc
    finally:
        if response is not None:
            response.close()

    digest = hashlib.sha256(body).hexdigest()
    canonical_digest = reviewed_body_hash(body) if layout or incorporation else None
    if layout and canonical_digest != layout["canonical_content_hash"]:
        raise PublicDocumentError("reviewed annual document hash mismatch")
    if incorporation and canonical_digest != incorporation[0][incorporation[1] + "_canonical_hash"]:
        raise PublicDocumentError("reviewed incorporation document hash mismatch")
    accessed_at = datetime.now(timezone.utc).isoformat()
    if media_type == "application/pdf":
        title, text, pages = _extract_pdf(body)
        return PublicDocument(
            requested_url=requested_url, final_url=current_url,
            content_type=media_type, content_hash=digest, byte_count=len(body),
            title=title, text=text, sections=(), pages=pages, links=(),
            extraction_method="pdf_text" if text else "unknown",
            text_ready=bool(text),
            accessed_at=accessed_at, publisher=publisher,
            published_at=published_at, document_type=document_type,
            source_type=source_type, source_tier=source_tier,
        )
    decoded = body.decode(encoding, errors="replace")
    inline_facts = ()
    if inline_fact_cik is not None:
        from ..providers.sec_inline_facts import parse_inline_observations
        inline_facts = parse_inline_observations(decoded, cik=inline_fact_cik,
                                                concepts=inline_fact_concepts)
    tables: tuple[DocumentTable, ...] = ()
    text_metadata = {}
    if media_type in {"text/html", "application/xhtml+xml"}:
        parser = _HTMLTextExtractor()
        parser.feed(decoded)
        if layout and layout["mapping"] not in parser.normalized_visible_text(preserve_sec_risk=True):
            raise PublicDocumentError("reviewed annual risk mapping unavailable")
        title, text, sections, raw_links = parser.result(
            max_chars=MAX_SEC_PERIODIC_CHARS if sec_periodic_limits else MAX_EXTRACTED_CHARS,
            preserve_sec_risk=sec_periodic_limits, preserve_sec_business=preserve_sec_business, risk_form=document_type or "10-K", risk_layout=layout)
        text_metadata = {"canonical_content_hash": canonical_digest,
                         "normalized_text_chars_total": parser.normalized_text_chars_total,
                         "text_window_start": parser.text_window_start,
                         "text_selection": parser.text_selection}
        links = _normalize_links(current_url, raw_links)
        method = "html"
        if incorporation and incorporation[1] == "exhibit":
            table_parser = _ReviewedRiskTableExtractor(incorporation[0]["table_number"])
            table_parser.feed(decoded)
            tables = table_parser.result()
        elif extract_tables:
            table_parser = _HTMLTableExtractor()
            table_parser.feed(decoded)
            tables = table_parser.result()
    else:
        title, text, sections, links, method = (
            None, _clean_text(decoded)[:MAX_EXTRACTED_CHARS], (), (), "manual"
        )
    if not text:
        raise PublicDocumentError("document contained no extractable text")
    return PublicDocument(
        requested_url=requested_url, final_url=current_url,
        content_type=media_type, content_hash=digest, byte_count=len(body),
        title=title, text=text, sections=sections, pages=(), links=links,
        extraction_method=method,
        text_ready=True,
        accessed_at=accessed_at, publisher=publisher,
        published_at=published_at, document_type=document_type,
        source_type=source_type, source_tier=source_tier,
        tables=tables,
        inline_xbrl_facts=inline_facts,
        **text_metadata,
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
