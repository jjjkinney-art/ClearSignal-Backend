"""Run 9 fixes: Human Capital exclusion and disclosure-only partial answers.

All prose is synthetic; no test claims these are actual SEC disclosures.
"""
import re
from collections import OrderedDict
from types import SimpleNamespace

import pytest

from app.providers import sec_client
from app.schemas import InvestmentThesis
from app.services import disclosure_only_answer as only
from app.services import thesis_disclosures as service
from app.services.evidence_references import admit_evidence
from app.services.source_answer import apply_source_answer_gate
from test_thesis_disclosures import BUSINESS, QUESTION, RISK, document
from test_financial_thesis_foundation import pair

TRAINING = 'We offer leadership training and support to ensure that all employees are supported in their careers.'
AFTER = 'We also design and sell calibration services to industrial customers through our direct sales force.'
VALID_RISKS = [
    'Because our credit facility accounts for a significant portion of our funding, our inability to refinance '
    'debt maturities could adversely affect our liquidity and operating results.',
    'Because our credit facility accounts for a significant portion of our funding, higher refinancing costs '
    'could adversely affect our liquidity and financial condition.']


def annual(body):
    return document(f'Item 1. Business Overview. {body} Item 1A. Risk Factors {RISK} Item 1B. Unresolved Staff Comments')


# --- Human Capital zones -----------------------------------------------------------------------------

def test_a_zone_runs_from_its_heading_to_the_next_standard_subsection():
    window = f'Overview. {BUSINESS} Human Capital Resources {TRAINING} Our Products {AFTER}'
    (start, end), = service.human_capital_zones(window)
    assert window[start:end].startswith('Human Capital Resources') and TRAINING in window[start:end]
    assert AFTER not in window[start:end] and window[end:].startswith('Our Products')


def test_a_zone_may_run_to_the_end_of_item_1_but_not_without_a_clear_end():
    short = f'Overview. {BUSINESS} Human Capital Management {TRAINING}'
    assert service.human_capital_zones(short) == [(short.index('Human Capital'), len(short))]
    long = short + ' Another ordinary sentence follows here. ' * 400
    assert len(long) - long.index('Human Capital') > service._HUMAN_CAPITAL_MAX_TAIL
    assert service.human_capital_zones(long) == []


def test_a_cross_reference_is_not_a_heading():
    for sentence in (f'We describe our workforce in Human Capital Resources below. {BUSINESS}',
                     f'For more information, see “Human Capital” in this report. {BUSINESS}',
                     f'Our approach is covered in the Human Capital section. {BUSINESS}'):
        assert service.human_capital_zones(sentence) == [], sentence


def test_workforce_sentences_are_excluded_and_later_descriptions_still_qualify():
    stats = {}
    found = service.extract_business_descriptions(
        annual(f'{BUSINESS} Human Capital Resources {TRAINING} Our Products {AFTER}'),
        ticker='AAPL', cik='320193', diagnostics=stats)
    quotes = [item.business_disclosures[0]['quote'] for item in found]
    assert TRAINING not in quotes and quotes == [BUSINESS, AFTER]
    assert stats['rejection_counts']['human_capital_section'] >= 1


def test_the_same_sentence_outside_a_human_capital_section_is_judged_as_before():
    stats = {}
    service.extract_business_descriptions(
        annual(f'{BUSINESS} Workforce Notes {TRAINING} Our Products {AFTER}'),
        ticker='AAPL', cik='320193', diagnostics=stats)
    assert 'human_capital_section' not in stats['rejection_counts']


# --- taxonomy record and the financial gap -----------------------------------------------------------

@pytest.fixture
def taxonomies(monkeypatch):
    monkeypatch.setattr(sec_client, '_OBSERVED_TAXONOMIES', OrderedDict())
    return sec_client._OBSERVED_TAXONOMIES


def _facts(**counts):
    return {'cik': 1234567, 'facts': {name: {f'C{i}': {} for i in range(n)} for name, n in counts.items()}}


