"""Bounded annual segment tables; never relax consolidated Inline XBRL scope.

The XML target shares the existing strict scalar/namespace/resource limits, then
requires explicit dimensions, visible column binding and accounting caveats.
"""
from collections import deque
from datetime import date
import re
from xml.etree import ElementTree as ET

from . import sec_inline_facts as base

XHTML = 'http://www.w3.org/1999/xhtml'
XBRLDI = 'http://xbrl.org/2006/xbrldi'
SRT = re.compile(r'https?://fasb\.org/srt/20\d{2}(?:-\d{2}-\d{2})?\Z')
CONCEPTS = ('Revenues', 'RevenueFromContractWithCustomerExcludingAssessedTax', 'OperatingIncomeLoss')
HIDDEN = re.compile(r'(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden)\s*(?:!important\s*)?(?:;|$)', re.I)
DEFINITION = 'In the following summary, operating profit represents earnings before other income and income taxes.'
ALLOCATION = re.compile(r"Costs associated with corporate activities \([^.;]{1,120}\) and the assets associated with such activities are included within the (?P<label>[A-Za-z][A-Za-z /&-]{1,79}) segment for all periods presented\.")


def clean(text):
    return re.sub(r'\s+', ' ', text).strip()


def valid_dimensions(dimensions):
    if not isinstance(dimensions, list) or len(dimensions) != 2:
        return False
    consolidation, segment = dimensions
    return bool(set(consolidation) == set(segment) == {'axis_namespace', 'axis', 'member_namespace', 'member'}
        and SRT.fullmatch(consolidation['axis_namespace'])
        and consolidation['axis'] == 'ConsolidationItemsAxis'
        and base._GAAP.fullmatch(consolidation['member_namespace'])
        and consolidation['member'] == 'OperatingSegmentsMember'
        and base._GAAP.fullmatch(segment['axis_namespace'])
        and segment['axis'] == 'StatementBusinessSegmentsAxis'
        and re.fullmatch(r'https?://[A-Za-z0-9.-]+/[^\s]{1,180}', segment['member_namespace'])
        and base._ID.fullmatch(segment['member']))


def valid_total_dimensions(dimensions):
    # A segment-table aggregation is still not a consolidated company fact.
    if not isinstance(dimensions, list) or len(dimensions) != 1:
        return False
    d = dimensions[0]
    return bool(set(d) == {'axis_namespace', 'axis', 'member_namespace', 'member'}
        and SRT.fullmatch(d['axis_namespace']) and d['axis'] == 'ConsolidationItemsAxis'
        and base._GAAP.fullmatch(d['member_namespace']) and d['member'] == 'OperatingSegmentsMember')


def total_amount(observation, *, cik):
    try:
        if observation.get('scope') != 'reported_segment_total' or not valid_total_dimensions(observation['dimensions']):
            return None
        # Preserve the total scope; copy only for the existing scalar checks.
        start, end = date.fromisoformat(observation['start']), date.fromisoformat(observation['end'])
        if not 330 <= (end - start).days <= 380:
            return None
        return base.validated_observation({**observation, 'scope': 'consolidated'}, cik=cik, concepts=CONCEPTS)
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def amount(observation, *, cik):
    """Only a separately validated dimensional observation may reuse scalar math."""
    if not isinstance(observation, dict) or observation.get('scope') != 'segment':
        return None
    try:
        if not valid_dimensions(observation['dimensions']):
            return None
        start, end = date.fromisoformat(observation['start']), date.fromisoformat(observation['end'])
        if not 330 <= (end - start).days <= 380:
            return None
        # Local copy solely for scalar checks; never returned as consolidated.
        return base.validated_observation({**observation, 'scope': 'consolidated'}, cik=cik, concepts=CONCEPTS)
    except (KeyError, TypeError, ValueError):
        return None


