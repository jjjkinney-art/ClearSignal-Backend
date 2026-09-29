from __future__ import annotations

import json

import pytest

from scripts import benchmark_point_in_time_audit
from validation.intelligence_benchmark import BenchmarkContractError
from validation.point_in_time_sources import (
    audit_point_in_time_sources,
    normalize_source,
    require_point_in_time_sources,
)


AS_OF = "2025-02-01T21:00:00Z"


def _sec(**overrides):
    value = {
        "source_id": "sec-aapl-10q",
        "source_type": "sec_filing",
        "document_url": "https://www.sec.gov/example",
        "accepted_at": "2025-01-31T21:05:00Z",
        "retrieved_at": "2025-02-02T01:00:00Z",
        "content_sha256": "a" * 64,
        "authoritative": True,
    }
    value.update(overrides)
    return value


def test_sec_filing_uses_acceptance_timestamp():
    source = normalize_source(_sec())
    assert source.timestamp_basis == "accepted_at"
    assert source.version_available_at == "2025-01-31T21:05:00Z"


def test_admits_version_available_at_boundary():
    report = audit_point_in_time_sources(
        as_of=AS_OF, records=[_sec(accepted_at=AS_OF)]
    )
    assert report.passed is True
    assert len(report.admitted) == 1


def test_rejects_filing_accepted_after_boundary():
    report = audit_point_in_time_sources(
        as_of=AS_OF, records=[_sec(accepted_at="2025-02-01T21:00:01Z")]
    )
    assert report.passed is False
    assert report.lookahead_leakage_count == 1
    assert report.findings[0].code == "future_source_version"


def test_later_revision_cannot_borrow_original_publication_date():
    record = _sec(
        accepted_at="2025-01-15T00:00:00Z",
        revision_published_at="2025-02-10T00:00:00Z",
        revision_id="amendment-1",
    )
    source = normalize_source(record)
    assert source.timestamp_basis == "revision_published_at"
    report = audit_point_in_time_sources(as_of=AS_OF, records=[record])
    assert report.passed is False
    assert any(f.code == "future_source_version" for f in report.findings)


@pytest.mark.parametrize(
    ("source_type", "timestamp_field"),
    [
        ("issuer_release", "published_at"),
        ("transcript", "published_at"),
        ("news", "published_at"),
        ("market_data", "observed_at"),
        ("analyst_consensus", "observed_at"),
        ("other", "available_at"),
    ],
)
def test_source_types_require_explicit_semantic_timestamp(source_type, timestamp_field):
    record = _sec(source_type=source_type)
    record.pop("accepted_at")
    with pytest.raises(BenchmarkContractError, match=timestamp_field):
        normalize_source(record)


def test_retrieval_time_is_never_used_as_publication_fallback():
    record = _sec()
    record.pop("accepted_at")
    report = audit_point_in_time_sources(as_of=AS_OF, records=[record])
    assert report.passed is False
    assert report.findings[0].code == "unverifiable_availability"


def test_rejects_retrieval_before_publication():
    report = audit_point_in_time_sources(
        as_of=AS_OF,
        records=[_sec(retrieved_at="2025-01-01T00:00:00Z")],
    )
    assert report.passed is False
    assert any(f.code == "impossible_retrieval_order" for f in report.findings)


def test_later_retrieval_is_safe_only_with_version_hash():
    good = audit_point_in_time_sources(as_of=AS_OF, records=[_sec()])
    bad = audit_point_in_time_sources(
        as_of=AS_OF, records=[_sec(content_sha256="")]
    )
    assert good.passed is True
    assert bad.passed is False
    assert bad.lookahead_leakage_count == 1
    assert any(f.code == "future_retrieval_dependency" for f in bad.findings)


def test_missing_document_identity_is_stop_ship():
    report = audit_point_in_time_sources(
        as_of=AS_OF, records=[_sec(document_url="")]
    )
    assert report.passed is False
    assert any(f.code == "missing_document_identity" for f in report.findings)


def test_secondary_source_is_admitted_with_review_finding():
    record = _sec(
        source_type="news",
        published_at="2025-01-31T20:00:00Z",
        authoritative=False,
    )
    record.pop("accepted_at")
    report = audit_point_in_time_sources(as_of=AS_OF, records=[record])
    assert report.passed is True
    assert len(report.admitted) == 1
    assert report.findings[0].code == "secondary_source_requires_review"


def test_duplicate_source_id_is_rejected():
    report = audit_point_in_time_sources(as_of=AS_OF, records=[_sec(), _sec()])
    assert report.passed is False
    assert any(f.code == "duplicate_source_id" for f in report.findings)


def test_admitted_sources_are_sorted_deterministically():
    records = [_sec(source_id="z"), _sec(source_id="a")]
    report = audit_point_in_time_sources(as_of=AS_OF, records=records)
    assert [source.source_id for source in report.admitted] == ["a", "z"]


def test_require_helper_fails_closed_with_codes():
    with pytest.raises(BenchmarkContractError, match="future_source_version"):
        require_point_in_time_sources(
            as_of=AS_OF,
            records=[_sec(accepted_at="2025-02-02T00:00:00Z")],
        )


def test_cli_passes_clean_manifest(tmp_path, capsys):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"as_of": AS_OF, "sources": [_sec()]}))
    assert benchmark_point_in_time_audit.main([str(path)]) == 0
    assert "integrity: PASS" in capsys.readouterr().out


def test_cli_fails_future_source_manifest(tmp_path, capsys):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({
        "as_of": AS_OF,
        "sources": [_sec(accepted_at="2025-02-02T00:00:00Z")],
    }))
    assert benchmark_point_in_time_audit.main([str(path)]) == 1
    output = capsys.readouterr().out
    assert "integrity: FAIL" in output
    assert "future_source_version" in output

