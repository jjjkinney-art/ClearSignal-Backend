"""Invented named-segment disclosures; no claim of actual competitive strength."""
from copy import deepcopy
from dataclasses import replace

import pytest

from app.schemas import InvestmentThesis
from app.services import thesis_competition as service
from app.services.evidence_references import admit_evidence
from app.services.source_answer import apply_source_answer_gate
from test_financial_thesis_foundation import pair
from test_thesis_disclosures import document, BUSINESS, RISK

QUOTE='The Components segment competes for its business primarily on the basis of technical competence, product quality, manufacturing experience, and price.'
SCOPE={'kind':'named_segment','label':'Components'}


def segment_document(quote=QUOTE,*,in_risk=False):
    text=(f'Item 1. Business Overview. {BUSINESS} '
          + ('' if in_risk else quote+' ')
          + f'Item 1A. Risk Factors {RISK} '
          + (quote+' ' if in_risk else '')
          + 'Item 1B. Unresolved Staff Comments')
    url=document().final_url.replace('/320193/','/1234567/')
    return document(text,requested_url=url,final_url=url)


@pytest.mark.parametrize('label',['Components','Retail Banking','Housewares/Small Appliance','Energy & Materials'])
@pytest.mark.parametrize('lead',['','\ufeff \ufeff '])
def test_named_segment_quote_remains_exact_and_scope_bound(label,lead):
    quote=lead+QUOTE.replace('Components',label)
    doc=segment_document(quote)
    item,=service.extract_competition_descriptions(doc,ticker='ZQXB',cik='1234567')
    value=service.bound_competition_description(item,ticker='ZQXB',cik='1234567')
    assert value['competition_scope']=={'kind':'named_segment','label':label}
    assert doc.text[value['start_offset']:value['end_offset']]==value['quote']==quote
    assert value['document_ref']['quote']==quote
    assert 'not a company-wide competitive assessment' in item.summary
    assert 'durable advantage remain unverified' in item.summary


def test_final_source_answer_preserves_segment_and_remaining_company_gaps():
    item,=service.extract_competition_descriptions(segment_document(),ticker='ZQXB',cik='1234567')
    admitted,refs,_=admit_evidence(pair(ticker='ZQXB',cik='1234567')+[item],evaluated_at='2025-08-05')
    thesis=InvestmentThesis(ticker='ZQXB',company_name='Invented issuer')
    # Expected issuer identity comes from the same fixed local map used by the
    # existing pair fixtures, never from a new SEC directory request.
    from app.services.providers import sec_provider
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sec_provider,'_load_ticker_cik_map',lambda:{'ZQXB':'1234567'})
        result=apply_source_answer_gate(thesis,'What is the investment thesis for ZQXB? Cite material claims.',admitted,references=refs)
    claim,=[r for r in result['claims'] if r['claim_kind']=='issuer_competition_description']
    assert claim['competition_scope']==SCOPE and claim['reference_id'] in {r['id'] for r in refs}
    assert QUOTE in thesis.direct_answer and result['status']=='partial'
    assert any('competitive position' in p for p in result['unanswered_parts'])
    assert 'valuation and expected returns' in result['unanswered_parts']
    assert thesis.confidence_score==0


@pytest.mark.parametrize('quote',[
    QUOTE.replace('The Components segment','This segment'),
    QUOTE.replace('The Components segment','It'),
    QUOTE.replace('competes','may compete'),
    QUOTE.replace('competes','expects to compete'),
    QUOTE.replace('technical competence','superior technology'),
    QUOTE.replace('technical competence','80% market share'),
    QUOTE[:-1]+' and we believe we have a durable advantage.',
    QUOTE.replace('Components','Workforce'),
    QUOTE.replace('Components',"Competitor's Components"),
])
def test_ambiguous_forecast_promotional_numeric_or_internal_quotes_withheld(quote):
    assert service.extract_competition_descriptions(segment_document(quote),ticker='ZQXB',cik='1234567')==[]


@pytest.mark.parametrize('mutate',[
    lambda i:i.competition_disclosures[0].pop('competition_scope'),
    lambda i:i.competition_disclosures[0]['competition_scope'].update(label='Entire company'),
    lambda i:i.competition_disclosures[0]['competition_scope'].update(kind='issuer'),
    lambda i:i.competition_disclosures[0].update(ticker='OTHER'),
    lambda i:setattr(i,'url',i.url.replace('/1234567/','/9999999/')),
    lambda i:setattr(i,'freshness_status','stale'),
    lambda i:i.competition_disclosures[0].update(start_offset=True),
    lambda i:i.competition_disclosures[0]['document_ref'].update(quote='Altered quoted evidence.'),
])
def test_forged_or_mutated_segment_bindings_fail_closed(mutate):
    item,=service.extract_competition_descriptions(segment_document(),ticker='ZQXB',cik='1234567')
    mutate(item)
    # Rebuilding prose from corrupted metadata must not bypass scope checks.
    item.summary=service._summary(item.competition_disclosures[0])
    assert service.bound_competition_description(item,ticker='ZQXB',cik='1234567') is None


def test_no_risk_only_outside_section_incomplete_or_predecessor_exception():
    assert service.extract_competition_descriptions(segment_document(in_risk=True),ticker='ZQXB',cik='1234567')==[]
    for text in [QUOTE+f' Item 1. Business {BUSINESS} Item 1A. Risk Factors {RISK} Item 1B. Unresolved Staff Comments',
                 'Item 1. Business '+QUOTE]:
        assert service.extract_competition_descriptions(replace(segment_document(),text=text),ticker='ZQXB',cik='1234567')==[]
    assert service.extract_competition_descriptions(segment_document(),ticker='ZQXB',cik='9999999')==[]


def test_company_wide_disclosure_cannot_gain_forged_segment_scope():
    doc=segment_document('We compete on the basis of product performance, service quality and price in our markets.')
    item,=service.extract_competition_descriptions(doc,ticker='ZQXB',cik='1234567')
    assert 'competition_scope' not in item.competition_disclosures[0]
    item.competition_disclosures[0]['competition_scope']=deepcopy(SCOPE)
    item.summary=service._summary(item.competition_disclosures[0])
    assert service.bound_competition_description(item,ticker='ZQXB',cik='1234567') is None
