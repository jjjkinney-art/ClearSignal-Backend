import hashlib
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


def test_opt_in_inline_facts_share_the_bounded_download_hash(monkeypatch):
    cik, concepts = '320193', ('Revenues',)
    url = 'https://www.sec.gov/Archives/edgar/data/320193/000032019326000001/company.htm'
    body = b'''<html xmlns="http://www.w3.org/1999/xhtml"
        xmlns:x="http://www.xbrl.org/2003/instance" xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
        xmlns:g="http://fasb.org/us-gaap/2026" xmlns:iso="http://www.xbrl.org/2003/iso4217">
        <body><ix:header><ix:resources><x:context id="c"><x:entity>
        <x:identifier scheme="http://www.sec.gov/CIK">320193</x:identifier></x:entity>
        <x:period><x:startDate>2026-04-01</x:startDate><x:endDate>2026-06-30</x:endDate></x:period>
        </x:context><x:unit id="usd"><x:measure>iso:USD</x:measure></x:unit></ix:resources></ix:header>
        <ix:nonFraction id="f" name="g:Revenues" contextRef="c" unitRef="usd" decimals="0">100</ix:nonFraction>
        </body></html>'''
    response = _Response(body)
    monkeypatch.setattr(requests, 'get', lambda *args, **kwargs: response)
    document = fetch_public_document(url, publisher='SEC EDGAR', published_at='2026-07-28',
        document_type='10-Q', source_type='regulatory_filing', source_tier='primary',
        sec_periodic_limits=True, extract_tables=False, inline_fact_cik=cik,
        inline_fact_concepts=concepts)
    assert len(document.inline_xbrl_facts) == 1
    assert document.content_hash == hashlib.sha256(body).hexdigest()
    assert response.closed
    with pytest.raises(PublicDocumentError, match='SEC periodic limits'):
        fetch_public_document(url, inline_fact_cik=cik)
    assert response.closed is True


@pytest.mark.parametrize("status", [403, 404, 429, 503])
def test_http_failure_preserves_status_without_sensitive_exception_text(monkeypatch, status):
    response = _Response(status=status)
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: response)
    with pytest.raises(PublicDocumentError, match="public document request failed") as caught:
        fetch_public_document("https://example.com/report")
    error = caught.value
    assert error.failure_kind == "http_error"
    assert error.http_status == status
    assert error.error_class == "HTTPError"
    assert response.closed is True


@pytest.mark.parametrize("exc,kind,error_class", [
    (requests.Timeout("secret URL and credential"), "timeout", "Timeout"),
    (requests.exceptions.SSLError("secret URL and credential"), "tls_error", "SSLError"),
    (requests.ConnectionError("secret URL and credential"), "connection_error", "ConnectionError"),
    (requests.RequestException("secret URL and credential"), "request_error", "RequestException"),
])
def test_transport_failure_is_classified_without_logging_secret_details(monkeypatch, exc, kind, error_class):
    def fail(*args, **kwargs):
        raise exc
    monkeypatch.setattr(requests, "get", fail)
    with pytest.raises(PublicDocumentError) as caught:
        fetch_public_document("https://example.com/report")
    error = caught.value
    assert error.failure_kind == kind
    assert error.error_class == error_class
    assert error.http_status is None
    assert "secret" not in str(error)


def test_dns_failure_keeps_safe_classification(monkeypatch):
    def fail(*args, **kwargs):
        raise socket.gaierror("secret resolver detail")
    monkeypatch.setattr(socket, "getaddrinfo", fail)
    with pytest.raises(PublicDocumentError) as caught:
        fetch_public_document("https://example.com/report")
    assert caught.value.failure_kind == "dns_error"
    assert caught.value.error_class == "DNSLookupError"
    assert "secret" not in str(caught.value)


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


