"""Invented disclosures exercise actual extraction, binding and composition."""
from copy import deepcopy

import pytest

from app.schemas import InvestmentThesis
from app.services import thesis_disclosures as disclosures
from app.services.evidence_references import admit_evidence
from app.services.financial_thesis_foundation import build_financial_foundation, _risk_monitoring_inference
from app.services.risk_financial_monitoring import risk_financial_link
from app.services.source_answer import apply_source_answer_gate
from test_financial_thesis_foundation import pair, evidence, reference
from test_thesis_disclosures import document, BUSINESS, QUESTION


def risk_item(effect='our revenue and operating income', *, condition='Supply chain disruptions'):
    quote = f'{condition} could adversely affect {effect}.'
    doc = document(f'Item 1. Business {BUSINESS} Item 1A. Risk Factors {quote} '
                   'Item 1B. Unresolved Staff Comments')
    item, = disclosures.extract_issuer_risk_evidence(doc, ticker='AAPL',
                                                    question='What operating risk affects Supply chain?')
    assert disclosures.bound_thesis_risk(item, ticker='AAPL')['quote'] == quote
    return item


def compose(items, references=None):
    return build_financial_foundation('AAPL', items, references, expected_cik='320193')


def links(result):
    return [row for row in result['inferences'] if row['kind'] == 'risk_financial_monitoring_link']


def test_actual_bound_risk_links_exact_named_measures_and_both_comparison_periods():
    items = pair() + [risk_item()]
    refs = [reference(item, ref) for item, ref in zip(items, ('E8', 'E3', 'E12'))]
    result = compose(items, refs)
    link, = links(result)
    assert link['reference_ids'] == ['E12', 'E8', 'E3']
    assert link['risk_reference_id'] == 'E12'
    assert link['risk_filed_at'] == '2025-08-01'
    assert [row['metric'] for row in link['financial_targets']] == ['revenue (as reported)', 'operating income']
    assert link['financial_targets'][0] == dict(metric='revenue (as reported)', reference_id='E8',
        current_period_start='2025-04-01', current_period_end='2025-06-30',
        prior_period_start='2024-04-01', prior_period_end='2024-06-30')
    assert '2025-04-01 to 2025-06-30' in link['text']
    assert '2024-04-01 to 2024-06-30' in link['text']
    assert '[E12]' in link['text'] and '[E8]' in link['text'] and '[E3]' in link['text']
    assert not link['causal_attribution_established'] and not link['materiality_assessed']
    assert link['match_basis'] == 'explicit_financial_family'
    assert not link['measure_equivalence_established']
    assert 'risk materiality, likelihood and effect on the investment case' in result['unanswered_parts']
    assert 'valuation and expected returns' in result['unanswered_parts']
    assert len(result['claims']) == 3  # linking is inference, never another sourced fact


@pytest.mark.parametrize('effect,expected', [
    ('our revenues', ['revenue (as reported)']),
    ('our consolidated revenue and our operating income', ['revenue (as reported)', 'operating income']),
    ('our business, revenue, and net income', ['revenue (as reported)', 'net income attributable to parent']),
    ('our financial condition and operating cash flow', ['operating cash flow']),
    ('our revenue, operating income, net income and operating cash flow',
     ['revenue (as reported)', 'operating income', 'net income attributable to parent', 'operating cash flow']),
])
def test_only_explicit_issuer_measures_link_including_oxford_lists(effect, expected):
    result = compose(pair() + [evidence('NetIncomeLoss', 'net income'),
        evidence('NetCashProvidedByUsedInOperatingActivities', 'operating cash flow', ytd=True), risk_item(effect)])
    link, = links(result)
    assert [row['metric'] for row in link['financial_targets']] == expected
    assert 'Different reporting durations must be assessed separately' in link['conditional_test']


@pytest.mark.parametrize('effect', [
    'our financial condition and results of operations',
    'our ability to generate revenue',
    'our customers and their revenue',
    'our customers\' revenue and operating income',
    'our adjusted operating income',
    'our segment revenue',
    'our revenue from discontinued operations',
    'our revenue but not our operating income',
    'our revenue and our customers\' net income',
])
def test_generic_third_party_adjusted_segment_and_qualified_effects_do_not_link(effect):
    result = compose(pair() + [risk_item(effect)])
    assert links(result) == []
    assert 'Risk-to-financial monitoring questions' not in result['answer']
    assert any(row['kind'] == 'risk_monitoring_inference' for row in result['inferences'])


def test_words_in_condition_cannot_supply_measure_missing_from_effect():
    item = risk_item('our manufacturing operations', condition='Supply chain disruptions that reduce revenue')
    assert links(compose(pair() + [item])) == []


