"""Dated vendor-deposit impairment, retaining management's recovery uncertainty."""
from datetime import date, datetime
import json
import re

from ..integrity.provenance import ClaimDocumentReference
from ..providers.sec_deposit_impairment import reconstruct
from ..schemas import RetrievedEvidence
from .sec_risk_sections import risk_sentence_spans
from .segment_sales_explanations import source_window, YEARS, MONEY

SECTION = 'Item 7. Management discussion - Deposit impairment'
QUARTERS = {'first':1,'second':2,'third':3,'fourth':4}
EVENT = re.compile(
    rf'During the (?P<deposit_quarter>first|second|third|fourth) quarter of (?P<year>20\d{{2}}), '
    rf'the Company made deposits totaling \$(?P<amount>{MONEY}) with a vendor in its '
    r'(?P<segment>[A-Z][A-Za-z /&-]{1,79}) segment\. '
    r'On (?P<bankruptcy_date>[A-Z][a-z]+ [0-9]{1,2}, 20[0-9]{2}), the vendor filed for protection '
    r'in the U\.S\. Bankruptcy Court in the (?P<court>[A-Z][A-Za-z -]{3,100})\. '
    r'As recovery of the deposit is deemed unlikely, the Company recorded an impairment of the full deposit '
    r'during the (?P<recognition_quarter>first|second|third|fourth) quarter of (?P<recognition_year>20\d{2})\.')


def narrative(measurement, source):
    try:
        if (not isinstance(source,dict) or set(source)!={'text','start_offset','sha256'}
                or type(source['start_offset']) is not int or not 0<=source['start_offset']<=360_000
                or source['start_offset']+len(source['text'])>360_000):
            return None
        window=source_window(source['text'])
        if (not window or window['start_offset']!=0 or window['text']!=source['text']
                or window['sha256']!=source['sha256']):
            return None
        year=int(measurement['end'][:4]);text=source['text'];headings=list(YEARS.finditer(text))
        if (len(headings)<2 or headings[0].groups()!=(str(year),str(year-1))
                or headings[1].groups()!=(str(year-1),str(year-2))):
            return None
        a,b=headings[0].end(),headings[1].start()
        # One vendor introduction in the eligible comparison block. A second
        # vendor cannot borrow the first vendor's pronouns or deposit amount.
        if len(re.findall(r'\b(?:a|another|second|other) vendor\b',text[a:b],re.I))!=1:
            return None
        spans=list(risk_sentence_spans(text[a:b]));found=[]
        for i in range(len(spans)-2):
            left,right=a+spans[i][0],a+spans[i+2][1]
            while left<right and text[left] in '\ufeff \t\n':left+=1
            quote=text[left:right];m=EVENT.fullmatch(quote)
            if not m or len(quote)>900:
                continue
            when=datetime.strptime(m['bankruptcy_date'],'%B %d, %Y').date()
            dq,rq=QUARTERS[m['deposit_quarter']],QUARTERS[m['recognition_quarter']]
            if (m['year']!=str(year) or m['recognition_year']!=str(year) or when.year!=year
                    or not dq <= (when.month-1)//3+1 <= rq
                    or int(m['amount'].replace(',',''))!=measurement['amount_usd']
                    or not date.fromisoformat(measurement['start'])<=when<=date.fromisoformat(measurement['end'])):
                continue
            found.append({'quote':quote,'start_offset':source['start_offset']+left,
                'end_offset':source['start_offset']+right,'segment_context':m['segment'],
                'segment_measurement_established':False,'vendor_identity':'not_named_in_passage',
                'deposit_quarter':dq,'recognition_quarter':rq,'event_year':year,
                'bankruptcy_filing_date':when.isoformat(),'court':m['court'],
                'recognition_extent':'full_deposit','recovery_assessment':'management_deems_unlikely',
                'attribution':'management','comparison_heading':headings[0].group()})
        return found[0] if len(found)==1 else None
    except (KeyError,TypeError,ValueError,AttributeError,ArithmeticError):
        return None


def _summary(v):
    m=v['impairment_context']['measurement']
    return (f"{v['ticker']} reported a consolidated vendor-deposit impairment expense of ${m['amount_usd']:,} "
        f"for {m['start']} to {m['end']}, in the 10-K filed {v['document_ref']['published_at']}. "
        f"Management described the event: “{v['quote']}” "
        'The income-statement expense and cash-flow reconciliation repeat one impairment; they are not added. '
        'The reconciliation does not establish a new cash payment. The segment name is narrative context, '
        'not a dimensionally reported segment expense. Recovery remains management’s assessment; recurrence, '
        'future recovery, materiality ranking and a complete operating-profit bridge are not established.')


