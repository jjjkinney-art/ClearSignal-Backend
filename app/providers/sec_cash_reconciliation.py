"""Complete indirect-cash table reconstruction, separate from answer admission.

Printed contributions and signed taxonomy values are different measurements.
The capsule retains the complete table and referenced resources for rebuilding;
its hash establishes consistency, not original-source authenticity. This module
is not yet wired into document ingestion, citations, /ask or feature flags.
"""
from datetime import date
from decimal import Decimal, localcontext
import hashlib
from io import StringIO
import re
from xml.etree import ElementTree as ET

from . import sec_inline_facts as base
from .sec_segment_facts import HIDDEN

XHTML = 'http://www.w3.org/1999/xhtml'
MAX_XML = 15_000_000
MAX_CAPSULE = 300_000
CURRENCIES = {'USD': '$', 'EUR': '€', 'GBP': '£'}
FIELDS = {'version', 'source_sha256', 'table_number', 'xml', 'capsule_sha256'}


def _digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _local(node):
    return node.tag.rsplit('}', 1)[-1]


def _clean(node):
    return ' '.join(''.join(node.itertext()).split())


def _read(text, limit):
    if not isinstance(text, str) or len(text) > limit or base._DECLARATION.search(text):
        raise ValueError('bounded XML without declarations required')
    namespaces, ids, depth, nodes = {}, {}, 0, 0
    parser = ET.iterparse(StringIO(text), events=('start', 'end', 'start-ns'))
    for event, value in parser:
        if event == 'start-ns':
            prefix, uri = value
            if prefix in namespaces and namespaces[prefix] != uri:
                raise ValueError('namespace rebinding unsupported')
            namespaces[prefix] = uri
            if len(namespaces) > 256 or len(prefix) > 200 or len(uri) > 2048:
                raise ValueError('namespace limit')
        elif event == 'start':
            depth += 1
            nodes += 1
            if depth > 128 or nodes > 200_000:
                raise ValueError('XML structure limit')
            identifier = value.get('id')
            if identifier:
                if identifier in ids:
                    raise ValueError('duplicate XML identifier')
                ids[identifier] = value
        else:
            depth -= 1
    return parser.root, namespaces, ids


def _qname(value, namespaces):
    parts = (value or '').split(':')
    if len(parts) != 2 or not base._ID.fullmatch(parts[1]):
        raise ValueError('explicit qualified name required')
    uri = namespaces.get(parts[0], '')
    if not re.fullmatch(r'https?://[^\s<>]{1,200}', uri):
        raise ValueError('unsupported concept namespace')
    return uri, parts[1]


def _context(node, *, cik):
    x = '{' + base.XBRLI + '}'
    entity, period = node.find(x + 'entity'), node.find(x + 'period')
    if (node.tag != x + 'context' or len(node) != 2 or entity is None or period is None
            or len(entity) != 1 or len(period) != 2):
        raise ValueError('consolidated duration context required')
    identifier = entity.find(x + 'identifier')
    start, end = period.find(x + 'startDate'), period.find(x + 'endDate')
    if any(n is None or len(n) for n in (identifier, start, end)):
        raise ValueError('scalar identity and period required')
    if identifier.get('scheme') != 'http://www.sec.gov/CIK' or not re.fullmatch(r'\d{1,10}', identifier.text or ''):
        raise ValueError('SEC identity required')
    if int(identifier.text) != int(cik):
        raise ValueError('issuer mismatch')
    a, b = date.fromisoformat(start.text), date.fromisoformat(end.text)
    if start.text != a.isoformat() or end.text != b.isoformat() or a != date(b.year, 1, 1) or b != date(b.year, 12, 31):
        raise ValueError('initial contract supports calendar annual columns only')
    return start.text, end.text


