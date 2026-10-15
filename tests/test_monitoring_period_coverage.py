"""Newer metadata discloses a coverage gap without supplying financial facts."""
import pytest

from app.schemas import InvestmentThesis, RetrievedEvidence
from app.services.decision_monitoring_evidence import build_decision_monitoring
from app.services.source_answer import apply_source_answer_gate
from test_decision_monitoring_evidence import inputs
from test_financial_thesis_foundation import reference


def materials():
    items, refs = inputs()
    listing = RetrievedEvidence(title='Synthetic issuer 10-Q', source='SEC EDGAR',
        summary='Quarterly filing metadata only', timestamp='2025-11-01',
        url='https://www.sec.gov/Archives/edgar/data/320193/000032019325000003/quarter.htm',
        claim_type='filing_metadata', source_type='regulatory_filing', source_tier='primary',
        document_type='10-Q', extraction_method='publisher_feed',
        reporting_period_end='2025-09-30')
    ref = reference(listing, 'E3')
    ref.update(claim_type='filing_metadata', document_type='10-Q', reporting_period_end='2025-09-30')
    return items + [listing], refs + [ref]


def test_newer_listing_is_a_cited_gap_and_never_a_newer_metric():
    items, refs = materials()
    result = build_decision_monitoring('AAPL', items, refs, expected_cik='320193')
    coverage = result['reporting_period_coverage']
    assert coverage['newer_listed_period_end'] == '2025-09-30'
    assert coverage['filing_reference_ids'] == ['E3']
    assert {r['reference_id'] for r in coverage['older_comparisons']} == {'E1', 'E2'}
    assert result['benchmarks'][0]['period_end'] == '2025-06-30'
    assert result['benchmarks'][0]['benchmark_percent'] == '20.0'
    assert '[E3]' in result['answer'] and 'does not verify its financial amounts' in result['answer']
    assert 'financial comparisons for the newer listed filing period' in result['unanswered_parts']
    assert len(result['foundation']['claims']) == 2


@pytest.mark.parametrize('field,value', [
    ('source', 'Unverified provider'), ('source_tier', 'unverified'),
    ('source_type', 'news'), ('claim_type', 'reported_fact'),
    ('extraction_method', 'manual'), ('document_type', '8-K'),
    ('freshness_status', 'conflicting'), ('availability_status', 'unavailable'),
    ('reporting_period_end', '2029-09-30'), ('timestamp', '2029-11-01'),
    ('reporting_period_end', '20250930'), ('reporting_period_end', 'not-a-date'),
    ('url', 'https://www.sec.gov/Archives/edgar/data/123/000032019325000003/quarter.htm'),
    ('url', 'https://example.com/quarter.htm'),
])
def test_unqualified_metadata_cannot_assert_a_newer_period(field, value):
    items, refs = materials()
    setattr(items[-1], field, value)
    assert 'reporting_period_coverage' not in build_decision_monitoring(
        'AAPL', items, refs, expected_cik='320193')


def test_unbound_or_altered_response_reference_cannot_assert_a_gap():
    for key in ('url', 'published_at', 'claim_type', 'document_type', 'reporting_period_end', 'id'):
        items, refs = materials()
        refs[-1][key] = 'unbound'
        assert 'reporting_period_coverage' not in build_decision_monitoring(
            'AAPL', items, refs, expected_cik='320193')


def test_equal_or_older_metadata_does_not_claim_recency_or_a_gap():
    for end in ('2025-06-30', '2025-03-31'):
        items, refs = materials()
        items[-1].reporting_period_end = end; refs[-1]['reporting_period_end'] = end
        result = build_decision_monitoring('AAPL', items, refs, expected_cik='320193')
        assert 'reporting_period_coverage' not in result
        assert 'latest available' not in result['answer']


def test_gate_preserves_coverage_and_investment_boundary_abstention(monkeypatch):
    from app.services.providers import sec_provider
    monkeypatch.setattr(sec_provider, '_load_ticker_cik_map', lambda: {'AAPL': '320193'})
    items, refs = materials()
    thesis = InvestmentThesis(ticker='AAPL', company_name='Apple')
    result = apply_source_answer_gate(thesis, 'Explain decision thresholds', items, references=refs)
    assert result['status'] == 'partial'
    assert result['reporting_period_coverage']['filing_reference_ids'] == ['E3']
    assert 'financial comparisons for the newer listed filing period' in result['unanswered_parts']
    assert not thesis.decision_thresholds and not thesis.threshold_zones
    assert thesis.confidence_score == 0


def test_missing_operating_income_keeps_both_metric_and_newer_period_gaps():
    from test_monitoring_without_operating_income import inputs as without_operating
    items, refs = without_operating()
    listing_items, listing_refs = materials()
    items.append(listing_items[-1]); ref = listing_refs[-1]; ref['id'] = 'E4'; refs.append(ref)
    result = build_decision_monitoring('AAPL', items, refs, expected_cik='320193')
    assert result['benchmarks'] == [] and len(result['foundation']['claims']) == 3
    assert len(result['reporting_period_coverage']['older_comparisons']) == 3
    assert result['unanswered_parts'] == ['operating income', 'operating margin',
        'financial comparisons for the newer listed filing period']


def test_ambiguous_reference_id_cannot_cite_newer_filing_metadata():
    items, refs = materials()
    refs[-1]['id'] = 'E1'
    result = build_decision_monitoring('AAPL', items, refs, expected_cik='320193')
    assert result is None or 'reporting_period_coverage' not in result
