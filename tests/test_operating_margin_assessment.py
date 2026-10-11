"""Synthetic profitability evidence; no claim about any real issuer's strength."""
from copy import deepcopy
from decimal import Decimal
import socket

import pytest

from app.integrity.sec_metric_evidence import comparable_metric_evidence
from app.providers.sec_client import SecFactRecord
from app.schemas import InvestmentThesis
from app.services.evidence_references import admit_evidence
from app.services.financial_thesis_foundation import build_financial_foundation
from app.services.source_answer import apply_source_answer_gate

TICKER, CIK = 'ZQXM', '1234567'


@pytest.fixture(autouse=True)
def offline_identity(monkeypatch):
    from app.services import issuer_identity
    from app.services.providers import sec_provider

    def no_network(*args, **kwargs):
        pytest.fail('Synthetic operating-margin tests must not use the network')

    monkeypatch.setattr(socket, 'getaddrinfo', no_network)
    monkeypatch.setattr(socket.socket, 'connect', no_network)
    monkeypatch.setattr(socket.socket, 'connect_ex', no_network)
    monkeypatch.setattr(sec_provider, '_load_ticker_cik_map', lambda: {TICKER: CIK})
    directory = issuer_identity.parse_directory({'0': {
        'ticker': TICKER, 'cik_str': int(CIK), 'title': 'Synthetic components issuer'}})
    monkeypatch.setattr(issuer_identity, '_load_directory', lambda: directory)


def metric(concept, name, current, prior, *, unit='USD', form='10-Q',
           current_start=None, prior_start=None, filing_number=1, cik=CIK):
    annual = form.startswith(('10-K', '20-F'))
    records = []
    for year, value, start in ((2025, current, current_start), (2024, prior, prior_start)):
        accession = f'{int(cik):010d}-{str(year)[-2:]}-{filing_number:06d}'
        records.append(SecFactRecord(
            cik=cik, taxonomy='us-gaap', concept=concept, label=concept,
            unit=unit, value=value, start=start or f'{year}-01-01',
            end=f'{year}-' + ('12-31' if annual else '03-31'),
            filed=f'{year + 1}-02-01' if annual else f'{year}-05-01',
            form=form, accession=accession,
            filing_url=f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/'
                       f'{accession.replace("-", "")}/{accession}-index.htm'))
    item = comparable_metric_evidence(records, ticker=TICKER, expected_cik=cik,
                                     concepts=(concept,), metric_name=name, unit=unit)
    assert item is not None
    return item


def material(*, revenue=120, prior_revenue=100, income=24, prior_income=10, **kwargs):
    return [metric('Revenues', 'revenue', revenue, prior_revenue, **kwargs),
            metric('OperatingIncomeLoss', 'operating income', income, prior_income, **kwargs)]


def admitted(items):
    # Freeze evaluation immediately after the newest authored filing.
    evaluated_at = max(item.timestamp for item in items)
    return admit_evidence(items, evaluated_at=evaluated_at)[:2]


def foundation(items, refs):
    return build_financial_foundation(TICKER, items, refs, expected_cik=CIK)


def margins(result):
    return [row for row in (result or {}).get('inferences', [])
            if row['kind'] == 'operating_margin_calculation']


@pytest.mark.parametrize('income,prior_income,revenue,direction,current,prior,change', [
    (24, 10, 120, 'widened', '20', '10', '10'),
    (22, 20, 200, 'narrowed', '11', '20', '-9'),
    (12, 10, 120, 'unchanged', '10', '10', '0'),
    (-6, -10, 120, 'widened', '-5', '-10', '5'),
    (0, 10, 120, 'narrowed', '0', '10', '-10'),
])
def test_exact_derived_comparison_and_cited_inputs(income, prior_income, revenue,
                                                 direction, current, prior, change):
    items, refs = admitted(material(income=income, prior_income=prior_income, revenue=revenue))
    before = deepcopy([item.model_dump() for item in items])
    result = foundation(items, refs)
    row, = margins(result)
    assert row['provenance'] == 'derived' and row['signal'] == 'context_only'
    assert row['direction'] == direction
    assert Decimal(row['current']['margin_percent']) == Decimal(current)
    assert Decimal(row['prior']['margin_percent']) == Decimal(prior)
    assert Decimal(row['change_percentage_points']) == Decimal(change)
    assert row['change_unit'] == 'percentage_points'
    assert row['formula'] == 'operating_income / revenue * 100'
    assert row['change_formula'] == 'current_margin_percent - prior_margin_percent'
    assert row['reference_ids'] == ['E1', 'E2']
    for period_index, key in enumerate(('current', 'prior')):
        period = row[key]
        for metric_name, item_index in (('revenue', 0), ('operating_income', 1)):
            source_claim = items[item_index].verified_claims[period_index]
            assert period[metric_name]['raw_value'] == str(source_claim['raw_value'])
            assert period[metric_name]['document_ref'] == source_claim['document_ref']
            assert period[metric_name]['reference_id'] == refs[item_index]['id']
        assert period['period_start'] == f'{2025 - period_index}-01-01'
        assert period['period_end'] == f'{2025 - period_index}-03-31'
    assert [item.model_dump() for item in items] == before
    assert 'No margin or cash-conversion ratio has been calculated' not in result['answer']
    assert 'not a peer comparison or proof' in result['answer']
    assert 'drivers of the margin change remain unverified' in result['answer']
    assert ('non-positive' in row['text']) == (Decimal(current) <= 0)
    assert all(gap in result['unanswered_parts'] for gap in (
        'business model and competitive position', 'valuation and expected returns',
        'issuer-disclosed operating-risk mechanisms'))