def _observation(fact, ids, namespaces, *, cik, currency):
    if (fact.tag != '{' + base.IX + '}nonFraction' or len(fact)
            or any(k in fact.attrib for k in ('tupleRef', 'target', 'continuedAt', 'precision'))
            or fact.get('{http://www.w3.org/2001/XMLSchema-instance}nil') is not None
            or not re.fullmatch(r'INF|-?\d{1,2}', fact.get('decimals', ''))):
        raise ValueError('unsupported inline fact')
    for key in ('id', 'contextRef', 'unitRef'):
        if not base._ID.fullmatch(fact.get(key, '')):
            raise ValueError('explicit resource IDs required')
    namespace, concept = _qname(fact.get('name'), namespaces)
    period = _context(ids[fact.get('contextRef')], cik=cik)
    unit = ids[fact.get('unitRef')]
    measure = unit.find('{' + base.XBRLI + '}measure')
    if unit.tag != '{' + base.XBRLI + '}unit' or len(unit) != 1 or measure is None or len(measure):
        raise ValueError('simple monetary unit required')
    if _qname(measure.text, namespaces) != (base.USD, currency):
        raise ValueError('currency mismatch; no conversion')
    scale_text, sign = fact.get('scale', '0'), fact.get('sign', '')
    if not re.fullmatch(r'-?\d', scale_text) or sign not in ('', '-'):
        raise ValueError('unsupported scale/sign')
    literal = (fact.text or '').strip()
    if len(literal) > 80:
        raise ValueError('literal limit')
    transform = _qname(fact.get('format'), namespaces) if fact.get('format') else ('', '')
    fixed_zero = transform[0] in {
        'http://www.xbrl.org/inlineXBRL/transformation/2020-02-12',
        'http://www.xbrl.org/inlineXBRL/transformation/2022-02-16'} and transform[1] == 'fixed-zero'
    if fixed_zero:
        if literal != '-':
            raise ValueError('reviewed fixed-zero literal required')
        magnitude = 0
    else:
        if transform != ('', '') and transform[1] not in base._TRANSFORMS.get(transform[0], set()):
            raise ValueError('unsupported transformation')
        grammar = r'(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?' if transform != ('', '') else r'\d+(?:\.\d+)?'
        if not re.fullmatch(grammar, literal):
            raise ValueError('unsupported literal')
        with localcontext() as arithmetic:
            arithmetic.prec = 100
            exact = Decimal(literal.replace(',', '')) * (Decimal(10) ** int(scale_text))
        if exact != exact.to_integral_value() or abs(exact) > 10**18:
            raise ValueError('exact bounded currency amount required')
        magnitude = int(exact)
    return {'fact_id': fact.get('id'), 'context_id': fact.get('contextRef'),
        'unit_id': fact.get('unitRef'), 'concept_namespace': namespace, 'concept': concept,
        'period_start': period[0], 'period_end': period[1], 'currency': currency,
        'literal': literal, 'scale': int(scale_text), 'format_namespace': transform[0],
        'format': transform[1], 'sign': sign, 'magnitude': magnitude,
        'signed_taxonomy_value': -magnitude if sign == '-' else magnitude}


def _rows(table):
    if sum(n.tag == '{' + XHTML + '}table' for n in table.iter()) != 1:
        raise ValueError('nested cash table unsupported')
    for n in table.iter():
        if (_local(n) in {'script', 'style', 'noscript', 'template', 'svg', 'hidden'}
                or 'hidden' in n.attrib or HIDDEN.search(n.get('style', ''))):
            raise ValueError('hidden/active table content unsupported')
    rows, in_rows = [], set()
    for tr in table.iter('{' + XHTML + '}tr'):
        cells = []
        for cell in tr:
            if cell.tag not in {'{' + XHTML + '}td', '{' + XHTML + '}th'}:
                raise ValueError('unsupported row child')
            span = cell.get('colspan', '1')
            if cell.get('rowspan', '1') != '1' or not re.fullmatch(r'[1-9]\d?', span):
                raise ValueError('unsupported spanning cell')
            if len(_clean(cell)) > 500:
                raise ValueError('cell length limit')
            cells.extend([cell] * int(span))
        if len(cells) > 50 or len(rows) >= 150:
            raise ValueError('table size limit')
        rows.append(cells)
        in_rows.update(id(f) for c in cells for f in c.iter('{' + base.IX + '}nonFraction'))
    if in_rows != {id(f) for f in table.iter('{' + base.IX + '}nonFraction')}:
        raise ValueError('facts outside table cells')
    return rows


