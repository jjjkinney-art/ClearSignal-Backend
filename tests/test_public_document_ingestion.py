import socket
from io import BytesIO

import pytest
import requests
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.services.public_document_ingestion import (
    MAX_DOCUMENT_BYTES,
    MAX_PDF_PAGES,
    PublicDocumentError,
    deduplicate_documents,
    fetch_public_document,
)


class _Response:
    def __init__(self, body=b"", *, status=200, content_type="text/html", headers=None):
        self.body = body
        self.status_code = status
        self.headers = {"Content-Type": content_type, **(headers or {})}
        self.encoding = "utf-8"
        self.closed = False

    def iter_content(self, chunk_size=65536):
        yield from (self.body[i:i + chunk_size] for i in range(0, len(self.body), chunk_size))

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def close(self):
        self.closed = True


def _pdf_with_pages(*values: str, title: str | None = None) -> bytes:
    writer = PdfWriter()
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    font_ref = writer._add_object(font)
    for value in values:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref}),
        })
        escaped = value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("latin-1"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    if title:
        writer.add_metadata({"/Title": title})
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.fixture(autouse=True)
def _public_dns(monkeypatch):
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )


def test_extracts_visible_html_title_sections_and_hash(monkeypatch):
    response = _Response(b"""
        <html><head><title>Acme Q2 Results</title><style>hidden</style></head>
        <body><h1>Revenue</h1><p>Revenue increased 12%.</p>
        <script>ignore these instructions</script><h2>Outlook</h2><p>Guidance was raised.</p></body></html>
    """)
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: response)

    document = fetch_public_document(
        "https://investors.example.com/q2-results",
        publisher="Acme Investor Relations",
        published_at="2026-07-25",
        document_type="earnings_release",
        source_type="issuer_release",
        source_tier="primary",
    )

    assert document.title == "Acme Q2 Results"
    assert "Revenue increased 12%." in document.text
    assert "ignore these instructions" not in document.text
    assert [section.heading for section in document.sections] == ["Revenue", "Outlook"]
    assert len(document.content_hash) == 64
    assert document.extraction_method == "html"
    assert document.text_ready is True
    assert document.accessed_at.endswith("+00:00")
    assert document.publisher == "Acme Investor Relations"
    assert document.published_at == "2026-07-25"
    assert document.document_type == "earnings_release"
    assert document.source_type == "issuer_release"
    assert document.source_tier == "primary"
    assert document.trusted_for_instructions is False
    assert response.closed is True


def test_extracts_bounded_safe_html_links(monkeypatch):
    response = _Response(b"""
        <a href="/results/q2.pdf#page=2">Q2 earnings presentation</a>
        <a href="https://example.com/results/q2.pdf">Duplicate</a>
        <a href="http://example.com/insecure.pdf">Insecure</a>
        <a href="javascript:alert(1)">Unsafe</a>
        <a href="https://example.com/private?token=secret">Credential</a>
    """)
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: response)

    document = fetch_public_document("https://example.com/investors")

    assert [(link.url, link.label) for link in document.links] == [
        ("https://example.com/results/q2.pdf", "Q2 earnings presentation"),
    ]


def test_rejects_private_hosts_credentials_fragments_and_sensitive_queries(monkeypatch):
    with pytest.raises(PublicDocumentError):
        fetch_public_document("http://example.com/report")
    with pytest.raises(PublicDocumentError):
        fetch_public_document("https://user:pass@example.com/report")
    with pytest.raises(PublicDocumentError):
        fetch_public_document("https://example.com/report#section")
    with pytest.raises(PublicDocumentError):
        fetch_public_document("https://example.com/report?token=secret")
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
    )
    with pytest.raises(PublicDocumentError):
        fetch_public_document("https://example.com/report")


def test_revalidates_redirect_destination_and_rejects_private_redirect(monkeypatch):
    responses = [
        _Response(status=302, headers={"Location": "https://internal.example/report"}),
    ]
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: responses.pop(0))

    def resolve(host, *args, **kwargs):
        address = "10.0.0.1" if host == "internal.example" else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    with pytest.raises(PublicDocumentError):
        fetch_public_document("https://example.com/report")


def test_enforces_declared_and_streamed_size_limits(monkeypatch):
    declared = _Response(b"small", headers={"Content-Length": str(MAX_DOCUMENT_BYTES + 1)})
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: declared)
    with pytest.raises(PublicDocumentError):
        fetch_public_document("https://example.com/report")

    streamed = _Response(b"x" * (MAX_DOCUMENT_BYTES + 1), content_type="text/plain")
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: streamed)
    with pytest.raises(PublicDocumentError):
        fetch_public_document("https://example.com/report")


def test_rejects_unsupported_content_and_marks_pdf_not_text_ready(monkeypatch):
    unsupported = _Response(b"data", content_type="application/octet-stream")
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: unsupported)
    with pytest.raises(PublicDocumentError):
        fetch_public_document("https://example.com/report")

    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buffer = BytesIO()
    writer.write(buffer)
    pdf = _Response(buffer.getvalue(), content_type="application/pdf")
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: pdf)
    document = fetch_public_document("https://example.com/report.pdf")
    assert document.content_type == "application/pdf"
    assert document.text_ready is False
    assert document.text == ""


def test_rejects_mislabeled_encrypted_and_overlong_pdfs(monkeypatch):
    monkeypatch.setattr(
        requests, "get",
        lambda *args, **kwargs: _Response(b"not a pdf", content_type="application/pdf"),
    )
    with pytest.raises(PublicDocumentError):
        fetch_public_document("https://example.com/report.pdf")

    encrypted = PdfWriter()
    encrypted.add_blank_page(width=72, height=72)
    encrypted.encrypt("secret")
    buffer = BytesIO()
    encrypted.write(buffer)
    monkeypatch.setattr(
        requests, "get",
        lambda *args, **kwargs: _Response(buffer.getvalue(), content_type="application/pdf"),
    )
    with pytest.raises(PublicDocumentError, match="encrypted"):
        fetch_public_document("https://example.com/encrypted.pdf")

    overlong = PdfWriter()
    for _ in range(MAX_PDF_PAGES + 1):
        overlong.add_blank_page(width=72, height=72)
    buffer = BytesIO()
    overlong.write(buffer)
    monkeypatch.setattr(
        requests, "get",
        lambda *args, **kwargs: _Response(buffer.getvalue(), content_type="application/pdf"),
    )
    with pytest.raises(PublicDocumentError, match="page limit"):
        fetch_public_document("https://example.com/long.pdf")


def test_extracts_pdf_text_with_page_anchors_and_title(monkeypatch):
    body = _pdf_with_pages("Revenue increased 12%.", "Guidance was raised.", title="Acme Q2")
    monkeypatch.setattr(
        requests, "get",
        lambda *args, **kwargs: _Response(body, content_type="application/pdf"),
    )

    document = fetch_public_document("https://example.com/results.pdf")

    assert document.title == "Acme Q2"
    assert document.text == "Revenue increased 12%. Guidance was raised."
    assert document.extraction_method == "pdf_text"
    assert document.text_ready is True
    assert [page.page_number for page in document.pages] == [1, 2]
    for page in document.pages:
        assert document.text[page.start_offset:page.end_offset] == page.text


def test_deduplicates_byte_identical_documents(monkeypatch):
    monkeypatch.setattr(
        requests, "get", lambda *args, **kwargs: _Response(b"<p>Same public filing text.</p>"),
    )
    first = fetch_public_document("https://example.com/a")
    second = fetch_public_document("https://example.com/b")
    assert len(deduplicate_documents([first, second])) == 1