class _Target(base._InlineTarget):
    def __init__(self):
        super().__init__(CONCEPTS)
        self.visibility = []
        self.tables, self.table_stack = [], []
        self.paragraph = None
        self.paragraphs = deque(maxlen=10)
        self.cell_count = 0

    def start(self, tag, attrs):
        super().start(tag, attrs)
        if tag == f'{{{XBRLDI}}}explicitMember' and self.resource is not None and not self.resource_invalid:
            self.resource_namespaces[id(self.stack[-1]['element'])] = self.scope
        local = tag.rsplit('}', 1)[-1]
        hidden = (bool(self.visibility and self.visibility[-1]) or local in {'script', 'style', 'noscript', 'template', 'svg', 'header', 'hidden'}
                  or 'hidden' in attrs or bool(HIDDEN.search(attrs.get('style', ''))))
        self.visibility.append(hidden)
        if tag == f'{{{XHTML}}}table':
            if len(self.tables) >= 2000:
                raise base._ParseLimit('segment table limit')
            if self.table_stack:
                self.table_stack[-1]['invalid'] = True
            table = dict(table_number=len(self.tables) + 1, rows=[], row=None, cell=None,
                         invalid=hidden or bool(self.table_stack), paragraphs=list(self.paragraphs))
            self.tables.append(table)
            self.table_stack.append(table)
        elif self.table_stack:
            table = self.table_stack[-1]
            if tag == f'{{{XHTML}}}tr':
                if table['row'] is not None:
                    table['invalid'] = True
                table['row'] = []
                table['rows'].append(table['row'])
                if len(table['rows']) > 150:
                    table['invalid'] = True
            elif tag in {f'{{{XHTML}}}td', f'{{{XHTML}}}th'}:
                self.cell_count += 1
                if self.cell_count > 40000:
                    raise base._ParseLimit('segment cell limit')
                if table['row'] is None or table['cell'] is not None:
                    table['invalid'] = True
                cell = dict(text='', parts=[], fact_ids=[], colspan=attrs.get('colspan', '1'),
                            rowspan=attrs.get('rowspan', '1'), hidden=hidden)
                table['cell'] = cell
                if table['row'] is not None:
                    table['row'].append(cell)
            elif tag == f'{{{base.IX}}}nonFraction' and table['cell'] is not None:
                if hidden:
                    table['invalid'] = True
                table['cell']['fact_ids'].append(attrs.get('id', ''))
        if tag == f'{{{XHTML}}}p' and not self.table_stack and not hidden:
            self.paragraph = []

    def data(self, text):
        if self.stack and self.stack[-1]['tag'] == f'{{{XBRLDI}}}explicitMember':
            frame = self.stack[-1]
            if frame['element'] is not None:
                if len(frame['element'].text or '') + len(text) > 500:
                    self.resource_invalid = True
                else:
                    frame['element'].text = (frame['element'].text or '') + text
        super().data(text)
        if self.visibility and self.visibility[-1]:
            return
        if self.table_stack and self.table_stack[-1]['cell'] is not None:
            parts = self.table_stack[-1]['cell']['parts']
            if sum(map(len, parts)) + len(text) > 500:
                self.table_stack[-1]['invalid'] = True
            else:
                parts.append(text)
        elif self.paragraph is not None:
            if sum(map(len, self.paragraph)) + len(text) <= 2000:
                self.paragraph.append(text)
            else:
                self.paragraph = None

    def end(self, tag):
        if self.table_stack:
            table = self.table_stack[-1]
            if tag in {f'{{{XHTML}}}td', f'{{{XHTML}}}th'}:
                if table['cell'] is not None:
                    table['cell']['text'] = clean(''.join(table['cell'].pop('parts')))
                table['cell'] = None
            elif tag == f'{{{XHTML}}}tr':
                table['row'] = None
            elif tag == f'{{{XHTML}}}table':
                self.table_stack.pop()
        elif tag == f'{{{XHTML}}}p' and self.paragraph is not None:
            self.paragraphs.append(clean(''.join(self.paragraph)))
            self.paragraph = None
        super().end(tag)
        self.visibility.pop()

    def _resource(self, element):
        if element.tag != f'{{{base.XBRLI}}}context':
            return super()._resource(element)
        x = f'{{{base.XBRLI}}}'
        entity, period = element.find(x + 'entity'), element.find(x + 'period')
        if entity is None or period is None or len(element) != 2 or len(entity) != 2 or len(period) != 2:
            return
        identifier, segment = entity.find(x + 'identifier'), entity.find(x + 'segment')
        start, end = period.find(x + 'startDate'), period.find(x + 'endDate')
        if any(n is None or len(n) for n in (identifier, start, end)) or segment is None or len(segment) not in {1, 2}:
            return
        dimensions = []
        for member in segment:
            if member.tag != f'{{{XBRLDI}}}explicitMember' or len(member):
                return
            scope = self.resource_namespaces.get(id(member), {})
            axis_ns, axis = base._qname(scope, member.get('dimension'))
            member_ns, name = base._qname(scope, (member.text or '').strip())
            dimensions.append(dict(axis_namespace=axis_ns, axis=axis, member_namespace=member_ns, member=name))
        dimensions.sort(key=lambda v: 0 if v['axis'] == 'ConsolidationItemsAxis' else 1)
        if not (valid_dimensions(dimensions) or valid_total_dimensions(dimensions)) or not base._ID.fullmatch(element.get('id', '')):
            return
        self.contexts[element.get('id')] = dict(entity_scheme=identifier.get('scheme'),
            entity_identifier=(identifier.text or '').strip(), start=(start.text or '').strip(),
            end=(end.text or '').strip(), dimensions=dimensions)


