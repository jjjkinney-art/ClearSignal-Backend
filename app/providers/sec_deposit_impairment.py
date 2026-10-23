"""Visible-label qualified custom deposit expense; consolidated GAAP rules stay separate."""
from datetime import date
from decimal import Decimal, localcontext
import re
from xml.etree import ElementTree as ET

from . import sec_inline_facts as base
from .sec_segment_facts import _Target as TableTarget, _expanded, clean

EXPENSE = re.compile(r'Impairment of (?:a )?(?:vendor|supplier) deposits?\Z', re.I)
RECONCILIATION = re.compile(r'Loss on impairment of (?:a )?(?:vendor|supplier) deposits?\Z', re.I)
TITLE = re.compile(r'CONSOLIDATED STATEMENTS OF (COMPREHENSIVE INCOME|INCOME|OPERATIONS|CASH FLOWS)', re.I)
ADJUSTMENTS = 'Adjustments to reconcile net earnings to net cash provided by operating activities:'


def amount(v, *, cik):
    """Custom observation scalar checks; never substitute a GAAP concept/namespace."""
    try:
        keys={'concept_namespace','concept','fact_id','context_id','unit_id','literal','format_namespace',
              'format','sign','scale','entity_scheme','entity_identifier','start','end','unit_namespace','unit','scope'}
        if (not isinstance(v,dict) or set(v)!=keys
                or not re.fullmatch(r'https?://[A-Za-z0-9.-]+/[^\s]{1,180}', v['concept_namespace'])
                or base._GAAP.fullmatch(v['concept_namespace'])
                or v['concept_namespace'] in {base.XBRLI,base.IX,base.USD,'http://www.w3.org/1999/xhtml'}
                or re.fullmatch(r'https?://fasb\.org/srt/.*',v['concept_namespace'])
                or not base._ID.fullmatch(v['concept']) or v['scope'] != 'consolidated'
                or v['entity_scheme'] != 'http://www.sec.gov/CIK'
                or not re.fullmatch(r'[0-9]{1,10}', v['entity_identifier'])
                or int(v['entity_identifier']) != int(cik)
                or v['unit'] != 'USD' or v['unit_namespace'] != base.USD
                or any(not base._ID.fullmatch(v[k]) for k in ('fact_id','context_id','unit_id'))
                or v['sign'] != '' or type(v['scale']) is not int or v['scale'] != 3
                or v['format'] not in base._TRANSFORMS.get(v['format_namespace'], set())
                or len(v['literal'])>80
                or not re.fullmatch(r'(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)', v['literal'])):
            return None
        a,b = date.fromisoformat(v['start']), date.fromisoformat(v['end'])
        if not 330 <= (b-a).days <= 380 or b.month != 12 or b.day != 31:
            return None
        with localcontext() as ctx:
            ctx.prec = 100
            result = Decimal(v['literal'].replace(',','')) * 1000
        return int(result) if 0 < result <= Decimal('1e18') else None
    except (KeyError, TypeError, ValueError, AttributeError, ArithmeticError):
        return None


class _Target(TableTarget):
    def _resource(self, element):
        # The base resource contract excludes both segment and scenario nodes.
        return base._InlineTarget._resource(self, element)

    def _fact(self, frame):
        fact = frame['element']; attrs = fact.attrib
        namespace, concept = base._qname(frame['scope'], attrs.get('name'))
        if (not base._ID.fullmatch(concept) or base._GAAP.fullmatch(namespace)
                or frame['children'] or frame['text_overflow']
                or any(k in attrs for k in ('tupleRef','target','continuedAt','precision'))
                or attrs.get('{http://www.w3.org/2001/XMLSchema-instance}nil') is not None
                or not re.fullmatch(r'(?:INF|-?[0-9]{1,2})',attrs.get('decimals',''))
                or (self.visibility and self.visibility[-1])):
            return
        ids = [attrs.get(k,'') for k in ('id','contextRef','unitRef')]
        if any(not base._ID.fullmatch(i) for i in ids):
            return
        try:
            scale = int(attrs.get('scale','0'))
        except ValueError:
            return
        ns, fmt = base._qname(frame['scope'],attrs.get('format'))
        if len(self.facts) >= base.MAX_FACTS:
            raise base._ParseLimit('custom expense fact limit')
        self.facts.append(dict(concept_namespace=namespace,concept=concept,
            fact_id=ids[0],context_id=ids[1],unit_id=ids[2],literal=(fact.text or '').strip(),
            format_namespace=ns,format=fmt,sign=attrs.get('sign',''),scale=scale))


