"""Bound monitoring comparisons without inventing missing operating margins."""
import pytest

from app.schemas import InvestmentThesis
from app.services.decision_monitoring_evidence import build_decision_monitoring
from app.services.source_answer import apply_source_answer_gate
from test_financial_thesis_foundation import evidence, reference


def inputs():
    items = [evidence('Revenues', 'revenue', current=80, prior=100),
             evidence('NetIncomeLoss', 'net income', current=4, prior=8),
             evidence('NetCashProvidedByUsedInOperatingActivities', 'operating cash flow',
                      current=60, prior=12, ytd=True)]
    return items, [reference(item, f'E{i}') for i, item in enumerate(items, 1)]


def test_valid_comparisons_survive_missing_operating_income():
    items, refs = inputs()
    result = build_decision_monitoring('AAPL', items, refs, expected_cik='320193')
    assert result['benchmarks'] == []
    assert len(result['foundation']['claims']) == 3
    assert [r['signal'] for r in result['calculations']] == [
        'counter_evidence', 'counter_evidence', 'supporting']
    assert result['unanswered_parts'] == ['operating income', 'operating margin']
    assert 'no operating margin or margin benchmark has been calculated' in result['answer']
    assert 'own reporting period' in result['answer']
    assert all(f'[E{i}]' in result['answer'] for i in (1, 2, 3))


@pytest.mark.parametrize('mutation', ['raw', 'summary', 'reference', 'scope', 'currency'])
def test_invalid_comparisons_do_not_become_monitoring_evidence(mutation):
    items, refs = inputs()
    for item in items[1:]:
        if mutation == 'raw': item.verified_claims[0]['raw_value'] = 999
        elif mutation == 'summary': item.summary = 'Invented financial improvement'
        elif mutation == 'reference':
            next(r for r in refs if r['title'] == item.title)['url'] = 'https://example.com'
        elif mutation == 'scope': item.verified_claims[0]['scope'] = 'segment'
        elif mutation == 'currency': item.verified_claims[0]['unit'] = 'EUR'
    assert build_decision_monitoring('AAPL', items, refs, expected_cik='320193') is None


def test_unmatched_operating_margin_inputs_still_fail_closed():
    items = [evidence('Revenues', 'revenue'),
             evidence('OperatingIncomeLoss', 'operating income', ytd=True)]
    refs = [reference(item, f'E{i}') for i, item in enumerate(items, 1)]
    assert build_decision_monitoring('AAPL', items, refs, expected_cik='320193') is None


def test_gate_keeps_evidence_and_missing_margin_but_removes_investment_boundaries(monkeypatch):
    from app.services.providers import sec_provider
    monkeypatch.setattr(sec_provider, '_load_ticker_cik_map', lambda: {'AAPL': '320193'})
    items, refs = inputs()
    thesis = InvestmentThesis(ticker='AAPL', company_name='Apple', bull_thesis='Buy at 30x')
    thesis.decision_thresholds = [{'bull_boundary': 30}]
    for _ in range(2):
        result = apply_source_answer_gate(thesis, 'Explain decision thresholds', items, references=refs)
        assert result['status'] == 'partial'
        assert result['monitoring_benchmarks'] == []
        assert len(result['claims']) == 3
        assert 'operating income' in result['unanswered_parts']
        assert 'operating margin' in result['unanswered_parts']
        assert 'valuation decision boundaries' in result['unanswered_parts']
        assert not thesis.decision_thresholds and not thesis.threshold_zones
        assert not thesis.bull_thesis and thesis.confidence_score == 0


def test_wrong_identity_and_missing_references_remain_refused():
    items, refs = inputs()
    assert build_decision_monitoring('AAPL', items, refs, expected_cik='123') is None
    assert build_decision_monitoring('AAPL', items, [], expected_cik='320193') is None
