"""Annual cash-use explanations matched to same-document consolidated facts."""
from datetime import date
import json
import re

from ..integrity.provenance import ClaimDocumentReference
from ..providers.sec_inline_facts import validated_observation
from ..schemas import RetrievedEvidence
from .segment_sales_explanations import source_window, YEARS, MONEY

CONCEPT = 'NetCashProvidedByUsedInOperatingActivities'
SECTION = 'Item 7. Management discussion - Annual operating cash explanation'
KIND = 'issuer_annual_cash_flow_context'
FIELDS = frozenset('concept_namespace concept fact_id context_id unit_id literal format_namespace format sign scale entity_scheme entity_identifier start end unit_namespace unit scope'.split())
LIQUIDITY = re.compile(r'LIQUIDITY AND CAPITAL RESOURCES\s+(20\d{2}) COMPARED TO (20\d{2})')
OPENING = re.compile(
    rf'Cash used in operating activities was \$(?P<current>{MONEY}) during (?P<year>20\d{{2}}) '
    rf'as compared to \$(?P<prior>{MONEY}) during (?P<previous>20\d{{2}})\. '
    r'The principal factors behind the (?P<movement>decrease|increase) in cash used can be found '
    r'in the changes in the components of working capital within the Consolidated Statements of Cash Flows\. ')
DETAILS = re.compile(
    r'Of particular note during (?P<year>20\d{2}) was net earnings of \$[^.!?]{10,550}\. '
    r'The combination of these factors was [^.!?]{20,350}\. '
    r'Of particular note during (?P<previous>20\d{2}) was net earnings of \$[^.!?]{10,550}\. '
    r'This was augmented by [^.!?]{20,350}\. '
    r'The combination of these factors was [^.!?]{20,350}\.')


def reconstruct(source, observations, *, cik):
    try:
        if (not isinstance(source,dict) or set(source)!={'text','start_offset','sha256'}
                or type(source['start_offset']) is not int or source['start_offset']<0
                or source['start_offset']+len(source['text'])>360_000):
            return None
        window=source_window(source['text'])
        if not window or window['start_offset']!=0 or window['text']!=source['text'] or window['sha256']!=source['sha256']:
            return None
        text=source['text'];heads=list(YEARS.finditer(text));liquidity=list(LIQUIDITY.finditer(text))
        if not heads or not liquidity or len(liquidity)!=1:
            return None
        year,previous=map(int,liquidity[0].groups())
        if year!=previous+1 or heads[0].groups()!=(str(year),str(previous)):
            return None
        closing=next((h for h in heads if h.start()>liquidity[0].end()),None)
        if not closing or closing.groups()!=(str(previous),str(previous-1)):
            return None
        left=liquidity[0].end()
        starts=list(re.finditer('Cash used in operating activities was ',text[left:closing.start()]))
        if len(starts)!=1:
            return None
        left+=starts[0].start()
        stops=list(re.finditer(r'Net cash (?:used in|provided by) investing activities',text[left:closing.start()]))
        if len(stops)!=1:
            return None
        quote=text[left:left+stops[0].start()].strip(' \ufeff')
        if len(quote)>1600:
            return None
        opening=OPENING.match(quote)
        details=DETAILS.fullmatch(quote[opening.end():]) if opening else None
        if (not opening or not details or opening['year']!=str(year) or opening['previous']!=str(previous)
                or details['year']!=str(year) or details['previous']!=str(previous)
                or re.search(r'\b(?:will|expect\w*|forecast\w*|future|instructions?|ignore)\b',quote,re.I)):
            return None
        if not isinstance(observations,(list,tuple)) or len(observations)!=2:
            return None
        amounts=[]
        for obs,y in zip(observations,(year,previous)):
            if not isinstance(obs,dict) or set(obs)!=FIELDS:
                return None
            amount=validated_observation(obs,cik=cik,concepts=(CONCEPT,))
            if (amount is None or amount>=0 or obs['start']!=f'{y}-01-01' or obs['end']!=f'{y}-12-31'):
                return None
            amounts.append(amount)
        if (len({o['fact_id'] for o in observations})!=2
                or len({o['context_id'] for o in observations})!=2
                or len({o['concept_namespace'] for o in observations})!=1):
            return None
        current,prior=amounts
        if (int(opening['current'].replace(',',''))!=-current or int(opening['prior'].replace(',',''))!=-prior
                or current==prior or opening['movement']!=('decrease' if abs(current)<abs(prior) else 'increase')):
            return None
        return {'quote':quote,'start_offset':source['start_offset']+left,
            'end_offset':source['start_offset']+left+len(quote),
            'cash_flow_context':{'scope':'consolidated','currency':'USD',
                'current_start':f'{year}-01-01','current_end':f'{year}-12-31','current_amount':current,
                'prior_start':f'{previous}-01-01','prior_end':f'{previous}-12-31','prior_amount':prior,
                'movement_in_cash_used':opening['movement'],'attribution':'management',
                'independent_causality_established':False,'interim_bridge_established':False}}
    except (KeyError,TypeError,ValueError,AttributeError,OverflowError):
        return None


