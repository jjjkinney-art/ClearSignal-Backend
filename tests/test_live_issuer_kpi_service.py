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
        "limit": 2, "years_back": 2, "prefer_results": True,
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


def test_apple_services_growth_uses_periodic_filing_and_real_table_extraction(monkeypatch):
    from pathlib import Path
    from app.services.public_document_ingestion import _HTMLTableExtractor
    from dataclasses import replace

    url = "https://www.sec.gov/Archives/edgar/data/320193/000032019325000073/aapl-20250628.htm"
    filing = _filing(url).model_copy(update={"document_type": "10-Q", "timestamp": "2025-08-01"})
    parser = _HTMLTableExtractor()
    parser.feed((Path(__file__).parent / "fixtures/apple_services_q3_2025.html").read_text())
    document = replace(_document(url=url), document_type="10-Q", published_at="2025-08-01",
                       extraction_method="html", tables=parser.result())
    calls = []
    monkeypatch.setattr(service.sec_provider, "fetch_recent_filings",
                        lambda *args, **kwargs: calls.append(kwargs) or [filing])
    monkeypatch.setattr(service, "fetch_public_document", lambda *args, **kwargs: document)
    monkeypatch.setattr(service, "extract_source_bound_kpis",
                        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no generic metrics")))
    evidence = service.fetch_live_issuer_kpi_evidence(
        "aapl", question="What is the strongest current public evidence for Apple's services-growth thesis?",
    )
    assert len(evidence) == 2
    assert evidence[0].verified_claims[0]["raw_value"] == 27_423_000_000
    assert calls == [{"forms": ["10-Q", "10-Q/A", "10-K", "10-K/A"],
                     "limit": 2, "years_back": 2, "prefer_results": False}]


def test_services_path_respects_document_budget_and_does_not_follow_exhibits(monkeypatch):
    filings = [_filing(f"https://www.sec.gov/Archives/edgar/data/1/{i}/report.htm").model_copy(
        update={"document_type": "10-Q"}) for i in range(3)]
    monkeypatch.setattr(service.sec_provider, "fetch_recent_filings", lambda *args, **kwargs: filings)
    calls = []
    monkeypatch.setattr(service, "fetch_public_document",
                        lambda url, **kwargs: calls.append(url) or _document("No tables here."))
    monkeypatch.setattr(service, "discover_official_documents",
                        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no exhibit discovery")))
    assert service.fetch_live_issuer_kpi_evidence("AAPL", question="Services growth?", max_documents=2) == []
    assert len(calls) == 2


def test_document_failure_log_exposes_status_without_user_agent_or_url(monkeypatch, caplog):
    import logging
    from app.services.public_document_ingestion import PublicDocumentError
    filing = _filing("https://www.sec.gov/Archives/edgar/data/320193/1/private-path.htm").model_copy(
        update={"document_type": "10-Q"},
    )
    monkeypatch.setattr(service.sec_provider, "fetch_recent_filings", lambda *a, **k: [filing])
    def fail(*a, **k):
        raise PublicDocumentError("public document request failed", failure_kind="http_error",
                                  http_status=403, error_class="HTTPError")
    monkeypatch.setattr(service, "fetch_public_document", fail)
    with caplog.at_level(logging.INFO, logger=service.__name__):
        assert service.fetch_live_issuer_kpi_evidence(
            "AAPL", question="What evidence supports Services growth?",
            user_agent="ClearSignal confidential-contact@example.com",
        ) == []
    assert "failure_kind=http_error" in caplog.text
    assert "http_status=403" in caplog.text
    assert "user_agent_configured=True" in caplog.text
    assert "confidential-contact" not in caplog.text
    assert "private-path" not in caplog.text


def test_services_fetch_failure_fails_closed(monkeypatch):
    from app.services.public_document_ingestion import PublicDocumentError
    monkeypatch.setattr(service.sec_provider, "fetch_recent_filings",
                        lambda *args, **kwargs: [_filing().model_copy(update={"document_type": "10-Q"})])
    monkeypatch.setattr(service, "fetch_public_document",
                        lambda *args, **kwargs: (_ for _ in ()).throw(PublicDocumentError("unavailable")))
    assert service.fetch_live_issuer_kpi_evidence("AAPL", question="Services revenue?") == []
