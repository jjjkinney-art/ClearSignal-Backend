"""Bound named-segment contract and recognition policies, not realized economics."""
from datetime import date
import hashlib
import json
import re

from ..integrity.provenance import ClaimDocumentReference
from ..schemas import RetrievedEvidence

SECTION = 'Financial statement notes - Segment revenue policies'
KIND = 'issuer_segment_revenue_policy'
LABEL = r'[A-Z][A-Za-z /&-]{1,79}?'
HEADING = re.compile(r'\(\s*(?P<n>[1-9][0-9]?)\s*\)\s+(?P<title>[A-Z][A-Z /&-]{1,79}):')
NOTES = 'NOTES TO CONSOLIDATED FINANCIAL STATEMENTS'
POLICIES = 'A. SUMMARY OF SIGNIFICANT ACCOUNTING POLICIES:'
CONTRACT = re.compile(
    rf"The Company's contracts in the (?P<segment>{LABEL}) segment are primarily with "
    r'(?P<customers>[A-Za-z .,()&-]{10,200})\. As a consequence, this segment\'s business '
    r'essentially depends on the product needs and governmental funding of the (?P<alias>[A-Z]{2,8})\. '
    rf'Substantially all of the work performed by the (?P=segment) segment directly or indirectly '
    r'for the (?P=alias) is performed on a fixed-price basis\. '
    r'Under fixed-price contracts, the price paid to the contractor is awarded based on competition '
    r'or negotiation at the outset of the contract and therefore, with the exception of limited '
    r'escalation provisions on specific materials, is generally not subject to any adjustments '
    r'reflecting the actual costs incurred by the contractor\.')
RECOGNITION = re.compile(
    rf'For the (?P<shipment_a>{LABEL}) and (?P<shipment_b>{LABEL}) segments, revenue is generally '
    r'recognized as the completed, ordered product is shipped to the customer from the Company’s warehouses\. '
    r'For the situations in which revenue should be recognized when product is received by the customer, '
    r'the Company adjusts revenue accordingly\. '
    rf'For the (?P<acceptance>{LABEL}) segment, revenue is primarily recognized when the customer has '
    r'legal title and formally documents that it has accepted the products\. '
    r'There are also certain termination clauses in (?P=acceptance) segment contracts that may give rise '
    r'to an over-time pattern of recognition of revenue in the absence of alternative use of the product\.')


def source_window(text):
    if not isinstance(text, str) or len(text) > 360_000:
        return None
    if text.count(NOTES) != 1:
        return None
    start = text.index(NOTES)
    if not text[start + len(NOTES):].lstrip(' \ufeff').startswith(POLICIES):
        return None
    headings = list(HEADING.finditer(text, start))
    revenue = [i for i,h in enumerate(headings) if h['title'] == 'REVENUES']
    if len(revenue) != 1 or revenue[0] + 1 >= len(headings):
        return None
    i = revenue[0]
    if int(headings[i+1]['n']) != int(headings[i]['n']) + 1:
        return None
    end = headings[i+1].end()
    if end - start > 50_000:
        return None
    window = text[start:end]
    return {'text': window, 'start_offset': start,
            'text_sha256': hashlib.sha256(window.encode()).hexdigest()}


def reconstruct(proof):
    if not isinstance(proof, dict) or set(proof) != {'text','start_offset','text_sha256'}:
        return []
    text, origin = proof['text'], proof['start_offset']
    if (not isinstance(text,str) or type(origin) is not int or origin < 0
            or origin + len(text) > 360_000):
        return []
    window = source_window(text)
    if not window or window['start_offset'] != 0 or window['text'] != text or window['text_sha256'] != proof['text_sha256']:
        return []
    headings = list(HEADING.finditer(text))
    index = next(i for i,h in enumerate(headings) if h['title'] == 'REVENUES')
    a,b = headings[index].end(),headings[index+1].start()
    starts = list(re.finditer(r"The Company's contracts in the ",text[a:b]))
    recognitions = list(re.finditer(r'For the '+LABEL+r' and '+LABEL+r' segments, revenue ',text[a:b]))
    timings = list(re.finditer(r'The timing of revenue recognition,',text[a:b]))
    if len(starts) != 1 or len(recognitions) != 1 or len(timings) != 1:
        return []
    x,y,z = (a + matches[0].start() for matches in (starts,recognitions,timings))
    if not x < y < z:
        return []
    candidates = []
    for role,left,right,grammar in [('contract_terms',x,y,CONTRACT),('recognition_timing',y,z,RECOGNITION)]:
        quote = text[left:right].strip(' \ufeff')
        match = grammar.fullmatch(quote)
        if not match or len(quote) > 900:
            continue
        if role == 'contract_terms':
            alias = match['alias']
            if len(re.findall(r'\('+re.escape(alias)+r'\)', match['customers'])) != 1:
                continue
            context = {'role':role,'segments':[match['segment']],
                'customers':match['customers'],'source_customer_alias':alias,
                'price_terms':'fixed_price_with_limited_material_escalation_exception'}
        else:
            segments = [match[k] for k in ('shipment_a','shipment_b','acceptance')]
            if len(set(segments)) != 3:
                continue
            context = {'role':role,'segments':segments,'shipment_segments':segments[:2],
                'acceptance_segment':segments[2], 'receipt_adjustment_preserved':True,
                'over_time_termination_exception_preserved':True}
        context.update(scope='named_segments',attribution='issuer_accounting_policy',
                       realized_performance_established=False, future_revenue_established=False)
        candidates.append({'quote':quote,'start_offset':origin+left,'end_offset':origin+left+len(quote),
                           'policy_context':context})
    return candidates