def _expanded(row):
    cells = []
    for cell in row:
        if cell['hidden'] or cell['rowspan'] != '1' or not re.fullmatch(r'[1-9]\d?', cell['colspan']):
            return None
        cells.extend([cell] * int(cell['colspan']))
    return cells if len(cells) <= 50 else None


def _caveats(paragraphs):
    # Both complete sentences must be in the immediately preceding substantive
    # paragraph. Do not borrow a definition/allocation from an unrelated table.
    paragraph = next((p for p in reversed(paragraphs) if p.replace('\ufeff', '').strip()), '')
    start = paragraph.find(DEFINITION)
    match = ALLOCATION.search(paragraph)
    if (start < 0 or not match or match.start() < start + len(DEFINITION)
            or (start != 0 and not paragraph[:start].endswith('. '))
            or (match.start() != 0 and not paragraph[:match.start()].endswith('. '))):
        return None, None
    return DEFINITION, match.group(0)


def parse_segment_tables(text, *, cik):
    """Return bounded table proofs, not consolidated observations or conclusions."""
    if not isinstance(text, str) or len(text) > 15_000_000 or base._DECLARATION.search(text):
        return ()
    target = _Target()
    parser = ET.XMLParser(target=target)
    try:
        for offset in range(0, len(text), 16384):
            parser.feed(text[offset:offset + 16384])
        parser.close()
    except (ET.ParseError, ValueError, TypeError, base._ParseLimit):
        return ()
    facts = {}
    conflicts = set()
    keys = {}
    for fact in target.facts:
        if any(fact[key] in target.duplicates for key in ('fact_id', 'context_id', 'unit_id')):
            continue
        context, unit = target.contexts.get(fact['context_id']), target.units.get(fact['unit_id'])
        if context is None or unit is None:
            continue
        scope = 'segment' if len(context['dimensions']) == 2 else 'reported_segment_total'
        observation = dict(**fact, **context, **unit, scope=scope)
        value = amount(observation, cik=cik) if scope == 'segment' else total_amount(observation, cik=cik)
        if value is None:
            continue
        key = (observation['start'], observation['end'], observation['concept'],
               tuple((d['axis_namespace'], d['axis'], d['member_namespace'], d['member']) for d in observation['dimensions']))
        if key in keys and keys[key] != value:
            conflicts.add(key)
        keys[key] = value
        facts[fact['fact_id']] = (observation, key)
    result = []
    for table in target.tables:
        definition, allocation = _caveats(table['paragraphs'])
        if table['invalid'] or not definition or not allocation:
            continue
        rows = [_expanded(row) for row in table['rows']]
        if any(row is None for row in rows):
            continue
        headers = next((row for row in rows if sum(bool(c['text']) for i, c in enumerate(row)
                                                   if not i or c is not row[i - 1]) >= 3
                        and any(c['text'] == 'Total' for c in row)
                        and not any(c['fact_ids'] for c in row)), None)
        if not headers or len(headers) < 4 or not any(c['text'] == '(in thousands)' for row in rows[:2] for c in row):
            continue
        periods = {}
        period = None
        for row in rows:
            text_row = clean(' '.join(c['text'] for i, c in enumerate(row) if not i or c is not row[i - 1]))
            match = re.fullmatch(r'Year ended December 31, (20\d{2})', text_row)
            if match:
                period = match[1] + '-12-31'
                if period in periods:
                    table['invalid'] = True
                periods.setdefault(period, {})
                continue
            if text_row.startswith('Year ended'):
                table['invalid'] = True
                period = None
                continue
            if period is None or not row:
                continue
            metric = {'External net sales': 'revenue', 'Operating profit (loss)': 'operating_income'}.get(row[0]['text'])
            if not metric or len(row) != len(headers):
                continue
            entries = []
            total = None
            for column, cell in enumerate(row):
                if column and cell is row[column - 1]:
                    continue
                if len(cell['fact_ids']) != 1:
                    continue
                pair = facts.get(cell['fact_ids'][0])
                if not pair or pair[1] in conflicts:
                    continue
                observation = pair[0]
                label = headers[column]['text']
                if not label or observation['end'] != period:
                    continue
                if metric == 'revenue' and observation['concept'] not in CONCEPTS[:2]:
                    continue
                if metric == 'operating_income' and observation['concept'] != CONCEPTS[2]:
                    continue
                entry = {'label': label, 'column': column, 'observation': observation}
                if label == 'Total':
                    if total is not None:
                        total = {'ambiguous': True}
                    else:
                        total = entry
                else:
                    entries.append(entry)
            bucket = periods.setdefault(period, {})
            if metric in bucket:
                table['invalid'] = True
            bucket[metric] = {'entries': entries, 'row_text': text_row,
                              'cells': [{'text': c['text'], 'fact_ids': c['fact_ids']} for c in row],
                              'total': total}
        for period, metrics in sorted(periods.items(), reverse=True)[:1]:
            proof = {'table_number': table['table_number'], 'period_end': period,
                     'unit_heading': '(in thousands)', 'headers': [c['text'] for c in headers],
                     'period_label': 'Year ended December 31, ' + period[:4], 'definition': definition,
                     'allocation': allocation, 'metrics': metrics}
            if not table['invalid'] and reconstruct(proof, cik=cik) is not None:
                result.append(proof)
                break  # latest supported year in each table; no stale substitution within a table
        if len(result) >= 1:
            break
    return tuple(result)