def _bridge(table, ids, namespaces, *, cik, currency):
    rows = _rows(table)
    headings = [(i, _clean(r[0]).lower()) for i, r in enumerate(rows) if r]
    opens = [i for i, label in headings if label == 'cash flows from operating activities:']
    closes = [i for i, label in headings if label == 'cash flows from investing activities:']
    if len(opens) != 1 or len(closes) != 1 or not opens[0] < closes[0]:
        raise ValueError('complete operating/investing boundaries required')
    a, b = opens[0], closes[0]
    if any(_clean(c) for i in (a, b) for c in rows[i][1:]):
        raise ValueError('unbound boundary row content')
    if not any('For the years ended December 31,' in ' '.join(_clean(c) for c in r) for r in rows[:a]):
        raise ValueError('calendar annual heading required')
    headers = [r for r in rows[:a] if len({id(c) for c in r if re.fullmatch(r'20\d{2}', _clean(c))}) in (2, 3)]
    if len(headers) != 1:
        raise ValueError('unambiguous two/three-year header required')
    header = headers[0]
    records, columns, periods, used_ids = [], None, None, set()
    for row in rows[a + 1:b]:
        texts = [_clean(c) for c in row]
        if not any(texts):
            continue
        if len(row) != len(header) or not texts[0] or len(texts[0]) > 180:
            raise ValueError('complete aligned row required')
        fact_cells = [(i, c, list(c.iter('{' + base.IX + '}nonFraction')))
                      for i, c in enumerate(row) if not i or c is not row[i - 1]]
        fact_cells = [(i, c, fs) for i, c, fs in fact_cells if fs]
        if not fact_cells:
            if any(texts[1:]) or texts[0] not in {
                    'Adjustments to reconcile net earnings to net cash provided by operating activities:',
                    'Changes in operating accounts:'}:
                raise ValueError('untagged numeric row')
            continue
        if columns is None:
            columns = [i for i, _, _ in fact_cells]
        if len(columns) not in (2, 3) or [i for i, _, _ in fact_cells] != columns:
            raise ValueError('missing or extra fact column')
        values, occupied = [], {0}
        for i, cell, facts in fact_cells:
            if len(facts) != 1 or row.count(cell) != 1 or i + 1 >= len(row):
                raise ValueError('one fact in one cell required')
            obs = _observation(facts[0], ids, namespaces, cik=cik, currency=currency)
            if obs['fact_id'] in used_ids:
                raise ValueError('duplicate displayed fact')
            used_ids.add(obs['fact_id'])
            if _clean(header[i]) != obs['period_end'][:4]:
                raise ValueError('visible year/context mismatch')
            negative = texts[i] == '(' + obs['literal']
            if texts[i] not in (obs['literal'], '(' + obs['literal']) or texts[i + 1] != (')' if negative else ''):
                raise ValueError('explicit display sign required')
            values.append({**obs, 'column': i, 'display_contribution': -obs['magnitude'] if negative else obs['magnitude']})
            occupied.update((i, i + 1))
        if any(texts[i] not in ('', CURRENCIES[currency]) for i in range(len(row)) if i not in occupied):
            raise ValueError('unbound numeric or descriptive cell')
        row_periods = [(v['period_start'], v['period_end'], v['context_id']) for v in values]
        if periods is None:
            periods = row_periods
        if row_periods != periods or len({(v['concept_namespace'], v['concept']) for v in values}) != 1:
            raise ValueError('period/context or row concept mismatch')
        records.append({'label': texts[0], 'values': values})
    if not records or len(records) < 3:
        raise ValueError('earnings, adjustments and total required')
    for record, concept in ((records[0], 'NetIncomeLoss'), (records[-1], 'NetCashProvidedByUsedInOperatingActivities')):
        if any(v['concept'] != concept or not base._GAAP.fullmatch(v['concept_namespace']) for v in record['values']):
            raise ValueError('standard earnings and operating cash anchors required')
    anchors = {'NetIncomeLoss', 'NetCashProvidedByUsedInOperatingActivities'}
    if len({(r['values'][0]['concept_namespace'], r['values'][0]['concept']) for r in records}) != len(records):
        raise ValueError('repeated concept or subtotal ambiguity')
    if any(v['concept'] in anchors and base._GAAP.fullmatch(v['concept_namespace'])
           for r in records[1:-1] for v in r['values']):
        raise ValueError('intermediate anchor or subtotal unsupported')
    if len({p[:2] for p in periods}) != len(periods) or [p[1] for p in periods] != sorted((p[1] for p in periods), reverse=True):
        raise ValueError('distinct newest-first periods required')
    if any(int(periods[i][1][:4]) != int(periods[i + 1][1][:4]) + 1 for i in range(len(periods) - 1)):
        raise ValueError('adjacent annual periods required')
    totals = []
    for i, (start, end, _) in enumerate(periods):
        values = [r['values'][i] for r in records]
        total = values[-1]['display_contribution']
        if values[-1]['signed_taxonomy_value'] != total or values[0]['signed_taxonomy_value'] != values[0]['display_contribution']:
            raise ValueError('anchor display/taxonomy disagreement')
        component_sum = sum(v['display_contribution'] for v in values[:-1])
        if component_sum != total:
            raise ValueError('exact reconciliation required; no residual plug')
        totals.append({'start': start, 'end': end, 'component_sum': component_sum, 'operating_cash_flow': total, 'residual': 0})
    changes = [{'label': r['label'], 'change': r['values'][0]['display_contribution'] - r['values'][1]['display_contribution']}
               for r in records[:-1]]
    delta = totals[0]['operating_cash_flow'] - totals[1]['operating_cash_flow']
    if sum(r['change'] for r in changes) != delta:
        raise ValueError('component change reconciliation required')
    return {'currency': currency, 'scope': 'consolidated_calendar_annual', 'rows': records,
        'totals': totals, 'current_vs_prior_component_changes': changes, 'operating_cash_flow_change': delta,
        'admitted': False, 'source_binding_established': False,
        'semantic_component_nonoverlap_verified': False, 'launch_ready': False}


