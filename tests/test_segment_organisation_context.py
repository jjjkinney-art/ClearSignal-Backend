"""Named synthetic organisations, scope/date boundaries and final proof tampering."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
import hashlib

import pytest
from app.integrity.provenance import ClaimDocumentReference
from app.schemas import InvestmentThesis
from app.services import segment_organisation_context as org, thesis_disclosures as disclosures
from app.services.evidence_references import admit_evidence
from app.services.source_answer import apply_source_answer_gate
from test_thesis_disclosures import document
from test_financial_thesis_foundation import pair

QUOTE = ('Northstar Devices Corporation ("Northstar") was acquired on February 24, 2001, '
         'and manufactures 40mm optical assemblies and mechanical instruments for '
         'the National Health Agency (NHA) and NHA prime contractors.')
CHANNELS = 'Products are sold directly to retailers and also through independent distributors.'


def fixture(quote=QUOTE, extra='', label='Clinical Devices'):
    return document('Item 1. Business '+CHANNELS+' 1. Consumer Segment Household products are sold to retailers. '
        +'2. '+label+' Segment The segment discusses the following organisations. '+quote+' '+extra
        +' 3. Water Systems Segment Filtration products are sold through distributors. '
        +'Item 1A. Risk Factors Supply disruption could affect operations. Item 1B. Unresolved Staff Comments')


def evidence(doc=None):
    return org.extract_organisation_activities(doc or fixture(),ticker='AAPL',cik='320193')[0]


@pytest.mark.parametrize('name,alias',[('Northstar Devices Corporation','Northstar'),('Morrow Instruments LLC','Morrow'),('Cedar Optics Limited','Cedar'),('Atlas Engineering Inc.','Atlas')])
@pytest.mark.parametrize('label',['Clinical Devices','Water/Filtration','Industrial & Consumer'])
def test_unseen_legal_names_segments_and_literal_quantities(name,alias,label):
    quote=QUOTE.replace('Northstar Devices Corporation',name).replace('"Northstar"','"'+alias+'"')
    doc=fixture(quote,label=label);item=evidence(doc)
    v=org.bound_organisation_activity(item,ticker='AAPL',cik='320193')
    assert v and doc.text[v['start_offset']:v['end_offset']]==quote
    c=v['organisation_context']
    assert c['organisation_name']==name and c['source_alias']==alias
    assert c['scope']=={'kind':'organisation_in_segment_discussion','segment_label':label}
    assert c['reported_acquisition_date']=='2001-02-24'
    assert c['customer_acronym_expansions']=={'NHA':'National Health Agency'}
    assert c['issuer_ownership']==c['current_status']==c['acquirer']=='not_established'
    assert '40mm' in c['products'] and c['revenue_inference_performed'] is False
    assert 'Current operations and issuer ownership are not established' in item.summary


@pytest.mark.parametrize('before,after',[
 ('Northstar Devices Corporation ("Northstar")','It'),
 ('Northstar Devices Corporation ("Northstar")','Northstar'),
 ('"Northstar"','"It"'),('manufactures','will manufacture'),
 ('manufactures','does not manufacture'),('40mm','20,000 square feet of'),
 ('40mm','$40 million of'),('40mm','40% of'),('40mm','2027 delivery of'),
 ('40mm','40mm reliable'),('40mm','40mm innovative'),
 ('40mm optical','LED optical'),('(NHA) and NHA','and NHA'),
 ('February 24, 2001','February 31, 2001'),('February 24, 2001','February 24, 2099'),
 ('and NHA prime contractors.','and competitors, which will grow profits.'),
])
def test_unsupported_activity_never_admitted(before,after):
    assert org.extract_organisation_activities(fixture(QUOTE.replace(before,after)),ticker='AAPL',cik='320193')==[]


@pytest.mark.parametrize('extra',[
 'Northstar was divested in 2023.', 'Northstar sold certain assets in 2025.',
 'The sale of Northstar assets was completed in 2025.',
 'The business was formerly owned by Northstar.',
 'Northstar was renamed in 2024.',
 'Other Devices LLC ("Northstar") manufactures unrelated parts for retail customers.',
])
def test_named_disposition_or_ambiguous_alias_withholds(extra):
    assert org.extract_organisation_activities(fixture(extra=extra),ticker='AAPL',cik='320193')==[]


def test_unrelated_disposal_or_other_former_asset_owner_does_not_suppress():
    for extra in ['Other Devices LLC was divested in 2023.',
        'West Division, a division of Northstar, holds assets formerly owned by Other Devices LLC.']:
        assert evidence(fixture(extra=extra))


@pytest.mark.parametrize('change',['label','alias','ownership','current','acquired','bool','offset','heading','end','quote','hash','summary','proof_text','proof_origin','proof_hash','ref','stale','period','ticker','published'])
def test_final_binding_reconstructs_and_rejects_tampering(change):
    item=deepcopy(evidence());v=item.organisation_disclosures[0];c=v['organisation_context']
    if change=='label':c['scope']['segment_label']='Other'
    elif change=='alias':c['source_alias']='Other'
    elif change=='ownership':c['issuer_ownership']='wholly_owned'
    elif change=='current':c['current_status']='current'
    elif change=='acquired':c['reported_acquisition_date']='2025-01-01'
    elif change=='bool':c['revenue_inference_performed']=0
    elif change=='offset':v['start_offset']=True
    elif change=='heading':v['heading_quote']='1. Other Segment'
    elif change=='end':v['segment_end_offset']+=1
    elif change=='quote':v['quote']='Buy now.'
    elif change=='hash':v['document_ref']['content_hash']='invalid'
    elif change=='summary':item.summary='Buy now.'
    elif change=='proof_text':v['business_source_proof']['text']+='malformed'
    elif change=='proof_origin':v['business_source_proof']['start_offset']=True
    elif change=='proof_hash':v['business_source_proof']['text_sha256']='0'*64
    elif change=='ref':v['document_ref']['quote']='Buy now.'
    elif change=='stale':item.freshness_status='stale'
    elif change=='period':item.reporting_period_end='2024-12-31'
    elif change=='ticker':v['ticker']='OTHER'
    elif change=='published':item.timestamp='2099-01-01'
    assert org.bound_organisation_activity(item,ticker='AAPL',cik='320193') is None


@pytest.mark.parametrize('before,after',[
 ('2. Clinical Devices','4. Clinical Devices'),('3. Water Systems','2. Water Systems'),
 ('2. Clinical Devices Segment','2. Clinical Devices Division'),
 ('Item 1A. Risk Factors','Unbounded Risks'),
])
def test_missing_duplicate_or_malformed_boundaries(before,after):
    d=fixture();assert org.extract_organisation_activities(replace(d,text=d.text.replace(before,after)),ticker='AAPL',cik='320193')==[]


@pytest.mark.parametrize('changes',[
 {'document_type':'20-F'},{'document_type':'10-Q'},{'publisher':'Other'},
 {'source_tier':'secondary'},{'extraction_method':'pdf'},{'text_ready':False},
 {'published_at':'2099-01-01'},{'published_at':'invalid'},
 {'final_url':'https://www.sec.gov/Archives/edgar/data/1/other.htm'},
])
def test_document_gates(changes):
    assert org.extract_organisation_activities(replace(fixture(),**changes),ticker='AAPL',cik='320193')==[]


def test_corrupted_complete_business_proof_cannot_keep_old_candidate():
    item=deepcopy(evidence());v=item.organisation_disclosures[0];p=v['business_source_proof']
    p['text']=p['text'].replace('3. Water Systems','Northstar was divested in 2023. 3. Water Systems')
    p['text_sha256']=hashlib.sha256(p['text'].encode()).hexdigest()
    assert org.bound_organisation_activity(item,ticker='AAPL',cik='320193') is None


def test_reference_limit_is_scoped():
    q=QUOTE.replace('optical assemblies','optical assemblies and mechanical and electrical sensor instruments '*3)
    v=evidence(fixture(q)).organisation_disclosures[0]
    assert len(q)>300 and ClaimDocumentReference(**v['document_ref']).quote==q
    with pytest.raises(ValueError,match='300'):
        ClaimDocumentReference(**{**v['document_ref'],'section':'Item 1. Business'})


def test_ordinary_ingestion_and_answer_do_not_fill_issuer_facets(monkeypatch):
    doc=fixture()
    monkeypatch.setattr(disclosures.sec_provider,'_load_ticker_cik_map',lambda:{'AAPL':'320193'})
    monkeypatch.setattr(disclosures.sec_provider,'fetch_recent_filings',lambda *a,**kw:[SimpleNamespace(url=doc.final_url,timestamp=doc.published_at,document_type='10-K')])
    monkeypatch.setattr(disclosures,'fetch_public_document',lambda *a,**kw:doc)
    items=disclosures.fetch_thesis_disclosures('AAPL',question='What is the investment thesis for AAPL?')
    assert len(items[-1].organisation_disclosures)==1
    admitted,refs,_=admit_evidence(pair()+items,evaluated_at='2026-10-22')
    thesis=InvestmentThesis(ticker='AAPL',company_name='Invented issuer')
    result=apply_source_answer_gate(thesis,'What is the investment thesis for AAPL? Cite material claims.',admitted,references=refs)
    rows=[c for c in result['claims'] if c['claim_kind']=='issuer_organisation_activity_context']
    assert len(rows)==1 and rows[0]['organisation_context']['scope']['segment_label']=='Clinical Devices'
    assert QUOTE in thesis.direct_answer and f"[{rows[0]['reference_id']}]" in thesis.direct_answer
    assert result['status']=='partial' and 'business model completeness' in result['unanswered_parts']
    coverage=result['business_context_coverage']
    assert coverage['complete_business_model'] is False
    assert next(f for f in coverage['facets'] if f['facet']=='activities')['status']=='not_verified'


def test_activity_after_non_segment_numbered_heading_is_not_in_last_segment():
    doc=fixture('No activity is identified.')
    doc=replace(doc,text=doc.text.replace('Item 1A. Risk Factors', '4. General Information '+QUOTE+' Item 1A. Risk Factors'))
    assert org.extract_organisation_activities(doc,ticker='AAPL',cik='320193')==[]


def test_acquisition_is_optional_and_does_not_invent_date():
    q=QUOTE.replace('was acquired on February 24, 2001, and ','')
    v=evidence(fixture(q)).organisation_disclosures[0]
    assert v['organisation_context']['reported_acquisition_date'] is None
