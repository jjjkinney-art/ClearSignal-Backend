"""Coverage comes from admitted source descriptions, never caller annotations."""
from copy import deepcopy

import pytest

from app.schemas import InvestmentThesis
from app.services import thesis_disclosures as disclosures
from app.services.business_context import description_roles
from app.services.financial_thesis_foundation import build_financial_foundation
from app.services.source_answer import apply_source_answer_gate
from app.services.evidence_references import admit_evidence
from test_thesis_disclosures import document, RISK, QUESTION
from test_financial_thesis_foundation import pair

ACTIVITY = 'We manufacture specialized components and distribute our products through independent dealers.'
DUPLICATE_ROLE = 'We manufacture industrial components and distribute these products through independent dealers.'
REVENUE = 'We generate revenue primarily from sales of products and related customer support services.'
CHANNELS = 'Products are sold directly to retailers and also through independent distributors.'


def items_for(*quotes):
    doc = document('Item 1. Business ' + ' '.join(quotes) +
                   f' Item 1A. Risk Factors {RISK} Item 1B. Unresolved Staff Comments')
    return doc, disclosures.extract_business_descriptions(doc, ticker='AAPL', cik='320193')


def by_facet(result):
    return {row['facet']: row for row in result['business_context_coverage']['facets']}


def test_explicit_revenue_replaces_a_redundant_second_activity_without_raising_cap():
    doc, items = items_for(ACTIVITY, DUPLICATE_ROLE, REVENUE, CHANNELS)
    assert [item.business_disclosures[0]['quote'] for item in items] == [ACTIVITY, REVENUE]
    assert len(items) == 2
    for item in items:
        value = disclosures.bound_business_description(item, ticker='AAPL', cik='320193')
        assert value and doc.text[value['start_offset']:value['end_offset']] == value['quote']
    result = build_financial_foundation('AAPL', pair() + items, None, expected_cik='320193')
    coverage = by_facet(result)
    assert coverage['activities']['reference_ids'] == ['E3']
    assert coverage['revenue_model']['reference_ids'] == ['E4']
    assert coverage['customers_and_channels']['reference_ids'] == ['E3']
    assert coverage['segments']['status'] == 'not_verified'
    assert 'business model completeness' in result['unanswered_parts']
    assert result['business_context_coverage']['complete_business_model'] is False
    assert ACTIVITY in result['answer'] and REVENUE in result['answer']


def test_distribution_alone_cannot_close_activities_revenue_or_full_model():
    _, items = items_for(CHANNELS)
    result = build_financial_foundation('AAPL', pair() + items, None, expected_cik='320193')
    coverage = by_facet(result)
    assert coverage['customers_and_channels']['reference_ids'] == ['E3']
    assert all(coverage[key]['status'] == 'not_verified' for key in ('activities', 'revenue_model', 'segments'))
    assert 'business model completeness' in result['unanswered_parts']
    assert 'How the issuer generates revenue: not verified in the admitted descriptions.' in result['answer']


def test_named_segment_list_does_not_imply_segment_economics_or_a_revenue_model():
    quote = 'The Company has two reportable business segments: Consumer Banking and Wealth Management.'
    _, items = items_for(quote)
    result = build_financial_foundation('AAPL', pair() + items, None, expected_cik='320193')
    coverage = by_facet(result)
    assert coverage['segments']['status'] == 'source_description_present'
    assert coverage['activities']['status'] == coverage['revenue_model']['status'] == 'not_verified'
    assert 'segment economics' in result['business_context_coverage']['limitation']


def test_customer_revenue_is_not_issuer_revenue():
    quote = 'We provide software that enables customers to generate revenue from transaction fees.'
    _, items = items_for(quote)
    assert len(items) == 1
    assert 'revenue_model' not in description_roles(quote)
    result = build_financial_foundation('AAPL', pair() + items, None, expected_cik='320193')
    assert by_facet(result)['revenue_model']['status'] == 'not_verified'