def _fields(proof, source, ref, *, cik):
    measurement=reconstruct(proof,cik=cik)
    if not measurement:
        return None
    event=narrative(measurement,source)
    if not event:
        return None
    refs=[ClaimDocumentReference(**{**ref,'reference_id':ref['reference_id']+':'+role,
        'section':'Annual consolidated statement - Deposit impairment',
        'quote':measurement[role]['row_text']}).to_dict()
        for role in ('income_statement','cash_flow_reconciliation')]
    return {**event,'impairment_context':{'measurement':measurement,'event':event},'measurement_refs':refs}


def extract_deposit_impairment(document, *, ticker, cik):
    from .thesis_disclosures import _business_issuer_url
    if (document.document_type!='10-K' or document.publisher!='SEC EDGAR'
            or document.source_type!='regulatory_filing' or document.source_tier!='primary'
            or document.extraction_method!='html' or not document.text_ready
            or not _business_issuer_url(document.final_url,cik)):
        return []
    proofs=getattr(document,'deposit_impairment_proofs',())
    if len(proofs)!=1:
        return []
    proof=proofs[0];measurement=reconstruct(proof,cik=cik);source=source_window(document.text)
    event=narrative(measurement,source) if measurement else None
    if not event:
        return []
    try:
        if not date.fromisoformat(measurement['end'])<=date.fromisoformat(document.published_at)<=date.today():
            return []
        ref=ClaimDocumentReference(reference_id=f'document:{document.content_hash}:deposit_impairment:{event["start_offset"]}',
            title=document.title or f'{ticker} 10-K',provider='SEC EDGAR',url=document.final_url,
            published_at=document.published_at,section=SECTION,content_hash=document.content_hash,quote=event['quote']).to_dict()
        fields=_fields(proof,source,ref,cik=cik)
        if not fields:
            return []
        value={**fields,'claim_kind':'issuer_deposit_impairment_context','ticker':ticker,
            'document_ref':ref,'measurement_proof':proof,'narrative_source':source}
        item=RetrievedEvidence(title=f'{ticker} reported deposit impairment',source='SEC EDGAR',summary=_summary(value),
            timestamp=document.published_at,url=document.final_url,relevance_score=0.96,source_type='regulatory_filing',
            source_tier='primary',claim_type='reported_fact',document_type='10-K',filed_at=document.published_at,
            section=SECTION,extraction_method='html',reporting_period_start=measurement['start'],
            reporting_period_end=measurement['end'],impairment_disclosures=[value])
        return [item] if bound_deposit_impairment(item,ticker=ticker,cik=cik) else []
    except (KeyError,TypeError,ValueError,AttributeError,ArithmeticError):
        return []


def bound_deposit_impairment(item, *, ticker, cik):
    from .thesis_disclosures import _business_issuer_url
    values=getattr(item,'impairment_disclosures',[])
    if not isinstance(values,list) or len(values)!=1 or not isinstance(values[0],dict):
        return None
    v=values[0]
    try:
        ref=ClaimDocumentReference(**v['document_ref']).to_dict()
        fields=_fields(v['measurement_proof'],v['narrative_source'],ref,cik=cik)
        if not fields or json.dumps({k:v.get(k) for k in fields},sort_keys=True,allow_nan=False)!=json.dumps(fields,sort_keys=True,allow_nan=False):
            return None
        m=fields['impairment_context']['measurement']
        if (v['ticker']!=ticker or v['claim_kind']!='issuer_deposit_impairment_context'
                or ref['provider']!='SEC EDGAR' or ref['url']!=item.url or ref['quote']!=v['quote']
                or not _business_issuer_url(item.url,cik) or not re.fullmatch(r'[0-9a-f]{64}',ref.get('content_hash',''))
                or ref.get('section')!=SECTION or item.section!=SECTION
                or ref['reference_id']!=f'document:{ref["content_hash"]}:deposit_impairment:{v["start_offset"]}'
                or ref['published_at']!=item.timestamp or item.filed_at!=item.timestamp
                or not date.fromisoformat(m['end'])<=date.fromisoformat(item.timestamp)<=date.today()
                or item.reporting_period_start!=m['start'] or item.reporting_period_end!=m['end']
                or item.source!='SEC EDGAR' or item.source_type!='regulatory_filing' or item.source_tier!='primary'
                or item.claim_type!='reported_fact' or item.document_type!='10-K' or item.extraction_method!='html'
                or item.availability_status!='available' or item.freshness_status in {'stale','unavailable','conflicting','superseded'}
                or item.summary!=_summary(v)):
            return None
        return v
    except (KeyError,TypeError,ValueError,AttributeError,ArithmeticError):
        return None
