import pytest
from app.services.decision_monitoring_evidence import build_decision_monitoring
from app.services.source_answer import apply_source_answer_gate
from app.schemas import InvestmentThesis
from test_financial_thesis_foundation import evidence, reference


def inputs():
    items = [evidence('Revenues', 'revenue', current=200, prior=100),
             evidence('OperatingIncomeLoss', 'operating income', current=40, prior=10)]
    return items, [reference(item, f'E{i}') for i, item in enumerate(items, 1)]


def test_margin_benchmark_is_recomputed_with_bound_inputs():
    items, refs = inputs()
    result = build_decision_monitoring('AAPL', items, refs, expected_cik='320193')
    row = result['benchmarks'][0]
    assert row['benchmark_percent'] == '20.0'
    assert row['inputs']['revenue']['raw_value'] == '200'
    assert row['inputs']['operating_income']['raw_value'] == '40'
    assert row['reference_ids'] == ['E1', 'E2']
    assert row['period_start'] == '2025-04-01'
    assert 'not a buy/sell boundary' in row['limitation']


@pytest.mark.parametrize('mutation', ['raw', 'scope', 'reference', 'currency', 'period'])
def test_tampered_or_unmatched_inputs_cannot_supply_a_benchmark(mutation):
    items, refs = inputs()
    if mutation == 'reference': refs[0]['url'] = 'https://example.com/metadata'
    else:
        key, value = {'raw': ('raw_value', '999'), 'scope': ('scope', 'segment'),
                      'currency': ('unit', 'EUR'), 'period': ('period_start', '2025-01-01')}[mutation]
        items[0].verified_claims[0][key] = value
    assert build_decision_monitoring('AAPL', items, refs, expected_cik='320193') is None


def test_no_references_and_wrong_identity_fail_closed():
    items, refs = inputs()
    assert build_decision_monitoring('AAPL', items, [], expected_cik='320193') is None
    assert build_decision_monitoring('AAPL', items, refs, expected_cik='123') is None


def test_response_preserves_benchmark_but_never_model_investment_boundaries(monkeypatch):
    from app.services.providers import sec_provider
    monkeypatch.setattr(sec_provider, '_load_ticker_cik_map', lambda: {'AAPL': '320193'})
    items, refs = inputs()
    thesis = InvestmentThesis(ticker='AAPL', company_name='Apple', bull_thesis='Buy at 30x')
    thesis.decision_thresholds = [{'bull_boundary': 30}]
    for _ in range(2):
        result = apply_source_answer_gate(thesis, 'Explain decision thresholds', items, references=refs)
        assert result['status'] == 'partial'
        assert result['monitoring_benchmarks'][0]['benchmark_percent'] == '20.0'
        assert not thesis.decision_thresholds and not thesis.threshold_zones
        assert not thesis.bull_thesis and thesis.confidence_score == 0
