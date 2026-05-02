from __future__ import annotations
"""
Evidence layer tests for the AI analyst backend.

These tests focus on the evidence selection and building logic.  They
verify that contexts are deep‑copied during enrichment, that SEC
company facts and filings are normalised correctly, that provider
failures fall back gracefully, and that retrieval provider outputs
populate the context consistently.
"""

import os
import sys
from typing import Any, Dict, List, Optional

import pytest

# Add project root to import path so ``import app`` resolves correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# NOTE: GroundingContext and FilingContext are imported inside each test function
# so that the conftest fixture can restore the real pydantic-backed classes before
# the import binding is created (stub test files overwrite app.schemas at collection
# time, and module-level from-imports would bind to the stub version).
from app.services.evidence_service import build_evidence
import app.services.evidence_service as esvc
import app.providers.sec_client as sec_client
import app.providers.fmp_client as fmp_client
import app.providers.retrieval_provider as retrieval_provider


def test_build_evidence_deepcopy(monkeypatch: pytest.MonkeyPatch) -> None:
    """build_evidence should not mutate the original context and should use deep copy."""
    from app.schemas import GroundingContext
    # Create an initial context with populated lists
    ctx = GroundingContext(company="Tesla")
    ctx.known_facts.append("original fact")
    ctx.recent_events.append("original event")
    ctx.macro_context.append("original macro")
    ctx.source_notes.append("original source")
    ctx.financials["revenue"] = 42.0

    # Patch all provider functions to return empty/None so build_evidence falls back to placeholders
    monkeypatch.setattr(esvc, "get_company_profile", lambda *args, **kwargs: {})
    monkeypatch.setattr(esvc, "get_market_snapshot", lambda *args, **kwargs: {})
    monkeypatch.setattr(esvc, "get_financial_context", lambda *args, **kwargs: {})
    monkeypatch.setattr(esvc, "get_recent_news", lambda *args, **kwargs: [])
    monkeypatch.setattr(esvc, "get_recent_filings", lambda *args, **kwargs: [])
    monkeypatch.setattr(esvc, "get_company_facts", lambda *args, **kwargs: {})
    monkeypatch.setattr(esvc, "get_public_context", lambda *args, **kwargs: None)
    monkeypatch.setattr(esvc, "get_document_context", lambda *args, **kwargs: None)

    # Build evidence with no sources selected (should only copy context and apply placeholders)
    new_ctx = build_evidence("Tesla", None, None, [], ctx)
    # Ensure a new object is returned and the original is unmodified
    assert new_ctx is not ctx
    assert ctx.known_facts == ["original fact"]
    assert ctx.recent_events == ["original event"]
    assert ctx.macro_context == ["original macro"]
    assert ctx.source_notes == ["original source"]
    # Ensure placeholders are added to new context when lists are empty
    assert new_ctx.known_facts != []
    assert new_ctx.recent_events != []
    assert new_ctx.macro_context != []
    assert new_ctx.source_notes != []