def _summary(value):
    c=value['cash_flow_context']
    return (f"{value['ticker']} reported annual consolidated operating cash flow of -${abs(c['current_amount']):,} "
        f"for {c['current_start']} to {c['current_end']}, versus -${abs(c['prior_amount']):,} for "
        f"{c['prior_start']} to {c['prior_end']}, in the 10-K filed {value['document_ref']['published_at']}. "
        f"Management explained: “{value['quote']}” Both annual amounts are cash outflows. "
        'This is management’s annual explanation, not independently established causality, sustainable cash generation '
        'or an explanation of later interim results. Noncash adjustments are not new cash payments; '
        'investing and financing flows are separate. This annual explanation does not verify any later interim cash-flow drivers.')


def extract_annual_cash_flow_context(document, *, ticker, cik):
    from .thesis_disclosures import _business_issuer_url
    if (document.document_type!='10-K' or document.publisher!='SEC EDGAR'
            or document.source_type!='regulatory_filing' or document.source_tier!='primary'
            or document.extraction_method!='html' or not document.text_ready
            or not _business_issuer_url(document.final_url,cik)):
        return []
    source=source_window(document.text)
    if not source:
        return []
    source['start_offset']+=document.text_window_start
    heads=list(YEARS.finditer(source['text']))
    if not heads:
        return []
    observations=document.cash_flow_observations
    if (not isinstance(observations,(list,tuple)) or len(observations)>100
            or any(not isinstance(o,dict) for o in observations)):
        return []
    year,prior=heads[0].groups();selected=[]
    for y in (year,prior):
        rows=[o for o in observations if o.get('start')==f'{y}-01-01' and o.get('end')==f'{y}-12-31']
        if len(rows)!=1:
            return []
        selected.append(rows[0])
    candidate=reconstruct(source,selected,cik=cik)
    if not candidate:
        return []
    try:
        ref=ClaimDocumentReference(reference_id=f'document:{document.content_hash}:annual_cash_flow:{candidate["start_offset"]}',
            title=document.title or f'{ticker} 10-K',provider='SEC EDGAR',url=document.final_url,
            published_at=document.published_at,section=SECTION,content_hash=document.content_hash,quote=candidate['quote']).to_dict()
        value={**candidate,'claim_kind':KIND,'ticker':ticker,'document_ref':ref,
               'cash_flow_source_proof':source,'observations':selected}
        item=RetrievedEvidence(title=f'{ticker} annual operating cash explanation',source='SEC EDGAR',summary=_summary(value),
            timestamp=document.published_at,url=document.final_url,relevance_score=0.96,source_type='regulatory_filing',
            source_tier='primary',claim_type='reported_fact',document_type='10-K',filed_at=document.published_at,
            section=SECTION,extraction_method='html',cash_flow_disclosures=[value],
            reporting_period_start=candidate['cash_flow_context']['current_start'],
            reporting_period_end=candidate['cash_flow_context']['current_end'])
        return [item] if bound_annual_cash_flow_context(item,ticker=ticker,cik=cik) else []
    except (TypeError,ValueError):
        return []


def bound_annual_cash_flow_context(item, *, ticker, cik):
    from .thesis_disclosures import _business_issuer_url
    values=getattr(item,'cash_flow_disclosures',[])
    if not isinstance(values,list) or len(values)!=1 or not isinstance(values[0],dict):
        return None
    v=values[0]
    try:
        c=reconstruct(v['cash_flow_source_proof'],v['observations'],cik=cik)
        if not c or json.dumps(c,sort_keys=True,allow_nan=False)!=json.dumps({k:v[k] for k in c},sort_keys=True,allow_nan=False):
            return None
        ref=ClaimDocumentReference(**v['document_ref']).to_dict()
        if (v['claim_kind']!=KIND or v['ticker']!=ticker or ref['quote']!=v['quote'] or ref['provider']!='SEC EDGAR'
                or not re.fullmatch(r'[0-9a-f]{64}',ref.get('content_hash',''))
                or ref['url']!=item.url or not _business_issuer_url(item.url,cik)
                or ref['published_at']!=item.timestamp or item.filed_at!=item.timestamp
                or ref.get('section')!=SECTION or item.section!=SECTION
                or ref['reference_id']!=f'document:{ref["content_hash"]}:annual_cash_flow:{v["start_offset"]}'
                or date.fromisoformat(item.timestamp)>date.today() or v['cash_flow_context']['current_end']>item.timestamp
                or item.source!='SEC EDGAR' or item.source_type!='regulatory_filing' or item.source_tier!='primary'
                or item.claim_type!='reported_fact' or item.document_type!='10-K' or item.extraction_method!='html'
                or item.reporting_period_start!=v['cash_flow_context']['current_start']
                or item.reporting_period_end!=v['cash_flow_context']['current_end']
                or item.availability_status!='available' or item.freshness_status in {'stale','conflicting','superseded','unavailable'}
                or item.summary!=_summary(v)):
            return None
        return v
    except (KeyError,ValueError,TypeError,AttributeError,OverflowError):
        return None
