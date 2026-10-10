"""Synthetic Company Facts payloads; these are not actual company financials."""
from copy import deepcopy
from dataclasses import replace

import pytest

from app.providers import sec_client
from app.integrity.sec_metric_evidence import comparable_metric_evidence
from app.services import verified_sec_metric_service as producer
from app.services import financial_thesis_foundation as foundation
from app.services.providers import sec_provider
from app.services.evidence_references import admit_evidence
from app.services.source_answer import apply_source_answer_gate
from app.schemas import InvestmentThesis

CIK = '1234567'
TICKER = 'ZQXF'
CONCEPTS = {name: aliases[0] for name, aliases in foundation.CORE_METRICS.items()}


def payload(unit='EUR', form='20-F'):
    facts = {}
    for concept in (*CONCEPTS.values(), 'Assets'):
        rows = []
        for year, value in ((2024, 1000000), (2025, 1200000)):
            row = dict(val=value, end=f'{year}-12-31', filed=f'{year+1}-02-25',
                       form=form, accn=f'0001234567-{str(year+1)[-2:]}-000001')
            if concept != 'Assets':
                row['start'] = f'{year}-01-01'
            rows.append(row)
        facts[concept] = dict(label=concept, units={unit: rows})
    return dict(cik=int(CIK), entityName='Synthetic issuer', facts={'us-gaap': facts})


def install(monkeypatch, data):
    calls = []
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return deepcopy(data)
    monkeypatch.setattr(sec_client.requests, 'get', lambda *a, **k: calls.append((a, k)) or Response())
    monkeypatch.setattr(producer, '_load_ticker_cik_map', lambda: {TICKER: CIK})
    monkeypatch.setattr(sec_provider, '_load_ticker_cik_map', lambda: {TICKER: CIK})
    return calls


@pytest.mark.parametrize('form', ['20-F', '20-F/A', '10-K'])
@pytest.mark.parametrize('unit,display', [('EUR', '1.2M EUR'), ('USD', '$1.2M')])
def test_native_currency_survives_parser_binding_admission_and_answer(monkeypatch, form, unit, display):
    calls = install(monkeypatch, payload(unit, form))
    items = producer.fetch_verified_metric_evidence(TICKER,
        question='Cite revenue, operating income, net income and operating cash flow trends.')
    assert len(calls) == 1 and len(items) == 4
    admitted, refs, _ = admit_evidence(items, evaluated_at='2026-02-26')
    assert len(admitted) == 4
    for item in items:
        assert display in item.summary
        assert len(item.verified_claims) == 2
        assert all(c['unit'] == c['currency'] == unit for c in item.verified_claims)
        assert all(c['period'].startswith('FY') for c in item.verified_claims)
    thesis = InvestmentThesis(ticker=TICKER, company_name='Synthetic issuer')
    result = apply_source_answer_gate(thesis,
        'What is the investment thesis for ZQXF? Cite material claims.', admitted, references=refs)
    assert result['status'] == 'partial' and len(result['claims']) == 4
    assert display in thesis.direct_answer and 'operating income' not in result['unanswered_parts']
    assert 'valuation and expected returns' in result['unanswered_parts']
    assert 'business model and competitive position' in result['unanswered_parts']
    assert thesis.confidence_score == 0


def test_financial_trends_all_four_slots_are_attributed_in_eur(monkeypatch):
    install(monkeypatch, payload())
    question = 'Cite revenue, operating income, net income and operating cash flow trends.'
    items, refs, _ = admit_evidence(producer.fetch_verified_metric_evidence(TICKER, question=question),
                                  evaluated_at='2026-02-26')
    thesis = InvestmentThesis(ticker=TICKER, company_name='Synthetic issuer')
    result = apply_source_answer_gate(thesis, question, items, references=refs)
    assert result['status'] == 'attributed' and result['unanswered_parts'] == []
    assert len(result['claims']) == 4 and 'EUR' in thesis.direct_answer
    assert '$' not in thesis.direct_answer