def test_taxonomies_are_recorded_only_from_a_received_response(monkeypatch, taxonomies):
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: _facts(**{'ifrs-full': 230, 'dei': 1}))

    monkeypatch.setattr(sec_client.requests, 'get', get)
    assert sec_client.observed_fact_taxonomies('1234567') is None
    assert sec_client.get_company_fact_records_for_concept_units(
        '1234567', concept_units=(('Revenues', 'USD'),)) == []
    assert sec_client.observed_fact_taxonomies('1234567') == {'ifrs-full': 230}
    assert len(calls) == 1                    # recording made no request of its own
    assert sec_client.observed_fact_taxonomies('7654321') is None and sec_client.observed_fact_taxonomies('x') is None
    # A response for a different issuer is rejected before anything is recorded.
    monkeypatch.setattr(sec_client.requests, 'get', lambda url, **kw: SimpleNamespace(
        raise_for_status=lambda: None, json=lambda: {**_facts(**{'us-gaap': 5}), 'cik': 999}))
    sec_client.get_company_fact_records_for_concept_units('7654321', concept_units=(('Revenues', 'USD'),))
    assert sec_client.observed_fact_taxonomies('7654321') is None


@pytest.mark.parametrize('observed, names_ifrs', [
    ({'ifrs-full': 230}, True), ({'ifrs-full': 304, 'us-gaap': 4}, True),
    ({'us-gaap': 400}, False), ({'ifrs-full': 10, 'us-gaap': 10}, False), ({}, False), (None, False)])
def test_ifrs_is_named_only_when_retrieval_confirmed_it(taxonomies, observed, names_ifrs):
    if observed is not None:
        taxonomies[1234567] = observed
    gap = only.financial_gap('1234567')
    assert gap['status'] == 'not_established'
    assert ('IFRS' in gap['text']) == names_ifrs
    assert gap['reason'] == ('ifrs_taxonomy_not_supported' if names_ifrs else 'comparisons_unavailable')


# --- the partial answer ---------------------------------------------------------------------------------

def _setup(monkeypatch, body, ticker='ZQXB', cik='1234567'):
    from app.services import issuer_identity
    directory = issuer_identity.parse_directory({'0': {'ticker': ticker, 'cik_str': int(cik), 'title': 'Synthetic test issuer'}})
    monkeypatch.setattr(issuer_identity, '_load_directory', lambda: directory)
    url = document().final_url.replace('/320193/', f'/{cik}/')
    doc = document(f'Item 1. Business Overview. {body} Item 1A. Risk Factors ' + ' '.join(VALID_RISKS)
                   + ' Item 1B. Unresolved Staff Comments', final_url=url, requested_url=url)
    monkeypatch.setattr(service.sec_provider, '_load_ticker_cik_map', lambda: {ticker: cik})
    monkeypatch.setattr(service.sec_provider, 'fetch_recent_filings', lambda *a, **kw: [
        SimpleNamespace(url=url, timestamp=doc.published_at, document_type='10-K')])
    monkeypatch.setattr(service, 'fetch_public_document', lambda *a, **kw: doc)
    return ticker, cik


def _gate(monkeypatch, taxonomies, observed=None, with_financials=False):
    ticker, cik = _setup(monkeypatch, BUSINESS)
    if observed is not None:
        taxonomies[int(cik)] = observed
    fetched = service.fetch_thesis_disclosures(ticker, question=f'What is the investment thesis for {ticker}?')
    items = (pair(ticker=ticker, cik=cik) if with_financials else []) + fetched
    admitted, refs, _ = admit_evidence(items, evaluated_at='2025-08-05')
    thesis = InvestmentThesis(ticker=ticker, company_name='Synthetic test issuer')
    result = apply_source_answer_gate(
        thesis, f'What is the investment thesis for {ticker}, what supports it, and what could invalidate it? '
                'Cite material claims.', admitted, references=refs)
    return result, thesis, refs


def test_disclosures_are_delivered_when_no_financial_comparison_exists(monkeypatch, taxonomies):
    result, thesis, refs = _gate(monkeypatch, taxonomies, {'ifrs-full': 230})
    assert result['status'] == 'partial' and result['content_scope'] == 'disclosures_only'
    kinds = {row['claim_kind'] for row in result['claims']}
    assert kinds == {'issuer_business_description', 'issuer_disclosed_risk'}
    assert kinds <= only.DISCLOSURE_ONLY_KINDS
    answer = thesis.direct_answer
    assert answer.startswith('Source-bound disclosures only (partial): no financial analysis was completed')
    assert BUSINESS in answer and VALID_RISKS[0] in answer
    assert 'IFRS' in answer and result['financial_analysis'] == {
        'status': 'not_established', 'reason': 'ifrs_taxonomy_not_supported', 'observed_taxonomies': {'ifrs-full': 230}}
    assert all(any(ref['id'] == row['reference_id'] for ref in refs) for row in result['claims'])
    assert thesis.confidence_score == 0 and thesis.directional_stance == ''