def test_sec_periodic_allowance_keeps_closing_section_and_full_byte_hash(monkeypatch):
    from app.services.public_document_ingestion import MAX_SEC_PERIODIC_CHARS
    body = (b'<html><body>' + b' ' * MAX_DOCUMENT_BYTES + b'<p>' +
            b'context ' * 16000 +
            b'Item 1A. Risk Factors Cloud capacity could harm revenue. Item 1B. Unresolved Staff Comments</p></body></html>')
    response = _Response(body, headers={'Content-Length': str(len(body))})
    monkeypatch.setattr(requests, 'get', lambda *a, **k: response)
    doc = fetch_public_document(
        'https://www.sec.gov/Archives/edgar/data/789019/000119312526323660/msft-20260630.htm',
        publisher='SEC EDGAR', document_type='10-K', source_type='regulatory_filing',
        source_tier='primary', sec_periodic_limits=True)
    assert 'Item 1B. Unresolved Staff Comments' in doc.text
    assert 120000 < len(doc.text) <= MAX_SEC_PERIODIC_CHARS
    assert doc.content_hash == hashlib.sha256(body).hexdigest()
    assert response.closed


@pytest.mark.parametrize('wrapper', [
    '<ix:header><ix:hidden>{}</ix:hidden></ix:header>',
    '<div hidden><div>{}</div></div>',
    '<div style="display: none !important"><span>{}</span></div>',
    '<div style="color: red; visibility: hidden;">{}</div>',
])
def test_hidden_xbrl_metadata_never_consumes_visible_text_or_tables(monkeypatch, wrapper):
    hidden = '<table><tr><td>Fabricated</td><td>999</td></tr></table>' + 'hidden metadata ' * 18000
    body = ('<html><body>' + wrapper.format(hidden) +
            '<h1>Visible results</h1><ix:nonNumeric>Visible narrative.</ix:nonNumeric>'
            '<table><tr><td>Revenue</td><td><ix:nonFraction>12</ix:nonFraction></td></tr></table>'
            '</body></html>').encode()
    monkeypatch.setattr(requests, 'get', lambda *a, **k: _Response(body))
    doc = fetch_public_document('https://example.com/report.htm')
    assert 'Visible narrative.' in doc.text and 'Revenue 12' in doc.text
    assert 'metadata' not in doc.text and 'Fabricated' not in doc.text
    assert len(doc.tables) == 1 and doc.tables[0].rows == (('Revenue', '12'),)
    assert doc.content_hash == hashlib.sha256(body).hexdigest()


def _periodic_document(monkeypatch, markup):
    body = ('<html><body>' + markup + '</body></html>').encode()
    monkeypatch.setattr(requests, 'get', lambda *a, **k: _Response(body))
    return fetch_public_document(
        'https://www.sec.gov/Archives/edgar/data/789019/000119312526323660/msft-20260630.htm',
        publisher='SEC EDGAR', published_at='2026-07-29', document_type='10-K',
        source_type='regulatory_filing', source_tier='primary', sec_periodic_limits=True), body


def test_late_complete_risk_section_survives_prefix_limit_and_exact_binding(monkeypatch):
    from app.services.issuer_risk_evidence import extract_issuer_risk_evidence, bound_issuer_risk
    from app.services.evidence_references import admit_evidence
    quote = 'Cloud capacity constraints could adversely affect our revenue growth.'
    # TOC and business narrative precede the true section, as in long filings.
    markup = ('<p>Item 1A. Risk Factors 18 Item 1B. Unresolved Staff Comments 40</p>' +
              '<p>' + 'business narrative ' * 20000 + '</p>' +
              '<h2>Item 1A. Risk Factors</h2><p>' + quote + '</p>' +
              '<h2>Item 1B. Unresolved Staff Comments</h2>')
    doc, body = _periodic_document(monkeypatch, markup)
    assert doc.text_selection == 'complete_sec_risk_section'
    assert doc.text_window_start > 360000 and len(doc.text) < 360000
    assert doc.normalized_text_chars_total > 360000
    assert doc.content_hash == hashlib.sha256(body).hexdigest()
    question = 'What operating risk affects Microsoft cloud growth?'
    items = extract_issuer_risk_evidence(doc, ticker='MSFT', question=question)
    admitted, _, _ = admit_evidence(items, evaluated_at='2026-10-06')
    assert len(admitted) == 1
    value = bound_issuer_risk(admitted[0], ticker='MSFT', question=question)
    assert doc.text[value['start_offset']:value['end_offset']] == quote
    assert all(0 <= section.start_offset <= len(doc.text) for section in doc.sections)
    assert doc.sections
    assert all(doc.text[s.start_offset:s.start_offset + len(s.heading)] == s.heading
               for s in doc.sections)