def _table_value(table, observations, *, cik):
    if (not isinstance(table,dict) or type(table.get('table_number')) is not int
            or not 1 <= table['table_number'] <= 2000 or table.get('invalid')
            or not isinstance(table.get('rows'),list) or len(table['rows']) > 150
            or len(table.get('paragraphs',[])) > 10):
        return None
    if (any(not isinstance(p,str) or len(p)>2000 for p in table['paragraphs'])
            or any(not isinstance(r,list) or len(r)>50 for r in table['rows'])
            or any(not isinstance(c.get('text'),str) or len(c['text'])>500 for r in table['rows'] for c in r)):
        return None
    paragraphs=[p.replace('\ufeff','').strip() for p in table['paragraphs'] if p.replace('\ufeff','').strip()]
    if (len(paragraphs)<2 or not TITLE.fullmatch(paragraphs[-2])
            or not re.fullmatch(r'\(In thousands(?: except per share data)?\)',paragraphs[-1],re.I)):
        return None
    role = 'cash_flow_reconciliation' if TITLE.fullmatch(paragraphs[-2])[1].upper() == 'CASH FLOWS' else 'income_statement'
    rows = [_expanded(r) for r in table['rows']]
    if any(r is None for r in rows):
        return None
    header_rows = []
    for i,row in enumerate(rows):
        bands = [(j,c['text']) for j,c in enumerate(row) if re.fullmatch(r'20\d{2}',c['text'])]
        years = list(dict.fromkeys(y for _,y in bands))
        if 2 <= len(years) <= 4 and list(map(int,years)) == list(range(int(years[0]),int(years[0])-len(years),-1)):
            header_rows.append((i,years[0],{j for j,y in bands if y==years[0]}))
    if len(header_rows) != 1:
        return None
    header,year,columns = header_rows[0]
    if not any('For the years ended December 31' in c['text'] for row in rows[:header] for c in row):
        return None
    selected = []
    for index,row in enumerate(rows):
        label = next((c['text'] for c in row if c['text']), '')
        pattern = EXPENSE if role=='income_statement' else RECONCILIATION
        if not pattern.fullmatch(label):
            continue
        if index <= header or (role=='cash_flow_reconciliation' and not any(
                c['text']==ADJUSTMENTS for r in rows[header+1:index] for c in r)):
            return None
        ids = list(dict.fromkeys(fid for j,c in enumerate(row) if j in columns for fid in c['fact_ids']))
        if len(ids)!=1 or ids[0] not in observations:
            return None
        v=observations[ids[0]]; n=amount(v,cik=cik)
        cells=[c for j,c in enumerate(row) if j in columns]
        visible={c['text'] for c in cells if c['text']}
        if (n is None or v['end']!=year+'-12-31' or visible-{'$',v['literal']}
                or not any(c['fact_ids']==ids and c['text']==v['literal'] for c in cells)):
            return None
        selected.append({'role':role,'table_number':table['table_number'],'label':label,
            'row_text':clean(' '.join(c['text'] for c in table['rows'][index])),
            'observation':v,'amount_usd':n})
    return selected[0] if len(selected)==1 else None


def reconstruct(proof, *, cik):
    try:
        if (not isinstance(proof,dict) or set(proof)!={'tables','observations'}
                or not isinstance(proof['tables'],list) or len(proof['tables'])!=2
                or not isinstance(proof['observations'],list) or len(proof['observations'])>100):
            return None
        obs={v['fact_id']:v for v in proof['observations']}
        if len(obs)!=len(proof['observations']):
            return None
        values=[_table_value(t,obs,cik=cik) for t in proof['tables']]
        if any(v is None for v in values) or {v['role'] for v in values}!={'income_statement','cash_flow_reconciliation'}:
            return None
        a=next(v for v in values if v['role']=='income_statement')
        b=next(v for v in values if v['role']=='cash_flow_reconciliation')
        if a['table_number']==b['table_number'] or a['amount_usd']!=b['amount_usd']:
            return None
        keys=('concept_namespace','concept','start','end','entity_identifier','unit','unit_namespace','scale','sign')
        if any(a['observation'][k]!=b['observation'][k] for k in keys):
            return None
        # Other positive observations of this concept/period must agree too.
        for v in obs.values():
            if all(v[k]==a['observation'][k] for k in ('concept_namespace','concept','start','end')) and amount(v,cik=cik)!=a['amount_usd']:
                return None
        return {'amount_usd':a['amount_usd'],'currency':'USD','start':a['observation']['start'],
            'end':a['observation']['end'],'scope':'consolidated_expense','income_statement':a,
            'cash_flow_reconciliation':b,'duplicate_presentations_not_added':True}
    except (KeyError,TypeError,ValueError,AttributeError,ArithmeticError):
        return None


def parse_impairment_tables(text, *, cik):
    if not isinstance(text,str) or len(text)>15_000_000 or base._DECLARATION.search(text):
        return ()
    target=_Target();parser=ET.XMLParser(target=target)
    try:
        for i in range(0,len(text),16384):parser.feed(text[i:i+16384])
        parser.close()
    except (ET.ParseError,ValueError,TypeError,base._ParseLimit):
        return ()
    obs=[]
    for f in target.facts:
        if any(f[k] in target.duplicates for k in ('fact_id','context_id','unit_id')):
            continue
        c,u=target.contexts.get(f['context_id']),target.units.get(f['unit_id'])
        if c is not None and u is not None:
            v=dict(**f,**c,**u,scope='consolidated')
            if amount(v,cik=cik) is not None:obs.append(v)
    eligible=[]
    for t in target.tables:
        if any(EXPENSE.fullmatch(c['text']) or RECONCILIATION.fullmatch(c['text']) for r in t['rows'] for c in r):
            eligible.append({k:t[k] for k in ('table_number','paragraphs','rows','invalid')})
    # Multiple matching statements/layouts are ambiguous, not first-wins.
    proof={'tables':eligible,'observations':obs}
    return (proof,) if reconstruct(proof,cik=cik) else ()