def test_the_partial_answer_states_no_figure_baseline_threshold_or_inference(monkeypatch, taxonomies):
    result, thesis, _ = _gate(monkeypatch, taxonomies, {'ifrs-full': 230})
    assert result['inferences'] == []
    body = re.sub(r'\[E\d+\]|10-K filed \d{4}-\d{2}-\d{2}', '', thesis.direct_answer)
    for quote in (BUSINESS, *VALID_RISKS):
        body = body.replace(quote, '')
    m = re.search(r'\d|%|\$', body)
    assert not m, body[max(0, m.start()-80):m.end()+80]
    assert 'Historical baseline' not in body and 'Monitoring condition' not in body
    for gap in ('financial performance and reported comparisons', 'monitoring baselines', 'valuation and expected returns'):
        assert gap in result['unanswered_parts']
    assert not any(row['claim_kind'].endswith(('comparison', 'explanation')) for row in result['claims'])


def test_without_confirmation_the_reason_is_generic_and_never_ifrs(monkeypatch, taxonomies):
    for observed in (None, {'us-gaap': 400}):
        result, thesis, _ = _gate(monkeypatch, taxonomies, observed)
        assert 'IFRS' not in thesis.direct_answer and 'ifrs' not in str(result['financial_analysis']).lower().replace(
            'comparisons_unavailable', '')
        assert result['financial_analysis']['reason'] == 'comparisons_unavailable'


def test_a_financial_foundation_still_wins_when_it_can_be_built(monkeypatch, taxonomies):
    result, thesis, _ = _gate(monkeypatch, taxonomies, None, with_financials=True)
    assert result['status'] == 'partial' and 'content_scope' not in result
    assert any(row['claim_kind'] == 'reported_financial_comparison' for row in result['claims'])
    assert not thesis.direct_answer.startswith('Source-bound disclosures only')


def test_nothing_bound_means_no_partial_answer(monkeypatch, taxonomies):
    ticker, cik = _setup(monkeypatch, BUSINESS)
    assert only.build_disclosure_only(ticker, [], None, expected_cik=cik) is None
    assert only.build_disclosure_only(ticker, [], None, expected_cik='not-a-cik') is None


# --- export classification ---------------------------------------------------------------------------------

def test_the_export_keeps_its_disclosure_kinds_equal_to_the_application():
    from validation.ordinary_native_export import DISCLOSURE_ONLY_CLAIM_KINDS
    assert DISCLOSURE_ONLY_CLAIM_KINDS == only.DISCLOSURE_ONLY_KINDS


def _payload(scope, *kinds):
    source = {'status': 'partial', 'claims': [{'claim_kind': kind} for kind in kinds]}
    if scope:
        source['content_scope'] = scope
    return {'answer': {'source_answer': source}}


@pytest.mark.parametrize('scope, kinds, expected', [
    ('disclosures_only', ('issuer_business_description', 'issuer_disclosed_risk'), 'source_bound_disclosures_only'),
    ('disclosures_only', ('issuer_business_description', 'reported_financial_comparison'), 'source_bound_claims'),
    (None, ('issuer_business_description', 'issuer_disclosed_risk'), 'source_bound_claims'),
    (None, ('reported_financial_comparison', 'issuer_disclosed_risk'), 'source_bound_claims')])
def test_only_a_marked_disclosure_only_answer_is_counted_apart(scope, kinds, expected):
    from validation.ordinary_native_export import answer_content
    assert answer_content('answered_unadjudicated', _payload(scope, *kinds)) == expected


def test_a_disclosure_only_answer_is_not_insufficient_evidence_and_not_financial_analysis():
    from validation.ordinary_native_export import answer_content
    insufficient = {'answer': {'source_answer': {'status': 'insufficient_claim_evidence', 'claims': []}}}
    assert answer_content('answered_unadjudicated', insufficient) == 'insufficient_evidence'
    assert answer_content('answered_unadjudicated', _payload('disclosures_only', 'issuer_disclosed_risk')) \
        not in {'source_bound_claims', 'insufficient_evidence'}