@pytest.mark.parametrize('tail', [
    'Item 1A. Risk Factors Cloud capacity constraints could harm revenue.',
    'Item 1A. Risk Factors ' + 'risk context ' * 26000 + 'Item 1B. Unresolved Staff Comments',
    'See “Item 1A. Risk Factors” Cloud capacity could harm revenue. Item 1B. Unresolved Staff Comments',
    'See Item 1A. Risk Factors Cloud capacity could harm revenue. Item 1B. Unresolved Staff Comments',
], ids=['missing-closing', 'oversized', 'quoted-reference', 'unquoted-reference'])
def test_incomplete_oversized_or_quoted_late_section_is_not_selected(monkeypatch, tail):
    doc, _ = _periodic_document(monkeypatch, '<p>' + 'business narrative ' * 20000 + tail + '</p>')
    assert doc.text_selection == 'prefix' and doc.text_window_start == 0
    assert len(doc.text) == 360000


def test_periodic_window_is_not_selected_for_other_public_documents(monkeypatch):
    body = ('<p>' + 'business narrative ' * 15000 +
            'Item 1A. Risk Factors Cloud capacity could harm revenue. Item 1B. Unresolved Staff Comments</p>').encode()
    monkeypatch.setattr(requests, 'get', lambda *a, **k: _Response(body))
    doc = fetch_public_document('https://example.com/report.htm')
    assert doc.text_selection == 'prefix' and len(doc.text) == 120000


def test_repeated_reference_headings_cannot_trigger_unbounded_risk_window_scan():
    from app.services.sec_risk_sections import complete_risk_window
    text = 'Item 1A. Risk Factors 18 ' * 64
    text += 'Item 1A. Risk Factors Cloud capacity could harm revenue. Item 1B. Unresolved Staff Comments'
    assert complete_risk_window(text) is None


def test_split_heading_and_longer_complete_section_keep_exact_visible_source(monkeypatch):
    from app.services.issuer_risk_evidence import extract_issuer_risk_evidence, bound_issuer_risk
    from app.services.evidence_references import admit_evidence
    quote = 'Cloud capacity constraints could adversely affect our revenue growth.'
    # Authored HTML using the observed split-word layout; not a live filing.
    markup = ('<p>' + 'business narrative ' * 15000 + '</p>' +
              '<h2>Ite<span>m 1A. Ri</span><span>sk Factors</span></h2>' +
              '<p>' + 'Historical context. ' * 8500 + quote + '</p>' +
              '<h2>Ite<span>m 1B. Unres</span><span>olved Staff Comments</span></h2>')
    doc, body = _periodic_document(monkeypatch, markup)
    assert doc.text_selection == 'complete_sec_risk_section'
    assert 160000 < len(doc.text) < 200000
    assert doc.content_hash == hashlib.sha256(body).hexdigest()
    question = 'What operating risk affects Microsoft cloud growth?'
    items, _, _ = admit_evidence(extract_issuer_risk_evidence(doc, ticker='MSFT', question=question),
                                evaluated_at='2026-10-07')
    assert len(items) == 1
    risk = bound_issuer_risk(items[0], ticker='MSFT', question=question)
    assert doc.text[risk['start_offset']:risk['end_offset']] == quote
    assert all(doc.text[s.start_offset:s.start_offset + len(s.heading)] == s.heading
               for s in doc.sections)