def test_sec_normalization(monkeypatch: pytest.MonkeyPatch) -> None:
    """SEC filings and company facts should be normalised into the context consistently."""
    # Prepare fake filings list
    fake_filings: List[Dict[str, Any]] = [
        {"filing_type": "10-K", "filing_date": "2025-03-01", "title": "10-K Annual report", "url": "http://example.com/1"},
        {"filing_type": "10-Q", "filing_date": "2024-11-15", "title": "10-Q Quarterly report", "url": "http://example.com/2"},
    ]
    # Fake company facts
    fake_facts = {"entityName": "Tesla, Inc.", "cik": "0001318605", "ticker": "TSLA"}

    # Patch SEC provider functions.  Note: build_evidence imports these
    # functions into the evidence_service namespace, so we patch both
    # the provider and the evidence_service aliases.
    monkeypatch.setattr(sec_client, "get_recent_filings", lambda *args, **kwargs: fake_filings)
    monkeypatch.setattr(sec_client, "get_company_facts", lambda *args, **kwargs: fake_facts)
    monkeypatch.setattr(esvc, "get_recent_filings", lambda *args, **kwargs: fake_filings)
    monkeypatch.setattr(esvc, "get_company_facts", lambda *args, **kwargs: fake_facts)
    # Patch other providers to no-op
    monkeypatch.setattr(esvc, "get_company_profile", lambda *args, **kwargs: {})
    monkeypatch.setattr(esvc, "get_market_snapshot", lambda *args, **kwargs: {})
    monkeypatch.setattr(esvc, "get_financial_context", lambda *args, **kwargs: {})
    monkeypatch.setattr(esvc, "get_recent_news", lambda *args, **kwargs: [])
    monkeypatch.setattr(esvc, "get_public_context", lambda *args, **kwargs: None)
    monkeypatch.setattr(esvc, "get_document_context", lambda *args, **kwargs: None)

    from app.schemas import GroundingContext, FilingContext
    ctx = GroundingContext(company="Tesla", ticker="1318605")
    enriched = build_evidence("Tesla", ctx.ticker, "What are Tesla's filings?", ["sec"], ctx)
    # Verify filings are converted to FilingContext entries
    assert len(enriched.filings_context) == len(fake_filings)
    for fc, src in zip(enriched.filings_context, fake_filings):
        assert isinstance(fc, FilingContext)
        assert fc.filing_type == src["filing_type"]
        assert fc.filing_date == src["filing_date"]
        assert fc.title == src["title"]
        # URL may not be present in filing context; ensure at least attribute exists
        assert hasattr(fc, "url")
    # Verify company facts appear in known_facts
    facts_summary = [f for f in enriched.known_facts if "SEC lists entity name" in f]
    assert facts_summary and "Tesla, Inc." in facts_summary[0]
    # Source notes should record both filings and facts
    assert "SEC EDGAR recent filings" in enriched.source_notes
    assert "SEC company facts" in enriched.source_notes


