"""Coverage names only selected, final-bound segment evidence; no promotion."""
from copy import deepcopy

import pytest

from app.services.financial_thesis_foundation import build_financial_foundation
from app.services.evidence_references import admit_evidence
from app.services import segment_product_context as products, segment_financial_context as financial
from test_segment_financial_context import CIK, xml, document
from test_segment_product_context import QUOTE
from test_financial_thesis_foundation import pair


def items():
    doc = document(xml().replace('Item 1A. Risk Factors', QUOTE + ' Item 1A. Risk Factors'))
    return (products.extract_segment_products(doc,ticker='ZQXB',cik=CIK)[0],
            financial.extract_segment_financial_context(doc,ticker='ZQXB',cik=CIK)[0])


def build(extra, refs=None):
    return build_financial_foundation('ZQXB',pair(ticker='ZQXB',cik=CIK)+extra,refs,expected_cik=CIK)


def test_named_products_and_reported_results_do_not_fill_issuer_wide_facets():
    product, result = items()
    answer = build([result,product])
    coverage=answer['business_context_coverage']
    assert coverage['complete_business_model'] is False
    assert all(f['status']=='not_verified' for f in coverage['facets'])
    scoped=coverage['scoped_context']
    assert [r['kind'] for r in scoped]==['reported_segment_results','segment_product_list']
    assert scoped[0]['segment_labels']==['Water Systems','Clinical Devices']
    assert scoped[1]['segment_label']=='Clinical Devices'
    assert 'Named-segment product list: Clinical Devices [E4].' in answer['answer']
    assert 'Reported annual segment results: Water Systems, Clinical Devices; 2024-01-01 to 2024-12-31 (USD) [E3].' in answer['answer']
    assert 'issuer-wide coverage remains unverified' in answer['answer']
    assert 'Standalone segment economics' in coverage['limitation']
    assert 'business model and competitive position' in answer['unanswered_parts']


@pytest.mark.parametrize('kind',['product','financial'])
@pytest.mark.parametrize('mutation',['stale','scope','summary','issuer','unavailable'])
def test_rejected_binding_cannot_populate_scoped_coverage(kind,mutation):
    product,result=deepcopy(items());item=product if kind=='product' else result
    if mutation=='stale':item.freshness_status='stale'
    elif mutation=='summary':item.summary='Unsupported.'
    elif mutation=='issuer':item.url=item.url.replace('/1234567/','/7654321/')
    elif mutation=='unavailable':item.availability_status='unavailable'
    elif kind=='product':item.product_disclosures[0]['product_context']['scope']['kind']='issuer'
    else:item.segment_disclosures[0]['segment_context']['scope']='consolidated'
    answer=build([item])
    assert 'scoped_context' not in answer['business_context_coverage']
    assert 'Business context coverage' not in answer['answer']


def test_absent_admitted_reference_cannot_fill_scoped_coverage():
    product,result=items();all_items=pair(ticker='ZQXB',cik=CIK)+[result,product]
    admitted,refs,_=admit_evidence(all_items,evaluated_at='2026-10-22')
    answer=build_financial_foundation('ZQXB',admitted,refs[:-1],expected_cik=CIK)
    assert [r['kind'] for r in answer['business_context_coverage']['scoped_context']]==['reported_segment_results']
    assert 'Named-segment product list:' not in answer['answer']


def test_caller_annotations_do_not_create_scope_or_alias_links():
    product,result=items()
    product.product_disclosures[0]['business_context_roles']=['activities','revenue_model']
    product.product_disclosures[0]['issuer_scope']='complete'
    result.segment_disclosures[0]['label_aliases']={'Clinical Devices':'Entire issuer'}
    answer=build([result,product]);coverage=answer['business_context_coverage']
    assert coverage['complete_business_model'] is False
    assert all(f['status']=='not_verified' for f in coverage['facets'])
    assert coverage['scoped_context'][1]['segment_label']=='Clinical Devices'
    assert 'Entire issuer' not in answer['answer']


def test_no_segment_evidence_preserves_original_coverage_contract():
    result=build([])
    assert 'scoped_context' not in result['business_context_coverage']
    assert result['business_context_coverage']['scope']=='sampled_issuer_descriptions'


def test_custom_admitted_ids_and_dates_are_retained():
    product,result=items();all_items=pair(ticker='ZQXB',cik=CIK)+[result,product]
    admitted,refs,_=admit_evidence(all_items,evaluated_at='2026-10-22')
    for i,ref in enumerate(refs):ref['id']=f'E{i+17}'
    answer=build_financial_foundation('ZQXB',admitted,refs,expected_cik=CIK)
    scoped=answer['business_context_coverage']['scoped_context']
    assert [r['reference_ids'] for r in scoped]==[['E19'],['E20']]
    assert scoped[0]['period_start']=='2024-01-01' and scoped[0]['period_end']=='2024-12-31'


def test_management_explanation_keeps_both_periods_and_attribution():
    from test_segment_sales_explanations import extracted
    result=build([extracted()])
    rows=result['business_context_coverage']['scoped_context']
    assert rows[1]=={'kind':'management_sales_explanation','scope':'reported_segment_sales',
        'segment_label':'Water Systems','current_start':'2025-01-01','current_end':'2025-12-31',
        'prior_start':'2024-01-01','prior_end':'2024-12-31','reference_ids':['E3']}
    assert 'Management-attributed segment sales explanation: Water Systems;' in result['answer']
    assert 'independently established causal drivers remain unverified' in result['answer']