@pytest.mark.parametrize('heading', [
    'Item 1A. Ri sk Factors 17',
    'See Ite m 1A. Ri sk Factors',
    'factors discussed in Ite m 1A. Ri sk Factors',
    '“Ite m 1A. Ri sk Factors',
])
def test_split_heading_toc_and_references_do_not_select_late_source(monkeypatch, heading):
    doc, _ = _periodic_document(monkeypatch, '<p>' + 'business narrative ' * 15000 +
        heading + ' Cloud capacity could harm revenue. Ite m 1B. Unres olved Staff Comments</p>')
    assert doc.text_selection == 'prefix' and doc.text_window_start == 0


@pytest.mark.parametrize('url,form', [
    ('https://example.com/report.htm', '10-K'),
    ('https://www.sec.gov/Archives/edgar/data/1/2/report.htm', '10-K'),
    ('https://www.sec.gov/Archives/edgar/data/1/000119312526323660/report.htm', '8-K'),
])
def test_expanded_limits_reject_nonperiodic_or_nonsec_sources_before_network(monkeypatch, url, form):
    monkeypatch.setattr(requests, 'get', lambda *a, **k: pytest.fail('rejected before fetch'))
    with pytest.raises(PublicDocumentError):
        fetch_public_document(url, publisher='SEC EDGAR', document_type=form,
                              source_type='regulatory_filing', source_tier='primary', sec_periodic_limits=True)


def test_expanded_limit_cannot_follow_redirect_to_other_host(monkeypatch):
    response = _Response(status=302, headers={'Location': 'https://example.com/report.htm'})
    calls = []
    monkeypatch.setattr(requests, 'get', lambda *a, **k: calls.append(a[0]) or response)
    with pytest.raises(PublicDocumentError):
        fetch_public_document('https://www.sec.gov/Archives/edgar/data/1/000119312526323660/report.htm',
                              publisher='SEC EDGAR', document_type='10-K', source_type='regulatory_filing',
                              source_tier='primary', sec_periodic_limits=True)
    assert len(calls) == 1 and response.closed


@pytest.mark.parametrize('declared', [False, True])
def test_sec_periodic_bytes_still_have_hard_limit(monkeypatch, declared):
    from app.services.public_document_ingestion import MAX_SEC_PERIODIC_BYTES
    response = _Response(b'x' * (MAX_SEC_PERIODIC_BYTES + 1),
                         headers={'Content-Length': str(MAX_SEC_PERIODIC_BYTES + 1)} if declared else {})
    monkeypatch.setattr(requests, 'get', lambda *a, **k: response)
    with pytest.raises(PublicDocumentError):
        fetch_public_document('https://www.sec.gov/Archives/edgar/data/1/000119312526323660/report.htm',
                              publisher='SEC EDGAR', document_type='10-K', source_type='regulatory_filing',
                              source_tier='primary', sec_periodic_limits=True)
    assert response.closed


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


def test_preserves_visible_table_cells_context_and_source_hash(monkeypatch):
    body = b'''<p>Net sales (dollars in millions):</p>
        <table><tr><th>Three Months Ended</th></tr>
        <tr><td>Services</td><td>27,423</td><td><script>99</script>24,213</td></tr></table>'''
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: _Response(body))
    document = fetch_public_document("https://example.com/report")
    assert len(document.tables) == 1
    table = document.tables[0]
    assert table.context == "Net sales (dollars in millions):"
    assert table.rows == (("Three Months Ended",), ("Services", "27,423", "24,213"))
    assert table.table_number == 1
    assert document.content_hash == hashlib.sha256(body).hexdigest()


@pytest.mark.parametrize("body", [
    b'<table><tr><td>Services</td><td>27,423</td></tr>',
    b'<table><tr><td><table><tr><td>Services</td></tr></table></td></tr></table>',
    b'<table><tr><td rowspan="2">Services</td><td>27,423</td></tr></table>',
    b'<table><tr><td>' + b'x' * 501 + b'</td></tr></table>',
])
def test_ambiguous_or_incomplete_table_structure_is_not_preserved(monkeypatch, body):
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: _Response(body))
    document = fetch_public_document("https://example.com/report")
    assert document.tables == ()
