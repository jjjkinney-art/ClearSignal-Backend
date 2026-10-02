from app.schemas import RetrievedEvidence
from app.services.evidence_references import (
    build_evidence_contract,
    build_evidence_references,
)


def _item(**changes):
    values = {
        "title": "Apple update",
        "source": "NewsAPI / Reuters",
        "summary": "A relevant update.",
        "timestamp": "2026-09-27",
        "relevance_score": 0.9,
    }
    values.update(changes)
    return RetrievedEvidence(**values)


def test_explicit_public_https_url_is_inspectable():
    refs = build_evidence_references([_item(url="https://example.com/apple")])
    assert refs[0]["id"] == "E1"
    assert refs[0]["url"] == "https://example.com/apple"
    assert refs[0]["inspectable"] is True
    assert refs[0]["source_type"] == "news"
    assert refs[0]["source_tier"] == "reputable_secondary"
    assert refs[0]["freshness_status"] in {"current", "stale"}
    assert refs[0]["conflict_group_id"] is None


def test_legacy_news_source_marker_remains_inspectable():
    refs = build_evidence_references([
        _item(summary="Update. [Source: https://example.com/story]")
    ])
    assert refs[0]["url"] == "https://example.com/story"
    assert refs[0]["inspectable"] is True


def test_credentials_and_provider_keys_are_never_exposed():
    refs = build_evidence_references([
        _item(url="https://user:pass@example.com/story"),
        _item(title="API request", url="https://example.com/data?apikey=secret"),
        _item(title="Plain HTTP", url="http://example.com/story"),
    ])
    assert all(ref["url"] is None for ref in refs)
    assert all(ref["inspectable"] is False for ref in refs)


def test_reference_metadata_is_available_without_a_url_and_deduplicated():
    item = _item(url=None)
    refs = build_evidence_references([item, item])
    assert len(refs) == 1
    assert refs[0]["title"] == "Apple update"
    assert refs[0]["source"] == "NewsAPI / Reuters"
    assert refs[0]["inspectable"] is False


def test_explicit_primary_source_metadata_is_preserved():
    refs = build_evidence_references([_item(
        source="SEC EDGAR — structured XBRL fact",
        source_type="regulatory_filing", source_tier="primary",
        claim_type="reported_fact", document_type="10-Q",
        reporting_period_start="2026-01-01", reporting_period_end="2026-03-31",
        filed_at="2026-05-01", extraction_method="structured_xbrl",
        url="https://www.sec.gov/Archives/edgar/data/320193/example-index.htm",
    )])
    assert refs[0]["source_type"] == "regulatory_filing"
    assert refs[0]["source_tier"] == "primary"
    assert refs[0]["claim_type"] == "reported_fact"
    assert refs[0]["document_type"] == "10-Q"
    assert refs[0]["reporting_period_end"] == "2026-03-31"
    assert refs[0]["extraction_method"] == "structured_xbrl"


def test_legacy_source_classification_is_conservative():
    refs = build_evidence_references([
        _item(source="SEC EDGAR", title="Filing discovery"),
        _item(source="FRED", title="Macro series"),
        _item(source="Unknown blog", title="Unverified commentary"),
    ])
    assert refs[0]["claim_type"] == "filing_metadata"
    assert refs[0]["source_tier"] == "primary"
    assert refs[1]["source_type"] == "government_dataset"
    assert refs[1]["source_tier"] == "primary"
    assert refs[2]["source_type"] == "unknown"
    assert refs[2]["source_tier"] == "unverified"


def _claim(value, *, accession):
    return {
        "ticker": "AAPL", "metric": "us-gaap:Revenues",
        "period_end": "2026-06-30", "period": "quarter ended 2026-06-30",
        "scope": "consolidated", "unit": "USD", "raw_value": value,
        "document_ref": {"reference_id": f"sec:{accession}"},
    }


def test_contract_classifies_current_and_stale_evidence_at_fixed_boundary():
    refs, integrity = build_evidence_contract([
        _item(title="Recent", timestamp="2026-09-28"),
        _item(title="Old", timestamp="2026-08-01"),
    ], evaluated_at="2026-10-02T00:00:00Z")

    assert [ref["freshness_status"] for ref in refs] == ["current", "stale"]
    assert integrity["overall_status"] == "mixed"
    assert integrity["counts"]["current"] == 1
    assert integrity["counts"]["stale"] == 1


def test_material_claim_conflict_is_visible_and_fail_closed():
    refs, integrity = build_evidence_contract([
        _item(
            title="Filing A", source="SEC EDGAR — structured XBRL fact",
            source_type="regulatory_filing", source_tier="primary",
            claim_type="reported_fact", document_type="10-Q",
            filed_at="2026-08-01", verified_claims=[_claim(100, accession="a")],
        ),
        _item(
            title="Filing B", source="SEC EDGAR — structured XBRL fact",
            source_type="regulatory_filing", source_tier="primary",
            claim_type="reported_fact", document_type="10-Q",
            filed_at="2026-08-02", verified_claims=[_claim(110, accession="b")],
        ),
    ], evaluated_at="2026-10-02T00:00:00Z")

    assert integrity["overall_status"] == "conflicting"
    assert integrity["has_material_conflict"] is True
    assert len(integrity["conflicts"]) == 1
    assert {ref["freshness_status"] for ref in refs} == {"conflicting"}
    assert refs[0]["conflict_group_id"] == refs[1]["conflict_group_id"]


def test_amendment_supersedes_original_instead_of_creating_false_conflict():
    refs, integrity = build_evidence_contract([
        _item(
            title="Original", source="SEC EDGAR — structured XBRL fact",
            source_type="regulatory_filing", source_tier="primary",
            claim_type="reported_fact", document_type="10-Q",
            filed_at="2026-08-01", verified_claims=[_claim(100, accession="a")],
        ),
        _item(
            title="Amendment", source="SEC EDGAR — structured XBRL fact",
            source_type="regulatory_filing", source_tier="primary",
            claim_type="reported_fact", document_type="10-Q/A",
            filed_at="2026-08-15", verified_claims=[_claim(110, accession="b")],
        ),
    ], evaluated_at="2026-10-02T00:00:00Z")

    assert integrity["has_material_conflict"] is False
    assert refs[0]["freshness_status"] == "superseded"
    assert refs[1]["supersedes_reference_id"] == "E1"


def test_unavailable_source_state_is_explicit():
    refs, integrity = build_evidence_contract([
        _item(
            timestamp="", availability_status="unavailable",
            status_reason="publisher removed the document",
        ),
    ], evaluated_at="2026-10-02T00:00:00Z")

    assert refs[0]["freshness_status"] == "unavailable"
    assert refs[0]["status_reason"] == "publisher removed the document"
    assert integrity["overall_status"] == "unavailable"


def test_source_after_historical_boundary_is_not_admitted_as_current():
    refs, integrity = build_evidence_contract([
        _item(timestamp="2026-09-28"),
    ], as_of="2026-08-31T23:59:59Z", evaluated_at="2026-10-02T00:00:00Z")

    assert refs[0]["freshness_status"] == "unavailable"
    assert refs[0]["status_reason"] == "evidence timestamp is after analysis boundary"
    assert integrity["as_of"] == "2026-08-31T23:59:59Z"
    assert integrity["evaluated_at"] == "2026-10-02T00:00:00+00:00"