def _summary(value):
    context = value['policy_context']
    label = 'contract terms' if context['role']=='contract_terms' else 'revenue-recognition policy'
    return (f"{value['ticker']} reported named-segment {label} in the 10-K filed "
        f"{value['document_ref']['published_at']}: “{value['quote']}” "
        'This is issuer-attributed policy for the named segments, with the stated exceptions. '
        'It does not establish realized revenue or cash collection, general cost pass-through, competitive '
        'advantage, future results or a complete issuer business model.')


def extract_segment_revenue_policies(document, *, ticker, cik):
    from .thesis_disclosures import _business_issuer_url
    if (document.document_type != '10-K' or document.publisher != 'SEC EDGAR'
            or document.source_type != 'regulatory_filing' or document.source_tier != 'primary'
            or document.extraction_method != 'html' or not document.text_ready
            or not _business_issuer_url(document.final_url,cik)):
        return []
    proof = source_window(document.text)
    if not proof:
        return []
    proof['start_offset'] += document.text_window_start
    output=[]
    for candidate in reconstruct(proof):
        try:
            ref=ClaimDocumentReference(reference_id=f'document:{document.content_hash}:segment_policy:{candidate["start_offset"]}',
                title=document.title or f'{ticker} 10-K',provider='SEC EDGAR',url=document.final_url,
                published_at=document.published_at,section=SECTION,content_hash=document.content_hash,
                quote=candidate['quote']).to_dict()
            value={**candidate,'claim_kind':KIND,'ticker':ticker,'document_ref':ref,'policy_source_proof':proof}
            item=RetrievedEvidence(title=f'{ticker} segment {candidate["policy_context"]["role"]}',source='SEC EDGAR',
                summary=_summary(value),timestamp=document.published_at,url=document.final_url,
                relevance_score=0.96,source_type='regulatory_filing',source_tier='primary',claim_type='reported_fact',
                document_type='10-K',filed_at=document.published_at,section=SECTION,extraction_method='html',
                revenue_policy_disclosures=[value])
            if bound_segment_revenue_policy(item,ticker=ticker,cik=cik):
                output.append(item)
        except (TypeError,ValueError):
            continue
    return output


def bound_segment_revenue_policy(item, *, ticker, cik):
    from .thesis_disclosures import _business_issuer_url
    values=getattr(item,'revenue_policy_disclosures',[])
    if not isinstance(values,list) or len(values)!=1 or not isinstance(values[0],dict):
        return None
    value=values[0]
    try:
        rebuilt=reconstruct(value['policy_source_proof'])
        selected={k:value[k] for k in ('quote','start_offset','end_offset','policy_context')}
        if not any(json.dumps(c,sort_keys=True,allow_nan=False)==json.dumps(selected,sort_keys=True,allow_nan=False) for c in rebuilt):
            return None
        ref=ClaimDocumentReference(**value['document_ref']).to_dict()
        if (value['claim_kind']!=KIND or value['ticker']!=ticker
                or ref['quote']!=value['quote'] or ref['provider']!='SEC EDGAR'
                or not re.fullmatch(r'[0-9a-f]{64}',ref.get('content_hash',''))
                or ref['url']!=item.url or not _business_issuer_url(item.url,cik)
                or ref['published_at']!=item.timestamp or item.filed_at!=item.timestamp
                or ref.get('section')!=SECTION or item.section!=SECTION
                or ref['reference_id']!=f'document:{ref["content_hash"]}:segment_policy:{value["start_offset"]}'
                or date.fromisoformat(item.timestamp)>date.today()
                or item.source!='SEC EDGAR' or item.source_type!='regulatory_filing'
                or item.source_tier!='primary' or item.claim_type!='reported_fact'
                or item.document_type!='10-K' or item.extraction_method!='html'
                or item.reporting_period_start is not None or item.reporting_period_end is not None
                or item.availability_status!='available'
                or item.freshness_status in {'unavailable','conflicting','superseded','stale'}
                or item.summary!=_summary(value)):
            return None
        return value
    except (KeyError,ValueError,TypeError,AttributeError,OverflowError,StopIteration):
        return None