def test_provider_partial_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """build_evidence should gracefully handle provider failures and add placeholders."""
    # Force all provider functions to raise exceptions
    def raise_exc(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("provider failure")

    monkeypatch.setattr(esvc, "get_company_profile", raise_exc)
    monkeypatch.setattr(esvc, "get_market_snapshot", raise_exc)
    monkeypatch.setattr(esvc, "get_financial_context", raise_exc)
    monkeypatch.setattr(esvc, "get_recent_news", raise_exc)
    # Patch both the provider module AND the service-level binding (from-import)
    monkeypatch.setattr(esvc, "get_recent_filings", raise_exc)
    monkeypatch.setattr(esvc, "get_company_facts", raise_exc)
    monkeypatch.setattr(sec_client, "get_recent_filings", raise_exc)
    monkeypatch.setattr(sec_client, "get_company_facts", raise_exc)
    monkeypatch.setattr(esvc, "get_public_context", raise_exc)
    monkeypatch.setattr(esvc, "get_document_context", raise_exc)
    monkeypatch.setattr(retrieval_provider, "get_public_context", raise_exc)
    monkeypatch.setattr(retrieval_provider, "get_document_context", raise_exc)

    from app.schemas import GroundingContext
    ctx = GroundingContext(company="Acme")
    enriched = build_evidence("Acme", None, "Explain Acme", ["fmp", "sec", "retrieval"], ctx)
    # When all providers fail, placeholders should be present
    assert enriched.company_profile is not None  # default instance
    assert enriched.financial_context is not None
    assert enriched.market_snapshot is not None
    assert enriched.filings_context == []
    assert enriched.known_facts  # placeholder
    assert enriched.recent_events  # placeholder
    assert enriched.source_notes  # placeholder


def test_retrieval_provider_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retrieval provider outputs should populate recent_events with structured strings."""
    # Fake retrieval outputs
    public_ctx = ["Headline A (2025-01-01)", "Headline B (2025-01-02)"]
    doc_ctx = ["Doc summary 1", "Doc summary 2"]
    monkeypatch.setattr(retrieval_provider, "get_public_context", lambda *args, **kwargs: public_ctx)
    monkeypatch.setattr(retrieval_provider, "get_document_context", lambda *args, **kwargs: doc_ctx)
    # Patch aliases imported into evidence service
    monkeypatch.setattr(esvc, "get_public_context", lambda *args, **kwargs: public_ctx)
    monkeypatch.setattr(esvc, "get_document_context", lambda *args, **kwargs: doc_ctx)
    # Disable other providers
    monkeypatch.setattr(esvc, "get_company_profile", lambda *args, **kwargs: {})
    monkeypatch.setattr(esvc, "get_market_snapshot", lambda *args, **kwargs: {})
    monkeypatch.setattr(esvc, "get_financial_context", lambda *args, **kwargs: {})
    monkeypatch.setattr(esvc, "get_recent_news", lambda *args, **kwargs: [])
    monkeypatch.setattr(sec_client, "get_recent_filings", lambda *args, **kwargs: [])
    monkeypatch.setattr(sec_client, "get_company_facts", lambda *args, **kwargs: {})

    # Also stub enterprise retrieval so it falls back to direct provider calls
    try:
        import app.enterprise.retrieval as _ent_ret
        monkeypatch.setattr(_ent_ret, "retrieve", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("stub")))
    except Exception:
        pass

    from app.schemas import GroundingContext
    ctx = GroundingContext(company="Foo")
    enriched = build_evidence("Foo", None, "What's new?", ["retrieval"], ctx)
    # Public context entries must be in recent_events regardless of retrieval path
    for item in public_ctx:
        assert item in enriched.recent_events, \
            f"Public item {item!r} missing from recent_events: {enriched.recent_events}"
    # Source notes should record retrieval was used (wording may differ by path)
    has_retrieval_note = any(
        s in enriched.source_notes
        for s in ("Public news retrieval", "Centralized retrieval", "Document context retrieval")
    )
    assert has_retrieval_note, f"No retrieval source note found: {enriched.source_notes}"


def test_final_evidence_assembly(monkeypatch: pytest.MonkeyPatch) -> None:
    """build_evidence should assemble multiple evidence sources into a consistent context."""
    # Fake FMP data
    fmp_profile = {"name": "Foo Inc", "industry": "Tech", "sector": "Technology", "description": "A tech company.", "ceo": "Jane Doe", "website": "https://foo.com", "ticker": "FOO"}
    fmp_snapshot = {"price": 123.45, "volume": 1000000, "market_cap": 123450000.0, "high_52_week": 150.0, "low_52_week": 80.0}
    fmp_financial = {"revenue": 1000.0, "net_income": 100.0, "ebitda": 150.0, "eps": 2.5}
    fmp_news = []
    # Fake SEC data
    sec_filings = [{"filing_type": "10-K", "filing_date": "2025-01-15", "title": "Annual report", "url": "http://example.com/k"}]
    sec_facts = {"entityName": "Foo Inc", "cik": "0000123456"}
    # Fake retrieval data
    retrieval_public = ["News (2025-01-01)"]
    retrieval_doc = None

    # Patch providers accordingly
    # Patch FMP provider functions and their aliases in evidence_service
    monkeypatch.setattr(fmp_client, "get_company_profile", lambda *args, **kwargs: fmp_profile)
    monkeypatch.setattr(fmp_client, "get_market_snapshot", lambda *args, **kwargs: fmp_snapshot)
    monkeypatch.setattr(fmp_client, "get_financial_context", lambda *args, **kwargs: fmp_financial)
    monkeypatch.setattr(fmp_client, "get_recent_news", lambda *args, **kwargs: fmp_news)
    monkeypatch.setattr(esvc, "get_company_profile", lambda *args, **kwargs: fmp_profile)
    monkeypatch.setattr(esvc, "get_market_snapshot", lambda *args, **kwargs: fmp_snapshot)
    monkeypatch.setattr(esvc, "get_financial_context", lambda *args, **kwargs: fmp_financial)
    monkeypatch.setattr(esvc, "get_recent_news", lambda *args, **kwargs: fmp_news)
    # Patch SEC provider functions and their aliases in evidence_service
    monkeypatch.setattr(sec_client, "get_recent_filings", lambda *args, **kwargs: sec_filings)
    monkeypatch.setattr(sec_client, "get_company_facts", lambda *args, **kwargs: sec_facts)
    monkeypatch.setattr(esvc, "get_recent_filings", lambda *args, **kwargs: sec_filings)
    monkeypatch.setattr(esvc, "get_company_facts", lambda *args, **kwargs: sec_facts)
    # Patch retrieval provider functions and their aliases in evidence_service
    monkeypatch.setattr(retrieval_provider, "get_public_context", lambda *args, **kwargs: retrieval_public)
    monkeypatch.setattr(retrieval_provider, "get_document_context", lambda *args, **kwargs: retrieval_doc)
    monkeypatch.setattr(esvc, "get_public_context", lambda *args, **kwargs: retrieval_public)
    monkeypatch.setattr(esvc, "get_document_context", lambda *args, **kwargs: retrieval_doc)
    # Bypass governance so FMP calls are not blocked (no real API key in test env)
    monkeypatch.setattr(esvc, "_check_provider_access", lambda *a, **kw: True)
    # Also stub enterprise retrieval to fall back to direct provider calls
    try:
        import app.enterprise.retrieval as _ent_ret
        monkeypatch.setattr(_ent_ret, "retrieve", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("stub")))
    except Exception:
        pass
    # Build evidence across all sources
    from app.schemas import GroundingContext
    ctx = GroundingContext(company="Foo", ticker="123456")
    enriched = build_evidence("Foo", ctx.ticker, "Comprehensive", ["fmp", "sec", "retrieval"], ctx)
    # Company profile should reflect FMP profile
    assert enriched.company_profile and enriched.company_profile.name == fmp_profile["name"]
    # Market snapshot fields
    assert enriched.market_snapshot and enriched.market_snapshot.price == fmp_snapshot["price"]
    # Financial context metrics
    assert enriched.financial_context and enriched.financial_context.revenue == fmp_financial["revenue"]
    # Filings context present
    assert enriched.filings_context and enriched.filings_context[0].filing_type == "10-K"
    # Revenue should also appear in legacy financials dict
    assert enriched.financials.get("revenue") == fmp_financial["revenue"]
    # Known facts should include SEC entity name summarisation
    assert any("Foo Inc" in fact for fact in enriched.known_facts)
    # Recent events should include retrieval news
    assert "News (2025-01-01)" in enriched.recent_events
    # Source notes should contain notes for each source
    assert "FMP press releases" in enriched.source_notes or not fmp_news
    assert "SEC EDGAR recent filings" in enriched.source_notes
    assert "SEC company facts" in enriched.source_notes
    # Retrieval note may say "Public news retrieval" or "Centralized retrieval" depending on enterprise mode
    assert any(s in enriched.source_notes for s in ("Public news retrieval", "Centralized retrieval")), \
        f"No retrieval source note: {enriched.source_notes}"


def test_historical_enrichment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Historical storage averages should be incorporated into the context."""
    # Patch provider functions to no‑op so only historical enrichment runs
    monkeypatch.setattr(esvc, "get_company_profile", lambda *args, **kwargs: {})
    monkeypatch.setattr(esvc, "get_market_snapshot", lambda *args, **kwargs: {})
    monkeypatch.setattr(esvc, "get_financial_context", lambda *args, **kwargs: {})
    monkeypatch.setattr(esvc, "get_recent_news", lambda *args, **kwargs: [])
    monkeypatch.setattr(esvc, "get_recent_filings", lambda *args, **kwargs: [])
    monkeypatch.setattr(esvc, "get_company_facts", lambda *args, **kwargs: {})
    monkeypatch.setattr(esvc, "get_public_context", lambda *args, **kwargs: None)
    monkeypatch.setattr(esvc, "get_document_context", lambda *args, **kwargs: None)
    # Patch storage query_records to return fake price and financial histories
    def fake_query_records(table: str, limit: int | None = None, **kwargs) -> List[dict[str, Any]]:
        # Include ticker field so history_ops._filter_by_ticker keeps these records
        if table == "price_history":
            return [
                {"price": 10.0, "ticker": "HistCo"},
                {"price": 20.0, "ticker": "HistCo"},
                {"price": 30.0, "ticker": "HistCo"},
            ]
        if table == "financial_history":
            return [
                {"metric_name": "revenue", "value": 100.0, "ticker": "HistCo"},
                {"metric_name": "revenue", "value": 200.0, "ticker": "HistCo"},
                {"metric_name": "net_income", "value": 50.0, "ticker": "HistCo"},
                {"metric_name": "net_income", "value": 150.0, "ticker": "HistCo"},
            ]
        return []
    monkeypatch.setattr("app.data_pipeline.storage.query_records", fake_query_records)
    ctx = esvc.GroundingContext(company="HistCo")
    enriched = esvc.build_evidence("HistCo", None, None, [], ctx)
    # Average price should be computed (10+20+30)/3 = 20 and stored in financials
    assert abs(enriched.financials.get("avg_price", 0) - 20.0) < 1e-6
    # Average revenue should be (100+200)/2 = 150 and stored in financials
    assert abs(enriched.financials.get("avg_revenue", 0) - 150.0) < 1e-6
    # Source notes should record historical statistics were incorporated
    assert any("historical" in note.lower() for note in enriched.source_notes)