@pytest.mark.parametrize('unit,form', [('USD', '10-Q'), ('USD', '10-K'), ('EUR', '20-F'), ('EUR', '20-F/A')])
def test_source_gate_preserves_partial_status_and_native_currency(unit, form):
    items, refs = admitted(material(unit=unit, form=form))
    thesis = InvestmentThesis(ticker=TICKER, company_name='Synthetic components issuer',
                              score_source='not_assessed_evidence_view')
    result = apply_source_answer_gate(thesis, f'What is the investment thesis for {TICKER}? Cite claims.',
                                     items, references=refs)
    row, = margins(result)
    assert row['current']['currency'] == row['prior']['currency'] == unit
    assert result['status'] == 'partial'
    assert row['text'] in thesis.direct_answer and '[E1] [E2]' in thesis.direct_answer
    assert thesis.directional_stance == '' and thesis.confidence_score == 0
    assert thesis.score_source == 'not_assessed_evidence_view'
    assert len(thesis.quantitative_claims) == 4
    assert all(claim['provenance'] == 'reported' for claim in thesis.quantitative_claims)
    assert result['inferences'][-1]['provenance'] == 'derived'


@pytest.mark.parametrize('changes', [
    {'current_start': '2025-01-02'}, {'prior_start': '2024-01-02'},
    {'filing_number': 2}, {'form': '10-Q/A'}, {'unit': 'EUR'}, {'cik': '7654321'},
])
def test_individually_bound_but_incompatible_operating_income_is_not_combined(changes):
    items = [material()[0], metric('OperatingIncomeLoss', 'operating income', 24, 10, **changes)]
    items, refs = admitted(items)
    assert margins(foundation(items, refs)) == []


@pytest.mark.parametrize('mutation', [
    lambda item: setattr(item, 'summary', 'Invented support'),
    lambda item: setattr(item, 'freshness_status', 'stale'),
    lambda item: setattr(item, 'freshness_status', 'conflicting'),
    lambda item: setattr(item, 'availability_status', 'unavailable'),
    lambda item: item.verified_claims[0].update(ticker='OTHER'),
    lambda item: item.verified_claims[0].update(scope='segment'),
    lambda item: item.verified_claims[0].update(raw_value=999),
    lambda item: item.verified_claims[0].update(raw_value=True),
    lambda item: item.verified_claims[0].update(provenance='estimated'),
    lambda item: item.verified_claims[0].update(raw_value=float('nan')),
    lambda item: item.verified_claims[0]['document_ref'].update(url='https://example.com/other'),
])
def test_tampered_stale_or_unavailable_inputs_cannot_produce_margin(mutation):
    items, refs = admitted(material())
    mutation(items[1])
    assert margins(foundation(items, refs)) == []


@pytest.mark.parametrize('current,prior', [(0, 100), (-10, 100), (120, -100)])
def test_nonpositive_revenue_withholds_ratio(current, prior):
    items, refs = admitted(material(revenue=current, prior_revenue=prior))
    assert margins(foundation(items, refs)) == []


def test_bank_net_interest_revenue_is_not_a_sales_margin_denominator():
    items = [metric('RevenuesNetOfInterestExpense', 'revenue net of interest expense', 120, 100),
             material()[1]]
    items, refs = admitted(items)
    assert foundation(items, refs) is not None
    assert margins(foundation(items, refs)) == []


