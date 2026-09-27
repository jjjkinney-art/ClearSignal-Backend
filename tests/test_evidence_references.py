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