def reconstruct_cash_reconciliation(proof, *, cik, currency='USD'):
    try:
        if (not isinstance(proof, dict) or set(proof) != FIELDS or proof['version'] != 1
                or type(proof['version']) is not int or type(proof['table_number']) is not int
                or proof['table_number'] < 1 or not re.fullmatch(r'[0-9a-f]{64}', proof['source_sha256'])
                or proof['capsule_sha256'] != _digest(proof['xml']) or currency not in CURRENCIES
                or not isinstance(cik, str) or not re.fullmatch(r'\d{1,10}', cik) or int(cik) == 0):
            return None
        root, namespaces, ids = _read(proof['xml'], MAX_CAPSULE)
        tables = list(root.iter('{' + XHTML + '}table'))
        if len(tables) != 1:
            return None
        return _bridge(tables[0], ids, namespaces, cik=cik, currency=currency)
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, ET.ParseError):
        return None


def parse_cash_reconciliations(text, *, cik, currency='USD'):
    """Return one complete-table capsule or a gap; does not create evidence."""
    try:
        root, namespaces, ids = _read(text, MAX_XML)
        tables = []
        def visit(node, hidden=False):
            hidden = hidden or 'hidden' in node.attrib or bool(HIDDEN.search(node.get('style', '')))
            if node.tag == '{' + XHTML + '}table' and not hidden:
                tables.append(node)
            for child in node:
                visit(child, hidden or _local(node) in {'hidden', 'script', 'style', 'template', 'svg', 'noscript', 'header'})
        visit(root)
        candidates = []
        for number, table in enumerate(tables, 1):
            if not any(f.get('name', '').endswith(':NetCashProvidedByUsedInOperatingActivities')
                       for f in table.iter('{' + base.IX + '}nonFraction')):
                continue
            # Do not silently choose among competing complete cash tables.
            candidates.append((number, table))
        if len(candidates) != 1:
            return ()
        number, table = candidates[0]
        facts = list(table.iter('{' + base.IX + '}nonFraction'))
        resources = sorted({f.get(k) for f in facts for k in ('contextRef', 'unitRef')})
        wrapper = ET.Element('cash-proof')
        for prefix, uri in namespaces.items():
            if prefix != 'xml':
                wrapper.set('xmlns' + (':' + prefix if prefix else ''), uri)
        wrapper.extend([ids[k] for k in resources] + [table])
        capsule = ET.tostring(wrapper, encoding='unicode')
        proof = {'version': 1, 'source_sha256': _digest(text), 'table_number': number,
                 'xml': capsule, 'capsule_sha256': _digest(capsule)}
        return (proof,) if reconstruct_cash_reconciliation(proof, cik=cik, currency=currency) else ()
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, ET.ParseError):
        return ()
