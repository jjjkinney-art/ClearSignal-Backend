"""Synthetic final-gate composition and document/segment separation."""
from copy import deepcopy
from dataclasses import replace

import pytest

from app.schemas import InvestmentThesis
from app.services.evidence_references import admit_evidence
from app.services.source_answer import apply_source_answer_gate
from app.services import annual_cash_flow_context as cash
from app.services import segment_financial_context as segments
from app.services import segment_revenue_policy as policies
from app.services.operating_research_questions import operating_research_questions
from test_annual_cash_flow_context import text as cash_text, observation
from test_segment_revenue_policy import text as policy_text
from test_segment_financial_context import document, xml
from test_financial_thesis_foundation import pair


@pytest.fixture(autouse=True)
def synthetic_identity(monkeypatch):
    monkeypatch.setattr('app.services.providers.sec_provider._load_ticker_cik_map',
                        lambda: {'ZQXB': '1234567'})


def items(label='Clinical Devices'):
    source = xml().replace('2024', '2025').replace('Clinical Devices', label)
    source = source.replace('</body>', '<p>' + policy_text().replace('Clinical Devices', label)
                            + '</p><p>' + cash_text() + '</p></body>')
    doc = replace(document(source), published_at='2026-03-13',
                  cash_flow_observations=(observation(2025, -100), observation(2024, -200)))
    return (segments.extract_segment_financial_context(doc, ticker='ZQXB', cik='1234567')
            + policies.extract_segment_revenue_policies(doc, ticker='ZQXB', cik='1234567')
            + cash.extract_annual_cash_flow_context(doc, ticker='ZQXB', cik='1234567'))


def answer(values):
    financial = pair(ticker='ZQXB', cik='1234567')
    admitted, refs, _ = admit_evidence(financial + values, evaluated_at='2026-10-24')
    thesis = InvestmentThesis(ticker='ZQXB', company_name='Synthetic issuer')
    result = apply_source_answer_gate(thesis, 'What is the investment thesis for ZQXB? Cite material claims.',
                                      admitted, references=refs)
    return result, thesis.direct_answer


@pytest.mark.parametrize('label', ['Clinical Devices', 'Industrial Sensors', 'Cloud Platforms'])
def test_final_gate_links_only_bound_evidence_as_questions(label):
    values = items(label)
    assert len(values) == 4
    result, prose = answer(values)
    questions = [i for i in result['inferences'] if i['kind'] == 'operating_research_question']
    assert [q['topic'] for q in questions] == ['contract_cost_exposure', 'annual_cash_conversion']
    assert questions[0]['segment_label'] == label
    assert questions[0]['period_start'] == questions[1]['period_start'] == '2025-01-01'
    assert questions[0]['reference_ids'] == ['E3', 'E4']
    assert questions[1]['reference_ids'] == ['E6']
    opening = prose.split('Positive, rising reported comparisons:')[0]
    assert 'Operating questions to resolve' in opening
    assert label + ', reported results' in opening
    assert 'limited material-escalation exception?' in opening
    assert 'later interim movements separately' in opening
    for question in questions:
        assert question['causal_attribution_established'] is False
        assert question['materiality_assessed'] is False
        assert prose.count(question['text']) == 1
        assert all(f'[{ref}]' in opening for ref in question['reference_ids'])
    assert all(prose.count(claim['claim']) == 1 for claim in result['claims'])
    assert result['status'] == 'partial'
    assert 'valuation and expected returns' in result['unanswered_parts']


@pytest.mark.parametrize('change', ['label', 'hash', 'url', 'date', 'missing_doc', 'duplicate'])
def test_no_contract_link_across_unmatched_or_ambiguous_final_rows(change):
    result, _ = answer(items())
    rows = deepcopy(result['claims'])
    policy = next(r for r in rows if r.get('policy_context', {}).get('role') == 'contract_terms')
    if change == 'label': policy['policy_context']['segments'] = ['Other Devices']
    elif change == 'hash': policy['document_ref']['content_hash'] = '0' * 64
    elif change == 'url': policy['document_ref']['url'] += '?other-filing'
    elif change == 'date': policy['document_ref']['published_at'] = '2025-03-13'
    elif change == 'missing_doc': policy.pop('document_ref')
    elif change == 'duplicate': rows += [deepcopy(next(r for r in rows if 'segment_context' in r))]
    questions = operating_research_questions(rows)
    assert [q['topic'] for q in questions] == ['annual_cash_conversion']


@pytest.mark.parametrize('change', ['cash_sign', 'policy_terms', 'cash_period', 'policy_summary'])
def test_unbound_evidence_cannot_create_research_question(change):
    values = deepcopy(items())
    if change == 'cash_sign': values[-1].cash_flow_disclosures[0]['observations'][0]['sign'] = ''
    elif change == 'cash_period': values[-1].cash_flow_disclosures[0]['cash_flow_context']['current_start'] = '2025-04-01'
    elif change == 'policy_terms': values[1].revenue_policy_disclosures[0]['policy_context']['price_terms'] = 'cost_pass_through'
    elif change == 'policy_summary': values[1].summary = 'Profits will rise.'
    result, _ = answer(values)
    topics = [q['topic'] for q in result['inferences'] if q['kind'] == 'operating_research_question']
    assert topics == (['contract_cost_exposure'] if change.startswith('cash') else ['annual_cash_conversion'])


def test_absent_sources_do_not_produce_generic_question_filler():
    result, prose = answer([])
    assert not any(i['kind'] == 'operating_research_question' for i in result['inferences'])
    assert 'Operating questions to resolve' not in prose