def reconstruct(proof, *, cik):
    """Recheck dimensions, labels, scalar semantics, annual periods and caveats."""
    try:
        if (type(proof['table_number']) is not int or not 1 <= proof['table_number'] <= 2000
                or proof['definition'] != DEFINITION or proof['unit_heading'] != '(in thousands)'
                or not ALLOCATION.fullmatch(proof['allocation']) or set(proof['metrics']) != {'revenue', 'operating_income'}):
            return None
        if proof['period_label'] != 'Year ended December 31, ' + proof['period_end'][:4] or not proof['period_end'].endswith('-12-31'):
            return None
        if not 4 <= len(proof['headers']) <= 50 or 'Total' not in proof['headers']:
            return None
        revenue = proof['metrics']['revenue']['entries']
        income = proof['metrics']['operating_income']['entries']
        if not 2 <= len(revenue) == len(income) <= 8:
            return None
        expected_labels = {label for label in proof['headers'] if label and label != 'Total'}
        if expected_labels != {entry['label'] for entry in revenue}:
            return None
        rows = []
        seen = set()
        columns = [entry['column'] for entry in revenue]
        if columns != sorted(set(columns)):
            return None
        for sales, profit in zip(revenue, income):
            a, b = sales['observation'], profit['observation']
            if (not isinstance(sales['label'], str) or not 1 <= len(sales['label']) <= 80
                    or sales['label'] != profit['label'] or sales['column'] != profit['column']
                    or type(sales['column']) is not int or not 2 <= sales['column'] < 50
                    or a['dimensions'] != b['dimensions'] or a['start'] != b['start']
                    or a['end'] != b['end'] or a['end'] != proof['period_end']
                    or a['concept'] not in CONCEPTS[:2] or b['concept'] != CONCEPTS[2]
                    or sales['label'] in seen or a['dimensions'] in [r['dimensions'] for r in rows]):
                return None
            for metric, entry, concept in [('revenue', sales, a), ('operating_income', profit, b)]:
                row = proof['metrics'][metric]
                cells = row['cells']
                column = entry['column']
                if (len(cells) != len(proof['headers']) or column >= len(cells) - 1
                        or entry['label'] != proof['headers'][column]
                        or cells[column]['fact_ids'] != [concept['fact_id']]
                        or concept['scale'] != 3
                        or cells[column - 1]['text'] not in {'', '$'}
                        or cells[column + 1]['text'] != (')' if concept['sign'] == '-' else '')
                        or cells[0]['text'] != {'revenue': 'External net sales', 'operating_income': 'Operating profit (loss)'}[metric]):
                    return None
                expected = ('(' if concept['sign'] == '-' else '') + concept['literal']
                if cells[column]['text'] != expected or (concept['sign'] == '-' and cells[column + 1]['text'] != ')'):
                    return None
                # Recreate the visible row after adjacent colspan copies collapse.
                visible = []
                for cell in cells:
                    if not visible or cell != visible[-1]:
                        visible.append(cell)
                if row['row_text'] != clean(' '.join(cell['text'] for cell in visible)):
                    return None
            av, bv = amount(a, cik=cik), amount(b, cik=cik)
            if av is None or bv is None or av < 0:
                return None
            seen.add(sales['label'])
            rows.append({'label': sales['label'], 'start': a['start'], 'end': a['end'],
                         'revenue_usd': av, 'operating_income_usd': bv, 'dimensions': a['dimensions']})
        allocation_label = ALLOCATION.fullmatch(proof['allocation'])['label']
        if clean(allocation_label).replace(' / ', '/') not in {r['label'].replace(' / ', '/') for r in rows}:
            return None
        return rows
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