def test_net_income_and_pretax_income_do_not_substitute_for_operating_income():
    items = [material()[0], metric('NetIncomeLoss', 'net income', 20, 10),
             metric('IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest',
                    'pretax income', 24, 12)]
    items, refs = admitted(items)
    result = foundation(items, refs)
    assert 'operating income' in result['unanswered_parts']
    assert margins(result) == []


@pytest.mark.parametrize('problem', ['none', 'missing', 'wrong_url', 'duplicate_id', 'conflicting_id', 'stale'])
def test_answer_references_must_be_present_and_unambiguous(problem):
    items, refs = admitted(material() + [metric('NetIncomeLoss', 'net income', 20, 10)])
    if problem == 'none':
        refs = None
    elif problem == 'missing':
        refs.pop(1)
    elif problem == 'wrong_url':
        refs[1]['url'] = 'https://example.com/other'
    elif problem == 'duplicate_id':
        refs[1]['id'] = refs[0]['id']
    elif problem == 'stale':
        refs[1]['freshness_status'] = 'stale'
    else:
        refs.append({**refs[0], 'url': 'https://example.com/other'})
    result = foundation(items, refs)
    assert result is not None
    assert margins(result) == []


def test_conflicting_revenue_does_not_select_a_convenient_margin():
    items = material() + [metric('Revenues', 'revenue', 140, 100),
                          metric('NetIncomeLoss', 'net income', 20, 10)]
    items, refs = admitted(items)
    result = foundation(items, refs)
    assert result is not None and 'revenue' in result['unanswered_parts']
    assert margins(result) == []


@pytest.mark.parametrize('income', [12.000012, 12.006])
def test_reassigned_citations_and_subprecision_change_remain_honest(income):
    items, refs = admitted(material(income=income, prior_income=10))
    refs[0]['id'], refs[1]['id'] = 'E4', 'E9'
    row, = margins(foundation(items, refs))
    assert row['reference_ids'] == ['E4', 'E9']
    assert row['direction'] == 'widened'
    assert 'less than 0.01 percentage points' in row['text']
    assert 'rounded to two decimals' in row['text']


def test_competition_and_risk_context_do_not_turn_margin_into_a_strength_claim():
    from dataclasses import replace
    from app.services import thesis_competition, thesis_disclosures
    from test_thesis_competition import competition_document, QUOTE

    doc = competition_document()
    url = doc.final_url.replace('/320193/', f'/{CIK}/')
    doc = replace(doc, final_url=url, requested_url=url)
    context = (thesis_disclosures.extract_business_descriptions(doc, ticker=TICKER, cik=CIK)
               + thesis_competition.extract_competition_descriptions(doc, ticker=TICKER, cik=CIK)
               + thesis_disclosures.extract_issuer_risk_evidence(doc, ticker=TICKER,
                   question='What operating risk affects Supply chain?'))
    items, refs = admitted(material() + context)
    result = foundation(items, refs)
    margin, = margins(result)
    assert margin['reference_ids'] == ['E1', 'E2']
    assert QUOTE in result['answer']
    assert 'durable advantage remain unverified' in result['answer']
    assert any(row['kind'] == 'risk_monitoring_inference' for row in result['inferences'])
    assert 'competitive position' in result['unanswered_parts']
    assert 'risk materiality, likelihood and effect on the investment case' in result['unanswered_parts']


def test_other_metric_period_does_not_contaminate_matched_margin():
    items = material() + [metric('NetIncomeLoss', 'net income', 20, 10,
                                current_start='2025-01-02', prior_start='2024-01-02')]
    items, refs = admitted(items)
    result = foundation(items, refs)
    assert len(margins(result)) == 1
    assert result['common_reporting_period'] is False
    assert 'Other metrics cover different reporting durations or end dates' in result['answer']


def test_contract_revenue_and_fractional_margin_display_keep_percentage_point_units():
    items = [metric('RevenueFromContractWithCustomerExcludingAssessedTax', 'revenue', 3, 4),
             metric('OperatingIncomeLoss', 'operating income', 1, 1)]
    items, refs = admitted(items)
    row, = margins(foundation(items, refs))
    assert '33.33%' in row['text'] and '25.00%' in row['text']
    assert 'widened by 8.33 percentage points' in row['text']
    assert abs(Decimal(row['change_percentage_points']) - Decimal(25) / 3) < Decimal('1e-25')
