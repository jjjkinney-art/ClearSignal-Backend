from app.schemas import RetrievedEvidence
from app.services.evidence_references import build_evidence_references


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
    assert refs == [{
        "id": "E1",
        "title": "Apple update",
        "source": "NewsAPI / Reuters",
        "published_at": "2026-09-27",
        "url": "https://example.com/apple",
        "inspectable": True,
        "source_type": "news",
        "source_tier": "reputable_secondary",
        "claim_type": "unknown",
        "document_type": None,
        "reporting_period_start": None,
        "reporting_period_end": None,
        "filed_at": None,
        "section": None,
        "page": None,
        "extraction_method": "unknown",
    }]


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
