"""Full producer/binder/composer regressions with authored source fixtures."""
import pytest

from app.schemas import InvestmentThesis
from app.services import thesis_disclosures as disclosures
from app.services.evidence_references import admit_evidence
from app.services.financial_thesis_foundation import build_financial_foundation
from app.services.operating_risk_mechanisms import operating_risk_mechanism
from app.services.source_answer import apply_source_answer_gate
from test_financial_thesis_foundation import pair, evidence, reference
from test_thesis_disclosures import document, BUSINESS, QUESTION

QUOTE = 'Supply chain disruptions may increase our production costs and reduce our profitability.'
# Owner-provided pilot excerpts, replayed as synthetic source documents here.
STAFFING = ('Human Capital Risks • Our facilities face competition for staffing, labor shortages '
            'and higher turnover rates that may increase our labor costs and reduce our profitability.')
PROCUREMENT = ('New laws, regulations or procurement requirements or changes to current ones '
               '(for example, regulations related to cybersecurity and related certification requirements, '
               'specialty metals, and conflict minerals) can significantly increase the Company’s '
               'costs and risks and reduce profitability.')


def risk_item(quote=QUOTE, scope='Supply chain'):
    doc = document(f'Item 1. Business {BUSINESS} Item 1A. Risk Factors {quote} '
                   'Item 1B. Unresolved Staff Comments')
    item, = disclosures.extract_issuer_risk_evidence(doc, ticker='AAPL',
        question=f'What operating risk affects {scope}?')
    value = disclosures.bound_thesis_risk(item, ticker='AAPL')
    assert value and value['quote'] == quote
    assert doc.text[value['start_offset']:value['end_offset']] == quote
    return item


def compose(items, refs=None):
    return build_financial_foundation('AAPL', items, refs, expected_cik='320193')


def mechanisms(result):
    return [row for row in result['inferences'] if row['kind'] == 'operating_risk_monitoring_inference']


@pytest.mark.parametrize('quote,scope,modal', [
    (QUOTE, 'Supply chain', 'may'),
    (QUOTE.replace('may', 'could'), 'Supply chain', 'could'),
    (STAFFING, 'Staffing demand', 'may'),
    (PROCUREMENT, 'Cybersecurity', 'can'),
])
def test_bound_direct_and_relative_mechanisms_retain_complete_source_and_modal(quote, scope, modal):
    items = pair() + [risk_item(quote, scope)]
    refs = [reference(item, name) for item, name in zip(items, ('E12', 'E7', 'E19'))]
    result = compose(items, refs)
    row, = mechanisms(result)
    assert row['source_quote'] == quote and row['modality'] == modal
    assert quote == row['condition'] + (' that ' if quote == STAFFING else ' ') + modal + ' ' + row['potential_effect'] + '.'
    assert row['risk_reference_id'] == 'E19' and row['risk_filed_at'] == '2025-08-01'
    assert row['reference_ids'] == ['E19', 'E7']  # revenue is not profitability context
    target, = row['financial_context']
    assert target == dict(metric='operating income', reference_id='E7', role='profitability_context_only',
        current_period_start='2025-04-01', current_period_end='2025-06-30',
        prior_period_start='2024-04-01', prior_period_end='2024-06-30')
    assert not row['causal_attribution_established']
    assert not row['materiality_assessed'] and not row['measure_equivalence_established']
    assert quote in result['answer']
    assert 'risk materiality, likelihood and effect on the investment case' in result['unanswered_parts']
    assert len(result['claims']) == 3


def test_different_income_durations_remain_separate_and_do_not_measure_cost_effect():
    items = pair() + [evidence('NetIncomeLoss', 'net income', ytd=True), risk_item()]
    row, = mechanisms(compose(items))
    assert [r['current_period_start'] for r in row['financial_context']] == ['2025-04-01', '2025-01-01']
    assert [r['metric'] for r in row['financial_context']] == ['operating income', 'net income attributable to parent']
    assert 'not a measurement of this cost effect' in row['conditional_test']
    assert 'do not establish common periods' in row['conditional_test']


def test_pretax_and_cash_flow_do_not_replace_missing_operating_or_net_income():
    items = [evidence('Revenues', 'revenue'),
        evidence('NetCashProvidedByUsedInOperatingActivities', 'operating cash flow'),
        evidence('IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest',
                 'pretax income'), risk_item()]
    result = compose(items)
    row, = mechanisms(result)
    assert row['financial_context'] == [] and row['reference_ids'] == ['E4']
    assert 'No reconstructed operating-income or net-income comparison' in row['text']
    assert 'operating income' in result['unanswered_parts'] and 'net income' in result['unanswered_parts']


