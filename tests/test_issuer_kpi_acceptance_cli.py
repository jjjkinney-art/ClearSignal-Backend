from app.schemas import RetrievedEvidence
from app.services.issuer_kpi_evidence import extract_source_bound_kpis
from app.services.official_document_discovery import OfficialDocumentCandidate
from app.services.public_document_ingestion import (
    DocumentLink, DocumentPage, PublicDocument, PublicDocumentError,
)
from scripts.issuer_kpi_acceptance import CanaryCase, run_case


def _filing(url="https://www.sec.gov/Archives/edgar/data/1/2/report.htm"):
    return RetrievedEvidence(
        title="Acme 8-K", source="SEC EDGAR", summary="Filed.",
        timestamp="2026-07-25", url=url, document_type="8-K",
    )


def _document(text, *, url=None, links=()):
    url = url or "https://www.sec.gov/Archives/edgar/data/1/2/report.htm"
    return PublicDocument(
        requested_url=url, final_url=url, content_type="text/html",
        content_hash="a" * 64, byte_count=100, title="Acme results", text=text,
        sections=(), pages=(DocumentPage(1, 0, len(text), text),), links=links,
        extraction_method="html", text_ready=True,
        accessed_at="2026-09-29T00:00:00+00:00", publisher="SEC EDGAR",
        published_at="2026-07-25", document_type="8-K",
        source_type="regulatory_filing", source_tier="primary",
    )


def test_reports_question_gate_miss_without_network_calls():
    result = run_case(
        CanaryCase("BAD", "ACME", "How did it perform?"),
        user_agent="ClearSignal test",
        filing_discovery=lambda *a, **k: (_ for _ in ()).throw(AssertionError()),
    )
    assert result.status == "miss"
    assert result.terminal_stage == "question_gate"


def test_reports_filing_discovery_provider_error():
    result = run_case(
        CanaryCase("ACME", "ACME", "What was paid memberships?"),
        user_agent="ClearSignal test",
        filing_discovery=lambda *a, **k: (_ for _ in ()).throw(RuntimeError()),
    )
    assert result.status == "error"
    assert result.terminal_stage == "filing_discovery"


def test_reports_document_retrieval_miss_with_fixed_category():
    result = run_case(
        CanaryCase("ACME", "ACME", "What was paid memberships?"),
        user_agent="ClearSignal test",
        filing_discovery=lambda *a, **k: [_filing()],
        document_fetch=lambda *a, **k: (_ for _ in ()).throw(
            PublicDocumentError("sensitive raw failure"),
        ),
    )
    assert result.status == "miss"
    assert result.terminal_stage == "document_retrieval"
    retrieval = next(stage for stage in result.stages if stage.name == "document_retrieval")
    assert retrieval.status == "miss"
    assert "sensitive raw failure" not in str(result)


def test_passes_on_primary_source_bound_evidence_and_preserves_budget():
    calls = {}

    def discovery(ticker, **kwargs):
        calls.update(ticker=ticker, **kwargs)
        return [_filing()]

    result = run_case(
        CanaryCase("ACME", "ACME", "What was paid memberships?"),
        user_agent="ClearSignal test", filing_discovery=discovery,
        document_fetch=lambda *a, **k: _document("Paid memberships were 80 million."),
    )
    assert result.status == "pass"
    assert result.evidence_count == 1
    assert result.documents_attempted == 1
    assert calls["prefer_results"] is True
    assert calls["limit"] == 2


def test_follows_official_exhibit_and_passes_bound_evidence():
    exhibit_url = "https://www.sec.gov/Archives/edgar/data/1/2/exhibit991.htm"
    primary = _document(
        "No requested KPI.", links=(DocumentLink(exhibit_url, "EX-99.1"),),
    )
    exhibit = _document("Total MAUs 778 million.", url=exhibit_url)

    def fetch(url, **kwargs):
        return primary if url.endswith("report.htm") else exhibit

    def discover(*args, **kwargs):
        return [OfficialDocumentCandidate(
            url=exhibit_url, title="EX-99.1", document_type="sec_exhibit",
            source_type="regulatory_filing", source_tier="primary",
            publisher="SEC EDGAR", published_at="2026-07-25",
            discovery_reason="official SEC archive link",
        )]

    result = run_case(
        CanaryCase("MUSIC", "MUSIC", "What were monthly active users?"),
        user_agent="ClearSignal test",
        filing_discovery=lambda *a, **k: [_filing()],
        document_fetch=fetch, document_discovery=discover,
        extractor=extract_source_bound_kpis,
    )
    assert result.status == "pass"
    assert result.documents_attempted == 2
    assert result.evidence[0]["url"] == exhibit_url


def test_ambiguous_metric_fails_closed_at_extraction():
    text = "Paid memberships were 80 million. Paid memberships were 75 million last year."
    result = run_case(
        CanaryCase("ACME", "ACME", "What was paid memberships?"),
        user_agent="ClearSignal test",
        filing_discovery=lambda *a, **k: [_filing()],
        document_fetch=lambda *a, **k: _document(text),
    )
    assert result.status == "miss"
    stage = next(value for value in result.stages if value.name == "source_bound_extraction")
    assert stage.detail == "no_unambiguous_requested_metric"