def test_missing_operating_income_cannot_be_replaced_by_pretax_income():
    items = [evidence('Revenues', 'revenue'), evidence('NetIncomeLoss', 'net income'),
        evidence('IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest',
                 'pretax income'), risk_item('our operating income')]
    result = compose(items)
    assert any(row['claim_kind'] == 'supplementary_profitability_comparison' for row in result['claims'])
    assert 'operating income' in result['unanswered_parts']
    assert links(result) == []


def test_contract_revenue_keeps_its_narrower_reported_definition():
    items = [evidence('RevenueFromContractWithCustomerExcludingAssessedTax', 'revenue'),
             evidence('OperatingIncomeLoss', 'operating income'), risk_item('our revenue')]
    link, = links(compose(items))
    assert link['financial_targets'][0]['metric'] == 'revenue from contracts with customers excluding assessed taxes'
    assert not link['measure_equivalence_established']
    assert 'not establish identical measure definitions' in link['conditional_test']


def test_deteriorating_financial_comparison_does_not_become_risk_causality():
    items = pair(current=80) + [risk_item()]
    result = compose(items)
    link, = links(result)
    assert all(row['signal'] == 'counter_evidence' for row in result['inferences']
               if row['kind'] == 'financial_inference')
    assert not link['causal_attribution_established']
    assert 'not establish a common observation period, that this risk caused reported changes' in link['conditional_test']


@pytest.mark.parametrize('mutation', [
    lambda item: setattr(item, 'summary', 'Invented risk summary'),
    lambda item: setattr(item, 'freshness_status', 'stale'),
    lambda item: setattr(item, 'url', 'https://www.sec.gov/Archives/edgar/data/9999/wrong.htm'),
])
def test_rejected_risk_cannot_link(mutation):
    item = risk_item()
    mutation(item)
    assert links(compose(pair() + [item])) == []


def test_unreferenced_risk_and_conflicting_or_unreferenced_metric_cannot_link():
    items = pair() + [evidence('NetIncomeLoss', 'net income'), risk_item()]
    refs = [reference(item, f'E{i}') for i, item in enumerate(items, 1)]
    assert links(compose(items, refs[:-1])) == []
    # Enough other metrics survive to build a foundation while revenue is withheld.
    missing_revenue = compose(items, refs[1:])
    assert [row['metric'] for row in links(missing_revenue)[0]['financial_targets']] == ['operating income']
    conflicted = compose(items + [evidence('Revenues', 'revenue', current=999)])
    assert [row['metric'] for row in links(conflicted)[0]['financial_targets']] == ['operating income']


def test_different_quarter_and_ytd_targets_keep_separate_durations():
    items = pair() + [evidence('NetCashProvidedByUsedInOperatingActivities', 'operating cash flow', ytd=True),
                     risk_item('our revenue and operating cash flow')]
    link, = links(compose(items))
    assert [row['current_period_start'] for row in link['financial_targets']] == ['2025-04-01', '2025-01-01']
    assert 'do not establish a common observation period' in link['conditional_test']


@pytest.mark.parametrize('effect,expected', [
    ('our revenue and operating cash flow', []),
    ('our revenue net of interest expense and operating cash flow', ['revenue net of interest expense']),
])
def test_bank_net_revenue_is_not_generic_revenue_and_cash_flow_is_not_performance_test(effect, expected):
    items = [evidence('RevenuesNetOfInterestExpense', 'revenue net of interest expense'),
             evidence('NetIncomeLoss', 'net income'),
             evidence('NetCashProvidedByUsedInOperatingActivities', 'operating cash flow'), risk_item(effect)]
    result = links(compose(items))
    assert [row['metric'] for link in result for row in link['financial_targets']] == expected


def test_historical_predecessor_mechanism_cannot_link_current_financial_case():
    value = deepcopy(risk_item().risk_disclosures[0])
    value['issuer_relationship'] = {'historical': True}
    risk = _risk_monitoring_inference(value, 'E3')
    assert risk['historical_context_only']
    assert risk_financial_link(risk, {}, filed_at='2025-08-01') is None


def test_source_answer_retains_links_as_inference_and_partial_unscored_result(monkeypatch):
    monkeypatch.setattr(disclosures.sec_provider, '_load_ticker_cik_map', lambda: {'AAPL': '0000320193'})
    items, refs, _ = admit_evidence(pair() + [risk_item()], evaluated_at='2025-09-01')
    thesis = InvestmentThesis(ticker='AAPL', company_name='Synthetic company')
    result = apply_source_answer_gate(thesis, QUESTION, items, references=refs)
    link, = links(result)
    assert result['status'] == 'partial' and thesis.confidence_score == 0
    assert 'Risk-to-financial monitoring questions' in thesis.direct_answer
    assert 'not a forecast or a buy/sell threshold' in thesis.direct_answer
    assert set(link['reference_ids']) <= {row['id'] for row in refs}
    assert all(row['claim_kind'] != 'risk_financial_monitoring_link' for row in result['claims'])