@pytest.mark.parametrize('quote', [
    'Supply chain disruptions may increase our customers’ costs and reduce their profitability.',
    'Supply chain disruptions may increase our production costs but not reduce our profitability.',
    'Supply chain disruptions will increase our production costs and reduce our profitability.',
    'Supply chain disruptions may not increase our production costs and reduce our profitability.',
    'Supply chain disruptions may probably increase our production costs and reduce our profitability.',
    'Supply chain disruptions may occur and could increase our costs and reduce our profitability.',
    'Supply chain disruptions are not material and may increase our costs and reduce our profitability.',
    'Supply chain disruptions may increase our costs and reduce our adjusted profitability.',
    'Supply chain disruptions may increase our costs and reduce our profitability in some segments.',
    'Supply chain disruptions may reduce profitability.',
    'Supply chain disruptions are discussed elsewhere in this filing.',
    'Furthermore, our actions related to the supply chain may increase our costs and reduce our profitability.',
    'These supply chain risks may increase our costs and reduce our profitability.',
    'The situation may increase our supply chain costs and reduce our profitability.',
])
def test_no_negated_nested_third_party_adjusted_generic_or_unresolved_mechanism(quote):
    # Parser testing does not bypass admission: none of these values enters the
    # final composer without independently passing the producer/binder.
    value = dict(quote=quote, scope='Supply chain')
    assert operating_risk_mechanism(value, 'E1', {}, filed_at='2025-08-01') is None


@pytest.mark.parametrize('mutation', [
    lambda item: setattr(item, 'summary', 'Unbound source summary'),
    lambda item: setattr(item, 'freshness_status', 'stale'),
    lambda item: setattr(item, 'url', 'https://example.com/unrelated.htm'),
    lambda item: item.risk_disclosures[0].update(ticker='TSLA'),
    lambda item: item.risk_disclosures[0].update(quote=QUOTE.replace('may', 'will')),
])
def test_invalid_source_cannot_produce_mechanism(mutation):
    item = risk_item()
    mutation(item)
    assert mechanisms(compose(pair() + [item])) == []


def test_unreferenced_risk_and_metric_do_not_supply_links():
    items = pair() + [evidence('NetIncomeLoss', 'net income'), risk_item()]
    refs = [reference(item, f'E{i}') for i, item in enumerate(items, 1)]
    assert mechanisms(compose(items, refs[:-1])) == []
    row, = mechanisms(compose(items, [refs[0], refs[2], refs[3]]))
    assert [r['metric'] for r in row['financial_context']] == ['net income attributable to parent']
    conflicting = compose(items + [evidence('OperatingIncomeLoss', 'operating income', current=999)])
    assert [r['metric'] for r in mechanisms(conflicting)[0]['financial_context']] == ['net income attributable to parent']


def test_historical_predecessor_mechanism_cannot_become_current_context():
    value = dict(quote=QUOTE, scope='Supply chain', issuer_relationship={'use': 'historical_risk_context_only'})
    assert operating_risk_mechanism(value, 'E1', {}, filed_at='2025-08-01') is None


def test_source_answer_carries_inference_without_changing_claim_or_quality_status(monkeypatch):
    monkeypatch.setattr(disclosures.sec_provider, '_load_ticker_cik_map', lambda: {'AAPL': '0000320193'})
    items, refs, _ = admit_evidence(pair() + [risk_item()], evaluated_at='2025-09-01')
    thesis = InvestmentThesis(ticker='AAPL', company_name='Synthetic company')
    result = apply_source_answer_gate(thesis, QUESTION, items, references=refs)
    row, = mechanisms(result)
    assert result['status'] == 'partial' and thesis.confidence_score == 0
    assert 'Disclosed operating mechanisms and monitoring' in thesis.direct_answer
    assert 'not a forecast or a buy/sell threshold' in row['conditional_test']
    assert len(result['claims']) == 3
    assert set(row['reference_ids']) <= {ref['id'] for ref in refs}
    assert 'valuation and expected returns' in result['unanswered_parts']


@pytest.mark.parametrize('ticker,cik', [('ZQXB', '1234567'), ('ZYTR', '7654321')])
def test_shared_composition_transfers_to_issuers_without_named_profiles(monkeypatch, ticker, cik):
    from app.services import issuer_identity
    directory = issuer_identity.parse_directory({'0': {'ticker': ticker, 'cik_str': int(cik),
                                                       'title': 'Invented components issuer'}})
    monkeypatch.setattr(issuer_identity, '_load_directory', lambda: directory)
    url = document().final_url.replace('/320193/', f'/{cik}/')
    doc = document(f'Item 1. Business {BUSINESS} Item 1A. Risk Factors {QUOTE} '
                   'Item 1B. Unresolved Staff Comments', requested_url=url, final_url=url)
    item, = disclosures.extract_issuer_risk_evidence(doc, ticker=ticker,
        question='What operating risk affects Supply chain?')
    result = build_financial_foundation(ticker, pair(ticker=ticker, cik=cik) + [item],
                                        None, expected_cik=cik)
    row, = mechanisms(result)
    assert row['source_quote'] == QUOTE and row['reference_ids'] == ['E3', 'E2']
    assert any(claim['claim_kind'] == 'issuer_disclosed_risk' for claim in result['claims'])


def test_caller_annotations_cannot_replace_the_bound_source_mechanism():
    item = risk_item()
    item.risk_disclosures[0]['operating_mechanism'] = {'condition': 'Guaranteed collapse',
        'potential_effect': 'Invented loss', 'reference_ids': ['E999']}
    row, = mechanisms(compose(pair() + [item]))
    assert row['source_quote'] == QUOTE
    assert 'Guaranteed collapse' not in str(row) and 'E999' not in str(row)
