from app.schemas import RetrievedEvidence
from app.services import live_issuer_kpi_service as service
from app.services.public_document_ingestion import DocumentLink, DocumentPage, PublicDocument


def _filing(url="https://www.sec.gov/Archives/edgar/data/1/2/report.htm"):
    return RetrievedEvidence(
        title="Acme Current Report (8-K)", source="SEC EDGAR", summary="Filed.",
        timestamp="2026-07-25", url=url, document_type="8-K",
    )


def _document(text="Paid memberships increased to 80.2 million.", *, links=(), url=None):
    url = url or "https://www.sec.gov/Archives/edgar/data/1/2/report.htm"
    return PublicDocument(
        requested_url=url,
        final_url=url,
        content_type="text/html", content_hash="a" * 64, byte_count=100,
        title="Acme 8-K", text=text, sections=(),
        pages=(DocumentPage(1, 0, len(text), text),), links=links,
        extraction_method="pdf_text", text_ready=True,
        accessed_at="2026-09-29T00:00:00+00:00", publisher="SEC EDGAR",
        published_at="2026-07-25", document_type="8-K",
        source_type="regulatory_filing", source_tier="primary",
    )


def test_question_gate_selects_only_explicit_supported_kpis():
    assert service.requested_issuer_kpi_aliases("What was NFLX paid memberships?") == {
        "paid memberships": ("paid memberships", "paid members"),
    }
    assert service.requested_issuer_kpi_aliases("How did the company perform?") == {}
    assert service.requested_issuer_kpi_aliases("Explain users and sales") == {}
    assert "remaining performance obligations" in service.requested_issuer_kpi_aliases(
        "What was Salesforce's current remaining performance obligation?",
    )


def test_fetches_current_report_and_returns_only_bound_evidence(monkeypatch):
    calls = {}

    def filings(ticker, **kwargs):
        calls.update(ticker=ticker, **kwargs)
        return [_filing()]

    monkeypatch.setattr(service.sec_provider, "fetch_recent_filings", filings)
    monkeypatch.setattr(service, "fetch_public_document", lambda *args, **kwargs: _document())

    evidence = service.fetch_live_issuer_kpi_evidence(
        "nflx", question="What were paid memberships?", user_agent="ClearSignal test",
    )

    assert len(evidence) == 1
    assert evidence[0].title == "NFLX paid memberships: 80.2 million"
    assert evidence[0].page == 1
    assert evidence[0].source_type == "regulatory_filing"
    assert calls == {
        "ticker": "NFLX", "forms": ["8-K", "8-K/A", "6-K", "6-K/A"],
        "limit": 2, "years_back": 2,
    }


def test_skips_unsupported_questions_and_unbound_documents(monkeypatch):
    monkeypatch.setattr(
        service.sec_provider, "fetch_recent_filings",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not fetch")),
    )
    assert service.fetch_live_issuer_kpi_evidence("NFLX", question="How did it perform?") == []

    monkeypatch.setattr(service.sec_provider, "fetch_recent_filings", lambda *args, **kwargs: [_filing()])
    monkeypatch.setattr(service, "fetch_public_document", lambda *args, **kwargs: _document("No KPI here."))
    assert service.fetch_live_issuer_kpi_evidence(
        "NFLX", question="What were paid memberships?",
    ) == []


def test_deduplicates_metric_across_newest_first_filings(monkeypatch):
    monkeypatch.setattr(
        service.sec_provider, "fetch_recent_filings", lambda *args, **kwargs: [_filing(), _filing()],
    )
    fetches = []

    def fetch(*args, **kwargs):
        fetches.append(args[0])
        return _document()

    monkeypatch.setattr(service, "fetch_public_document", fetch)
    evidence = service.fetch_live_issuer_kpi_evidence(
        "NFLX", question="What were paid memberships?",
    )
    assert len(evidence) == 1
    assert len(fetches) == 1


def test_follows_only_official_sec_exhibit_within_document_budget(monkeypatch):
    exhibit_url = "https://www.sec.gov/Archives/edgar/data/1/2/exhibit991.htm"
    primary = _document(
        "No KPI in the primary filing.",
        links=(DocumentLink(exhibit_url, "EX-99.1"),),
    )
    exhibit = _document(
        url=exhibit_url, text="Paid memberships increased to 80.2 million.",
    )
    monkeypatch.setattr(
        service.sec_provider, "fetch_recent_filings", lambda *args, **kwargs: [_filing()],
    )
    fetches = []

    def fetch(url, **kwargs):
        fetches.append((url, kwargs.get("document_type")))
        return primary if len(fetches) == 1 else exhibit

    monkeypatch.setattr(service, "fetch_public_document", fetch)

    evidence = service.fetch_live_issuer_kpi_evidence(
        "NFLX", question="What were paid memberships?", max_documents=2,
    )

    assert len(evidence) == 1
    assert fetches == [
        ("https://www.sec.gov/Archives/edgar/data/1/2/report.htm", "8-K"),
        (exhibit_url, "sec_exhibit"),
    ]