@pytest.mark.parametrize('mutation', ['cross_currency', 'quarter_in_annual', 'missing_prior', 'conflict', 'other_issuer', 'wrong_url'])
def test_annual_comparison_fails_closed_on_bad_pair(mutation):
    data = payload()
    rows = data['facts']['us-gaap'][CONCEPTS['revenue']]['units']['EUR']
    if mutation == 'cross_currency':
        data['facts']['us-gaap'][CONCEPTS['revenue']]['units']['USD'] = [rows.pop(0)]
    elif mutation == 'quarter_in_annual':
        rows[1]['start'] = '2025-10-01'
    elif mutation == 'missing_prior':
        rows.pop(0)
    elif mutation == 'conflict':
        rows.append({**rows[1], 'val': 1500000})
    records = sec_client.parse_company_fact_records(data, concept=CONCEPTS['revenue'], unit='EUR')
    if mutation == 'other_issuer':
        records = [replace(row, cik='7654321') for row in records]
    elif mutation == 'wrong_url':
        records[1] = replace(records[1], filing_url='https://example.com/unbound')
    assert comparable_metric_evidence(records, ticker=TICKER, expected_cik=CIK,
        concepts=(CONCEPTS['revenue'],), metric_name='revenue', unit='EUR') is None


def test_currency_ambiguity_is_not_resolved_by_preferring_usd(monkeypatch):
    data = payload()
    for entry in data['facts']['us-gaap'].values():
        entry['units']['USD'] = deepcopy(entry['units']['EUR'])
    install(monkeypatch, data)
    assert producer.fetch_verified_metric_evidence(TICKER, question='Cite financial trends.') == []


def test_unknown_currency_and_nonperiodic_forms_remain_unsupported(monkeypatch):
    install(monkeypatch, payload('GBP'))
    assert producer.fetch_verified_metric_evidence(TICKER, question='Cite financial trends.') == []
    data = payload(form='6-K')
    assert sec_client.parse_company_fact_records(data, concept=CONCEPTS['revenue'], unit='EUR') == []


def test_combined_foundation_does_not_mix_independently_valid_currencies(monkeypatch):
    install(monkeypatch, payload())
    euros = producer.fetch_verified_metric_evidence(TICKER, question='Cite financial trends.')
    install(monkeypatch, payload('USD'))
    dollars = producer.fetch_verified_metric_evidence(TICKER, question='Cite financial trends.')
    assert foundation.build_financial_foundation(TICKER, [euros[0], dollars[1]],
        None, expected_cik=CIK) is None


def test_20f_amendment_supersedes_same_day_original_without_hiding_conflict():
    data = payload()
    rows = data['facts']['us-gaap'][CONCEPTS['revenue']]['units']['EUR']
    amendment = {**rows[1], 'form': '20-F/A', 'val': 1300000, 'accn': '0001234567-26-000002'}
    rows.append(amendment)
    args = dict(ticker=TICKER, expected_cik=CIK, concepts=(CONCEPTS['revenue'],), metric_name='revenue', unit='EUR')
    records = sec_client.parse_company_fact_records(data, concept=CONCEPTS['revenue'], unit='EUR')
    item = comparable_metric_evidence(records, **args)
    assert item.verified_claims[0]['source'] == '20-F/A'
    assert item.verified_claims[0]['raw_value'] == 1300000
    rows.append({**amendment, 'val': 1400000, 'accn': '0001234567-26-000003'})
    records = sec_client.parse_company_fact_records(data, concept=CONCEPTS['revenue'], unit='EUR')
    assert comparable_metric_evidence(records, **args) is None


def test_as_of_boundary_excludes_later_20f(monkeypatch):
    install(monkeypatch, payload())
    assert producer.fetch_verified_metric_evidence(TICKER,
        question='Cite financial trends.', as_of='2026-02-24') == []


@pytest.mark.parametrize('mutation', ['currency', 'unit', 'display', 'reference'])
def test_final_foundation_rejects_tampered_eur_claim(monkeypatch, mutation):
    install(monkeypatch, payload())
    items = producer.fetch_verified_metric_evidence(TICKER, question='Cite financial trends.')
    item = items[0]
    if mutation == 'currency':
        item.verified_claims[0]['currency'] = 'USD'
    elif mutation == 'unit':
        item.verified_claims[1]['unit'] = 'USD'
    elif mutation == 'display':
        item.verified_claims[0]['value_text'] = '$1,200,000'
    else:
        item.verified_claims[0]['document_ref']['url'] = 'https://example.com/wrong'
    assert foundation._rebuild(item, ticker=TICKER, cik=CIK, name='revenue',
        concepts=foundation.CORE_METRICS['revenue']) is None
