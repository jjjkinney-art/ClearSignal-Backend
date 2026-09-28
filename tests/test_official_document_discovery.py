from dataclasses import replace

from app.services.official_document_discovery import discover_official_documents
from app.services.public_document_ingestion import DocumentLink, PublicDocument


def _index(*links: DocumentLink, url="https://investor.acme.com/results") -> PublicDocument:
    return PublicDocument(
        requested_url=url, final_url=url, content_type="text/html",
        content_hash="a" * 64, byte_count=100, title="Acme Results", text="Results",
        sections=(), pages=(), links=links, extraction_method="html", text_ready=True,
        accessed_at="2026-09-28T00:00:00+00:00", publisher="Acme Investor Relations",
    )


def test_discovers_and_classifies_only_allowlisted_official_documents():
    document = _index(
        DocumentLink("https://cdn.investor.acme.com/q2-results.pdf", "Q2 Financial Results"),
        DocumentLink("https://investor.acme.com/q2-presentation.pdf", "Investor Presentation"),
        DocumentLink("https://evil.example/q2-results.pdf", "Q2 Financial Results"),
        DocumentLink("https://investor.acme.com/random.pdf", "Download"),
    )

    candidates = discover_official_documents(
        document, issuer_hosts=("investor.acme.com",), published_at="2026-07-25",
    )

    assert [(item.document_type, item.source_type) for item in candidates] == [
        ("earnings_release", "issuer_release"),
        ("investor_presentation", "investor_presentation"),
    ]
    assert all(item.source_tier == "primary" for item in candidates)
    assert all(item.published_at == "2026-07-25" for item in candidates)


def test_accepts_strict_sec_archive_document_but_rejects_sec_lookalikes():
    document = _index(
        DocumentLink(
            "https://www.sec.gov/Archives/edgar/data/123/0001/exhibit991.htm",
            "Exhibit 99.1 Earnings Release",
        ),
        DocumentLink("https://sec.gov.example/Archives/edgar/data/123/1/a.htm", "Earnings Release"),
        DocumentLink("https://www.sec.gov/news/press-release.pdf", "Press Release"),
    )

    candidates = discover_official_documents(document, issuer_hosts=("investor.acme.com",))

    assert len(candidates) == 1
    assert candidates[0].source_type == "regulatory_filing"
    assert candidates[0].publisher == "SEC EDGAR"


def test_rejects_untrusted_index_and_invalid_limits():
    document = _index(DocumentLink("https://investor.acme.com/release.pdf", "Press Release"))
    assert discover_official_documents(
        replace(document, final_url="https://search.example/results"),
        issuer_hosts=("investor.acme.com",),
    ) == []

    for limit in (0, 101):
        try:
            discover_official_documents(document, issuer_hosts=("investor.acme.com",), limit=limit)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid limit should fail")
