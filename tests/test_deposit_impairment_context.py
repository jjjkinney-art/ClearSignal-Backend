"""Unseen issuer/concept fixtures and adverse context with scalar/source tampering."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest
from app.providers import sec_deposit_impairment as parser
from app.providers.sec_inline_facts import parse_inline_observations
from app.services import deposit_impairment_context as service, thesis_disclosures as disclosures
from app.integrity.provenance import ClaimDocumentReference
from app.schemas import InvestmentThesis
from app.services.evidence_references import admit_evidence
from app.services.source_answer import apply_source_answer_gate
from test_segment_financial_context import document as existing_document, CIK
from test_financial_thesis_foundation import pair

QUOTE=('During the first quarter of 2025, the Company made deposits totaling $2,701,000 with a vendor in its '
       'Clinical Devices segment. On May 29, 2025, the vendor filed for protection in the U.S. Bankruptcy Court '
       'in the Northern District of Illinois. As recovery of the deposit is deemed unlikely, the Company '
       'recorded an impairment of the full deposit during the second quarter of 2025.')


def xml(concept='VendorAdvanceCharge',namespace='https://unseen.invalid/2025',quote=QUOTE):
    def fact(fid):
        return f'<ix:nonFraction id="{fid}" name="c:{concept}" contextRef="ctx" unitRef="usd" format="t:num-dot-decimal" scale="3" decimals="-3">2,701</ix:nonFraction>'
    def table(role,label,fid):
        extra='<tr><td>'+parser.ADJUSTMENTS+'</td></tr>' if role=='CASH FLOWS' else ''
        return ('<p>CONSOLIDATED STATEMENTS OF '+role+'</p><p>(In thousands)</p><table>'
            '<tr><td colspan="7">For the years ended December 31,</td></tr>'
            '<tr><td></td><td colspan="3">2025</td><td colspan="3">2024</td></tr>'+extra+
            '<tr><td>'+label+'</td><td>$</td><td>'+fact(fid)+'</td><td></td><td>$</td><td>-</td><td></td></tr></table>')
    return f'''<html xmlns="http://www.w3.org/1999/xhtml" xmlns:x="http://www.xbrl.org/2003/instance"
    xmlns:ix="http://www.xbrl.org/2013/inlineXBRL" xmlns:c="{namespace}" xmlns:iso="http://www.xbrl.org/2003/iso4217"
    xmlns:t="http://www.xbrl.org/inlineXBRL/transformation/2020-02-12"><body><ix:header><ix:resources>
    <x:context id="ctx"><x:entity><x:identifier scheme="http://www.sec.gov/CIK">{CIK}</x:identifier></x:entity>
    <x:period><x:startDate>2025-01-01</x:startDate><x:endDate>2025-12-31</x:endDate></x:period></x:context>
    <x:unit id="usd"><x:measure>iso:USD</x:measure></x:unit></ix:resources></ix:header>
    <p>Item 1. Business Products are sold directly to retailers and also through independent distributors.
    Item 1A. Risk Factors Supply disruption could affect operations. Item 1B. Unresolved Staff Comments</p>
    <p>ITEM 7. MANAGEMENT’S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND RESULTS OF OPERATIONS Results of operations.
    2025 COMPARED TO 2024 Results are discussed below. {quote} 2024 COMPARED TO 2023 Prior results are discussed.</p>
    <p>ITEM 7A. QUANTITATIVE AND QUALITATIVE DISCLOSURES ABOUT MARKET RISK Further disclosures follow.</p>
    {table('INCOME','Impairment of vendor deposit','expense')}
    {table('CASH FLOWS','Loss on impairment of vendor deposit','reconcile')}</body></html>'''


def document(source=None):
    source=source or xml()
    return replace(existing_document(source),published_at='2026-03-13',
                   deposit_impairment_proofs=parser.parse_impairment_tables(source,cik=CIK))


def evidence(source=None):
    return service.extract_deposit_impairment(document(source),ticker='ZQXB',cik=CIK)[0]


@pytest.mark.parametrize('concept,namespace',[
    ('VendorAdvanceCharge','https://unseen.invalid/2025'),
    ('DepositWriteDown','http://another.example/taxonomy/2025'),
    ('SupplierDepositImpairment','https://different.example/20251231'),
])
def test_unseen_concepts_need_visible_label_and_two_agreeing_presentations(concept,namespace):
    s=xml(concept,namespace);proof,=parser.parse_impairment_tables(s,cik=CIK)
    m=parser.reconstruct(proof,cik=CIK)
    assert m['amount_usd']==2701000 and m['scope']=='consolidated_expense'
    assert m['duplicate_presentations_not_added'] is True
    assert m['income_statement']['observation']['concept']==concept
    assert parse_inline_observations(s,cik=CIK,concepts=(concept,))==()
    v=service.bound_deposit_impairment(evidence(s),ticker='ZQXB',cik=CIK)
    assert v['quote']==QUOTE and v['impairment_context']['event']['segment_context']=='Clinical Devices'
    assert v['impairment_context']['event']['segment_measurement_established'] is False


@pytest.mark.parametrize('before,after',[
    ('2,701</ix:nonFraction>','2,702</ix:nonFraction>'),
    ('unitRef="usd"','unitRef="other"'),('scale="3"','scale="6"'),
    ('scale="3"','scale="3" sign="-"'),('iso:USD','iso:EUR'),
    ('2025-12-31','2024-12-31'),('2025-01-01','2025-10-01'),
    ('http://www.sec.gov/CIK','https://other.invalid/CIK'),
    ('Impairment of vendor deposit','Impairment of goodwill'),
    (parser.ADJUSTMENTS,'Unrelated cash activity:'),
    ('CONSOLIDATED STATEMENTS OF INCOME','Segment income schedule'),
    ('(In thousands)','(In millions)'),
    ('<x:identifier scheme','<x:segment/><x:identifier scheme'),
    ('<x:period>','<x:scenario/><x:period>'),
    ('decimals="-3"','decimals="-3" continuedAt="other"'),
    ('<ix:nonFraction id="expense"','<ix:nonFraction style="display:none" id="expense"'),
    ('https://unseen.invalid/2025','http://www.xbrl.org/2003/instance'),
    (CIK,'9999999'),
    ('<p>(In thousands)</p><table>','<p>(In thousands)</p><p>Unrelated note</p><table>'),
])
def test_wrong_numeric_scope_resource_statement_or_hidden_source_withheld(before,after):
    s=xml().replace(before,after)
    assert service.extract_deposit_impairment(document(s),ticker='ZQXB',cik=CIK)==[]


def test_conflicting_cash_flow_or_duplicate_ids_do_not_pass():
    s=xml().replace('id="reconcile" name=', 'id="expense" name=')
    assert parser.parse_impairment_tables(s,cik=CIK)==()
    s=xml().replace('>2,701</ix:nonFraction>', '>2,702</ix:nonFraction>',1)
    assert parser.parse_impairment_tables(s,cik=CIK)==()


@pytest.mark.parametrize('drop',['income','cash_flow'])
def test_single_presentation_is_insufficient(drop):
    import re
    s=xml()
    tables=list(re.finditer(r'<table>.*?</table>',s))
    target=tables[0 if drop=='income' else 1]
    s=s[:target.start()]+s[target.end():]
    assert parser.parse_impairment_tables(s,cik=CIK)==()


@pytest.mark.parametrize('changes',[
    {'document_type':'10-Q'},{'document_type':'20-F'},{'publisher':'Other'},
    {'published_at':'2099-01-01'},{'published_at':'2024-01-01'},
    {'source_tier':'secondary'},{'text_ready':False},{'extraction_method':'pdf'},
])
def test_document_eligibility(changes):
    assert service.extract_deposit_impairment(replace(document(),**changes),ticker='ZQXB',cik=CIK)==[]


@pytest.mark.parametrize('before,after',[
    ('$2,701,000','$2,700,000'),('full deposit','partial deposit'),
    ('deemed unlikely','certainly impossible'),('first quarter','fourth quarter'),
    ('May 29, 2025','February 30, 2025'),('May 29, 2025','May 29, 2024'),
    ('second quarter of 2025','second quarter of 2024'),
    ('the vendor filed','another vendor filed'),('the full deposit','another deposit'),
    ('2025 COMPARED TO 2024','2024 COMPARED TO 2023'),
    ('2024 COMPARED TO 2023','2025 COMPARED TO 2024'),
    ('2025 COMPARED TO 2024 Results','2025 COMPARED TO 2024 Another vendor was involved. Results'),
])
def test_event_amount_dates_antecedents_and_comparison_boundary_must_match(before,after):
    assert service.extract_deposit_impairment(document(xml().replace(before,after)),ticker='ZQXB',cik=CIK)==[]


@pytest.mark.parametrize('field',['amount','dimension','scale','scope','sign','currency','table_role','quote','offset','event_segment','uncertainty','row_ref','hash','summary','period','ticker','stale'])
def test_final_binding_reconstructs_scalar_event_and_references(field):
    item=deepcopy(evidence());v=item.impairment_disclosures[0]
    obs=v['measurement_proof']['observations'][0]
    if field=='amount':v['impairment_context']['measurement']['amount_usd']*=2
    elif field=='dimension':obs['dimensions']=[{'member':'Other'}]
    elif field=='scale':obs['scale']=6
    elif field=='scope':obs['scope']='segment'
    elif field=='sign':obs['sign']='-'
    elif field=='currency':obs['unit']='EUR'
    elif field=='table_role':v['measurement_proof']['tables'][0]['paragraphs']=['Other statement']
    elif field=='quote':v['quote']='Buy now.'
    elif field=='offset':v['start_offset']=True
    elif field=='event_segment':v['impairment_context']['event']['segment_context']='Other'
    elif field=='uncertainty':v['impairment_context']['event']['recovery_assessment']='impossible'
    elif field=='row_ref':v['measurement_refs'][0]['quote']='Other row'
    elif field=='hash':v['document_ref']['content_hash']='invalid'
    elif field=='summary':item.summary='Buy now.'
    elif field=='period':item.reporting_period_end='2024-12-31'
    elif field=='ticker':v['ticker']='OTHER'
    elif field=='stale':item.freshness_status='stale'
    assert service.bound_deposit_impairment(item,ticker='ZQXB',cik=CIK) is None


def test_full_event_reference_has_separate_scoped_cap():
    v=evidence().impairment_disclosures[0]
    assert len(QUOTE)>300 and ClaimDocumentReference(**v['document_ref']).quote==QUOTE
    with pytest.raises(ValueError,match='300'):
        ClaimDocumentReference(**{**v['document_ref'],'section':'Item 7. Management discussion and analysis'})


def test_ordinary_retrieval_final_answer_and_incomplete_coverage(monkeypatch):
    doc=document();monkeypatch.setattr(disclosures.sec_provider,'_load_ticker_cik_map',lambda:{'ZQXB':CIK})
    monkeypatch.setattr(disclosures.sec_provider,'fetch_recent_filings',lambda *a,**kw:[SimpleNamespace(url=doc.final_url,timestamp=doc.published_at,document_type='10-K')])
    monkeypatch.setattr(disclosures,'fetch_public_document',lambda *a,**kw:doc)
    items=disclosures.fetch_thesis_disclosures('ZQXB',question='What is the investment thesis for ZQXB?')
    assert len(items[-1].impairment_disclosures)==1
    admitted,refs,_=admit_evidence(pair(ticker='ZQXB',cik=CIK)+items,evaluated_at='2026-10-23')
    thesis=InvestmentThesis(ticker='ZQXB',company_name='Invented issuer')
    result=apply_source_answer_gate(thesis,'What is the investment thesis for ZQXB? Cite material claims.',admitted,references=refs)
    rows=[c for c in result['claims'] if c['claim_kind']=='issuer_deposit_impairment_context']
    assert len(rows)==1 and QUOTE in thesis.direct_answer
    assert result['status']=='partial' and result['business_context_coverage']['complete_business_model'] is False