@pytest.mark.parametrize('quote', [
    'We provide custody and payment processing services to institutional customers.',
    'We offer document workflow software and related support services to enterprise clients.',
    'To help our customers manage workflow errors, we provide software products and integration services.',
])
def test_explicit_customer_descriptions_are_covered_without_revenue_inference(quote):
    _, items = items_for(quote)
    assert len(items) == 1
    result = build_financial_foundation('AAPL', pair() + items, None, expected_cik='320193')
    assert by_facet(result)['customers_and_channels']['status'] == 'source_description_present'
    assert by_facet(result)['revenue_model']['status'] == 'not_verified'


def test_complementary_ties_keep_original_choice_and_order():
    _, items = items_for(ACTIVITY, DUPLICATE_ROLE)
    assert [item.business_disclosures[0]['quote'] for item in items] == [ACTIVITY, DUPLICATE_ROLE]


@pytest.mark.parametrize('quote', [
    'We generate revenue from borrowing under credit agreements with independent financial institutions.',
    'We generate revenue primarily from sales of products and expect rapid growth in the coming year.',
    'Our competitor generates revenue from sales of products and related customer support services.',
    'We offer training and mentoring services to our employees throughout the global workforce.',
    'We generate revenue from sales of products at 20% margins through our retail channels.',
])
def test_breadth_selection_cannot_admit_previously_ineligible_prose(quote):
    _, items = items_for(ACTIVITY, DUPLICATE_ROLE, quote)
    assert [item.business_disclosures[0]['quote'] for item in items] == [ACTIVITY, DUPLICATE_ROLE]


@pytest.mark.parametrize('mutate', [
    lambda x: setattr(x, 'source_tier', 'secondary'),
    lambda x: setattr(x, 'freshness_status', 'stale'),
    lambda x: setattr(x, 'availability_status', 'unavailable'),
    lambda x: setattr(x, 'url', x.url.replace('/320193/', '/999999/')),
    lambda x: x.business_disclosures[0].update(ticker='OTHER'),
    lambda x: x.business_disclosures[0].update(quote=REVENUE),
])
def test_rejected_binding_cannot_fill_business_coverage(mutate):
    _, items = items_for(CHANNELS)
    mutate(items[0])
    result = build_financial_foundation('AAPL', pair() + items, None, expected_cik='320193')
    assert all(row['status'] == 'not_verified' and not row['reference_ids']
               for row in result['business_context_coverage']['facets'])
    assert 'business model and competitive position' in result['unanswered_parts']


def test_caller_facet_annotations_are_ignored():
    _, items = items_for(CHANNELS)
    items[0].business_disclosures[0]['business_context_roles'] = ['revenue_model', 'activities']
    result = build_financial_foundation('AAPL', pair() + items, None, expected_cik='320193')
    assert by_facet(result)['revenue_model']['status'] == by_facet(result)['activities']['status'] == 'not_verified'


def test_unreferenced_description_does_not_fill_coverage():
    _, items = items_for(REVENUE)
    admitted, refs, _ = admit_evidence(pair() + items, evaluated_at='2025-08-05')
    result = build_financial_foundation('AAPL', admitted, refs[:2], expected_cik='320193')
    assert all(not row['reference_ids'] for row in result['business_context_coverage']['facets'])


def test_final_source_answer_preserves_admitted_ids_and_keeps_partial_status(monkeypatch):
    monkeypatch.setattr(disclosures.sec_provider, '_load_ticker_cik_map', lambda: {'AAPL': '320193'})
    _, items = items_for(ACTIVITY, REVENUE)
    admitted, refs, _ = admit_evidence(pair() + items, evaluated_at='2025-08-05')
    refs = deepcopy(refs)
    for i, ref in enumerate(refs): ref['id'] = f'E{i + 7}'
    thesis = InvestmentThesis(ticker='AAPL', company_name='Synthetic issuer')
    result = apply_source_answer_gate(thesis, QUESTION, admitted, references=refs)
    assert result['status'] == 'partial' and thesis.confidence_score == 0
    assert by_facet(result)['revenue_model']['reference_ids'] == ['E10']
    assert by_facet(result)['activities']['reference_ids'] == ['E9']
    assert 'business model completeness' in result['unanswered_parts']
    assert 'competitive position' in result['unanswered_parts']
    assert 'valuation and expected returns' in result['unanswered_parts']
    assert 'How the issuer generates revenue: sampled issuer description [E10].' in thesis.direct_answer
