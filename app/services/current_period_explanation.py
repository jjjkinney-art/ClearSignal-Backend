"""Latest-period change explanations, bound to the same filing's own figures.

Two kinds of evidence, both from the latest periodic report already retrieved
for filing metrics (no additional request):

* A reported earnings bridge. When net income and operating income move in
  opposite directions, or the change in non-operating income (expense)
  exceeds the change in operating income, the filing's consolidated inline
  XBRL facts show where the difference sits (non-operating income (expense)
  and income tax). This is
  component arithmetic that must reconcile exactly; it identifies where the
  change sits, not why.
* Management's own statements. A sentence is admitted only if the change or
  level it states reconciles, at the sentence's stated precision, with a
  verified comparison from the same filing, or, when it states no reconcilable
  figure, names the current period explicitly and agrees in direction. A
  sentence that states a cause is preferred over one that only repeats
  figures. Segment, region or brand attributions are admitted only when they
  name the current period and state a cause, and are labelled as such. The
  quotes are management's attributions, never established causes.

Nothing here is issuer-specific; anything that does not reconcile is omitted.
"""
from datetime import date
from decimal import Decimal
import json
import re

from ..integrity.provenance import ClaimDocumentReference
from ..providers.sec_inline_facts import validated_observation
from ..schemas import RetrievedEvidence

SECTION = 'Latest periodic report - results discussion'
BRIDGE_CONCEPTS = ('OperatingIncomeLoss', 'NonoperatingIncomeExpense', 'IncomeTaxExpenseBenefit', 'NetIncomeLoss')
# Reported separately by some issuers inside total non-operating income.
OTHER_NONOPERATING = 'OtherNonoperatingIncomeExpense'
EXPLANATION_CONCEPTS = (*BRIDGE_CONCEPTS, OTHER_NONOPERATING)
METRIC_WORDS = {
    'revenue': r'\b(?:net sales|total revenues|revenues?)\b',
    'operating income': r'(?:\boperating (?:income|profit)\b(?! margin)|\b(?:income|loss) from operations\b)',
    'net income': r'\bnet (?:income|earnings)\b',
    # Total non-operating income (us-gaap:NonoperatingIncomeExpense); many
    # issuers present it as "other income (expense), net" or "OI&E".
    'non-operating income (expense)': r'(?:\bOI&E\b|\bother income \(expense\), net\b'
                                      r'|\b(?:total )?non-?operating income(?: \(expense\))?)',
    # The separately reported line item inside it, when an issuer has one.
    'other income (expense), net': r'\bother income \(expense\), net\b',
    'operating margin': r'\boperating (?:profit |income )?margin\b',
}
# Direction-only: margins are stated in basis points or percentages, never amounts.
DIRECTION_ONLY = {'operating margin'}
_QUARTER_NAMES = {3: 'first', 6: 'second', 9: 'third', 12: 'fourth'}
_OPENER = re.compile(r'(?:During|The|Our|We|In|For|On|As|Net|Total|Operating|Revenues?|Sales|Other|Income)\b')
_HEADING_PREFIX = re.compile(r'(?:[A-Z0-9(][A-Za-z0-9&/\-(),.]*\s+){1,8}')
_SCOPE = re.compile(
    r'\b(?:segments?|regions?|brands?|divisions?)\b'
    r'|\b(?:in|for) (?:the |our )?(?!(?:first|second|third|fourth|three|six|nine|twelve|Q[1-4])\b)[A-Z][A-Za-z&.\-–/]+'
    r'|\b(?!(?:The|Our|We|In|During|For|Consolidated|Total|Net|Operating)\b)[A-Z][A-Za-z&.\-–/]+'
    r'(?:\s+[A-Z][A-Za-z&.\-–/]+)*\s+(?:segment\s+)?(?:net sales|revenues?|operating (?:income|profit))\b')
# A sentence that explains the change stated just before it: "The decrease resulted primarily from …".
_ANAPHOR = re.compile(r'(?:The|This|These|That) (?:(?:net|overall|year-over-year) )?'
                      r'(increases?|decreases?|declines?|improvements?|reductions?|growth|changes?|deteriorations?)\b')
_OTHER_PERIOD = re.compile(r'\b(?:six|nine|twelve) months\b|\byear[- ]to[- ]date\b|\bfirst (?:half|nine months)\b'
                           r'|\bfull[- ]year\b|\bfiscal\b|\bannual\b|\b(?:19|20)\d{2}\b', re.I)
_PCT_LEVELS = re.compile(
    r'\b(increased|decreased)\s+(\d+(?:\.\d+)?)\s?(?:%|percent)\s+to\s+\$\s?([\d,]+(?:\.\d+)?)(?:\s*(thousand|million|billion))?\b'
    r'.{0,120}?\b(?:from|compared (?:to|with))\s+\$\s?([\d,]+(?:\.\d+)?)(?:\s*(thousand|million|billion))?', re.I)
# A segment table for one period: an upper-case heading, the period, then rows of
# current, prior and change ("MOBILE SOLUTIONS Three Months Ended September 30, 2026
# 2025 $ Change Net sales $ 68,177 $ 59,117 $ 9,060 …").
_TABLE_HEADING = re.compile(
    r'\b([A-Z][A-Z&/\-–]+(?: [A-Z][A-Z&/\-–]+){0,4}) (Three|Six|Nine|Twelve) Months Ended '
    r'((?:January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2}, \d{4})')
_TABLE_HEADER = re.compile(r'\s*(?:\d{4}\s+){1,2}(?:\$|%)?\s*Change\s+')
_TABLE_ROW = re.compile(r'\s*([A-Z][a-z][A-Za-z ,&\-]*?) \$ ?(\(?[\d,]+\)?) \$ ?(\(?[\d,]+\)?) \$ ?(\(?[\d,]+\)?)')
_TABLE_NARRATIVE = re.compile(r'([A-Z][a-z][A-Za-z ,&\-]*?) (increased|decreased) by \$ ?([\d,]+(?:\.\d+)?)'
                              r'(?:\s*(thousand|million|billion))?\b')
MAX_TABLE_CHARS = 3000
_UP = {'increased', 'rose', 'grew', 'an increase'}
_CHANGE = re.compile(r'\b(increased|decreased|rose|fell|declined|grew|an increase|a decrease)\b', re.I)
_CAUSE = re.compile(r'\b(?:primarily|reflecting|due to|driven by|attributable to|as a result of|resulting from)\b', re.I)
_MONEY = re.compile(r'\$\s?((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(?:\s*(thousand|million|billion)\b)?', re.I)
def cause_match(sentence):
    """The first causal connective, ignoring ownership labels such as
    "net income attributable to <parent>"."""
    for match in _CAUSE.finditer(sentence):
        if match.group(0).lower() == 'attributable to' and re.search(
                r'(?:income|loss|earnings|EPS|shares?)\s*$', sentence[:match.start()], re.I):
            continue
        return match
    return None


_PERCENT = re.compile(r'(\d+(?:\.\d+)?)\s?(?:%|percent\b)', re.I)
_SCALE = {None: 1, 'thousand': 10 ** 3, 'million': 10 ** 6, 'billion': 10 ** 9}
_COMPONENT = re.compile(r'\b(increased|decreased) by \$\s?([\d,]+(?:\.\d+)?)(?:\s*(thousand|million|billion))?\s+'
                        r'from \$\s?([\d,]+(?:\.\d+)?)(?:\s*(?:thousand|million|billion))?\s+'
                        r'to \$\s?([\d,]+(?:\.\d+)?)', re.I)
MAX_SENTENCE = 600
MAX_COMPONENTS = 3


_BOUNDARY = re.compile(r'[.!?](?=\s+[A-Z0-9("“•]|\s*$)')


def sentences(text):
    """(offset, sentence) pairs. A boundary is terminal punctuation followed by
    whitespace and a capital or digit, so a decimal such as $21.0 billion never
    splits. Byte-order marks count as spaces (same length, offsets unchanged)."""
    text = text.replace('\ufeff', ' ')
    start = 0
    for match in _BOUNDARY.finditer(text):
        chunk = text[start:match.end()]
        sentence = chunk.strip()
        if sentence:
            yield start + len(chunk) - len(chunk.lstrip()), sentence
        start = match.end()


def _amounts(fragment):
    """Stated USD amounts with the half-unit precision the text implies."""
    values = []
    for match in _MONEY.finditer(fragment):
        number, scale = match.group(1).replace(',', ''), _SCALE[(match.group(2) or '').lower() or None]
        decimals = len(number.split('.')[1]) if '.' in number else 0
        values.append((Decimal(number) * scale, Decimal(scale) / (2 * 10 ** decimals)))
    return values


def _close(stated, half, target):
    return abs(stated - abs(Decimal(target))) <= half + Decimal('0.5')


def current_period_patterns(period):
    """How a filing names the current period: quarters and fiscal years only."""
    start, end = date.fromisoformat(period['current_start']), date.fromisoformat(period['current_end'])
    month, days = end.strftime('%B'), (end - start).days
    ended = rf'{month}\s+{end.day},?\s+{end.year}'
    if 80 <= days <= 100:
        patterns = [rf'three months ended {ended}', rf'quarter ended {ended}']
        calendar = start.day == 1 and start.month == end.month - 2 and end.month in _QUARTER_NAMES \
            and (end.month == 12 or date(end.year, end.month + 1, 1).toordinal() - 1 == end.toordinal())
        if calendar:
            name = _QUARTER_NAMES[end.month]
            patterns += [rf'\b{name}[- ]quarter(?: of)? {end.year}\b', rf'\bQ{end.month // 3} {end.year}\b']
    elif 350 <= days <= 380:
        patterns = [rf'(?:fiscal )?year ended {ended}', rf'\bfiscal(?: year)? {end.year}\b']
    else:
        return []
    return [re.compile(pattern, re.I) for pattern in patterns]


def names_current_period(sentence, period):
    return any(pattern.search(sentence) for pattern in current_period_patterns(period))


_CUMULATIVE = re.compile(r'\b(?:six|nine|twelve) months ended\b|\byear-to-date\b|\bfirst (?:half|nine months)\b'
                         r'|\btrailing twelve months\b', re.I)


def defines_levels(sentence, metrics, period):
    """A sentence that names a metric and states its current and prior levels
    for the current period ("Other income (expense), net was $1.1 billion and
    $53.4 billion during Q2 2025 and Q2 2026")."""
    if len(sentence) > MAX_SENTENCE or not names_current_period(sentence, period):
        return None
    amounts = _amounts(sentence)
    found = [name for name, metric in metrics.items() if name not in DIRECTION_ONLY
             and re.search(METRIC_WORDS[name], sentence, re.I)
             and any(_close(v, h, metric['current']) for v, h in amounts)
             and any(_close(v, h, metric['prior']) for v, h in amounts)]
    return found[0] if len(found) == 1 else None


def bind_attribution(sentence, metrics, period, defined=None):
    """A causal sentence for the current period that does not restate a change.

    Either it states the current-period amount of exactly one metric, or the
    metric is its subject and its direction matches the reported figures. Any
    amount it states must reconcile with that metric.
    """
    if len(sentence) > MAX_SENTENCE or not cause_match(sentence) or not names_current_period(sentence, period):
        return None
    amounts = _amounts(sentence)
    matched = [name for name, metric in metrics.items() if name not in DIRECTION_ONLY
               and any(_close(value, half, metric['current']) for value, half in amounts)]
    if len(matched) > 1 and defined in matched:
        # Two line items agree at the stated precision; the filing's own
        # preceding definition of the current and prior levels decides.
        matched = [defined]
    if len(matched) == 1:
        metric = metrics[matched[0]]
        if all(any(_close(value, half, target) for target in
                   (metric['current'], metric['prior'], metric['current'] - metric['prior']))
               for value, half in amounts) or _CUMULATIVE.search(sentence):
            return {'metric': matched[0], 'basis': 'stated period amount with attribution'}
    for name, metric in metrics.items():
        subject = re.match(r'(?:the |our )?' + METRIC_WORDS[name], sentence, re.I)
        if not subject:
            continue
        verb = _CHANGE.search(sentence, subject.end(), subject.end() + 80)
        delta = metric['current'] - metric['prior']
        if not verb or delta == 0 or (verb.group(1).lower() in _UP) != (delta > 0):
            continue
        if name in DIRECTION_ONLY and amounts:
            continue
        if name not in DIRECTION_ONLY and not all(
                any(_close(value, half, target) for target in (metric['current'], metric['prior'], delta))
                for value, half in amounts):
            continue
        return {'metric': name, 'basis': 'period-matched attribution'}
    return None


def stated_direction(sentence):
    verb = re.search(r'\b(increased|decreased|rose|fell|declined|grew|improved|an increase|a decrease)\b', sentence, re.I)
    if not verb:
        return None
    return 'up' if verb.group(1).lower() in ('increased', 'rose', 'grew', 'improved', 'an increase') else 'down'


def following_cause(sentence, following, period):
    """Whether the next sentence explains this sentence's own stated change.

    Only the immediately following sentence; it must open by referring back
    ("The decrease …"), agree in direction, state a cause, introduce no new
    segment or region before the cause, and name no other period.
    """
    if not following or len(following) > MAX_SENTENCE or cause_match(sentence):
        return False
    anaphor, cause = _ANAPHOR.match(following), cause_match(following)
    direction = stated_direction(sentence)
    if not anaphor or not cause or cause.start() < anaphor.end() or direction is None:
        return False
    word = anaphor.group(1).lower()
    if word.startswith(('increase', 'improvement', 'growth')) and direction != 'up':
        return False
    if word.startswith(('decrease', 'decline', 'reduction', 'deterioration')) and direction != 'down':
        return False
    if _SCOPE.search(following[anaphor.end():cause.start()]):
        return False
    return not (_OTHER_PERIOD.search(following) and not names_current_period(following, period))


def internally_consistent(sentence):
    """The sentence's own figures agree: 'by $X from $A to $B', or 'N percent to $A … from $B'."""
    if _COMPONENT.search(sentence):
        return _component_figures(sentence)
    match = _PCT_LEVELS.search(sentence)
    if not match:
        return False
    current = Decimal(match.group(3).replace(',', '')) * _SCALE[(match.group(4) or '').lower() or None]
    prior = Decimal(match.group(5).replace(',', '')) * _SCALE[(match.group(6) or '').lower() or None]
    if prior <= 0 or current == prior or (current > prior) != (match.group(1).lower() == 'increased'):
        return False
    # Stated percentages and levels are both rounded.
    return abs(abs(current - prior) / prior * 100 - Decimal(match.group(2))) <= Decimal('1.0')


def segment_attribution(sentence, metrics, period, following=None):
    """A cause management gives for a named segment, region or brand this period,
    in the sentence itself or in the next sentence when its own figures agree."""
    cause = cause_match(sentence)
    if cause is None and not (following_cause(sentence, following, period) and internally_consistent(sentence)):
        return False
    head = sentence[:cause.start()] if cause else sentence
    return (len(sentence) <= MAX_SENTENCE and names_current_period(sentence, period)
            and _SCOPE.search(head) is not None
            and re.search(r'\b(?:increase[ds]?|decrease[ds]?|rose|fell|declined|grew|growth|decline)\b', sentence, re.I) is not None
            and re.search(r'(?<!cost of )(?<!costs of )(?:' + METRIC_WORDS['revenue'] + '|' + METRIC_WORDS['operating income']
                          + r'|\bsales\b)', head, re.I) is not None
            and bind_statement(sentence, metrics) is None
            and (not _COMPONENT.search(sentence) or _component_figures(sentence)))


def _table_number(cell):
    number = int(cell.strip('()').replace(',', ''))
    return -number if cell.startswith('(') else number


def table_blocks(text, period):
    """Segment tables for exactly the current quarter, with their narrative span."""
    blocks, headings = [], list(_TABLE_HEADING.finditer(text))
    for index, heading in enumerate(headings):
        if heading.group(2) != 'Three' or not names_current_period(f'three months ended {heading.group(3)}', period):
            continue
        end = min(headings[index + 1].start() if index + 1 < len(headings) else len(text),
                  heading.end() + MAX_TABLE_CHARS)
        position = heading.end()
        header = _TABLE_HEADER.match(text, position)
        if header:
            position = header.end()
        rows = {}
        while (row := _TABLE_ROW.match(text, position)) and row.end() <= end:
            rows[row.group(1).strip().lower()] = tuple(_table_number(row.group(k)) for k in (2, 3, 4))
            position = row.end()
        if rows:
            blocks.append({'heading': heading.group(1), 'start': heading.start(), 'rows_end': position,
                           'end': end, 'rows': rows})
    return blocks


def table_scoped(sentence, block, period, following=None):
    """A narrative sentence whose stated change is the change column of a row
    of this segment's current-quarter table, at exactly one unit scale."""
    match = _TABLE_NARRATIVE.match(sentence)
    if (not match or len(sentence) > MAX_SENTENCE or not names_current_period(sentence, period)
            or match.group(1).strip().lower() not in block['rows']):
        return False
    change = abs(block['rows'][match.group(1).strip().lower()][2])
    number = match.group(3).replace(',', '')
    stated = Decimal(number) * _SCALE[(match.group(4) or '').lower() or None]
    half = Decimal(_SCALE[(match.group(4) or '').lower() or None]) / (2 * 10 ** (len(number.split('.')[1]) if '.' in number else 0))
    scales = [scale for scale in (1, 10 ** 3, 10 ** 6) if abs(stated - change * scale) <= half]
    if len(scales) != 1 or not change:
        return False
    return cause_match(sentence) is not None or following_cause(sentence, following, period)


def bind_statement(sentence, metrics):
    """The metric and basis a management sentence reconciles with, or None."""
    if len(sentence) > MAX_SENTENCE:
        return None
    for name, metric in metrics.items():
        word = re.search(METRIC_WORDS[name], sentence, re.I)
        if not word or name in DIRECTION_ONLY:
            continue
        verb = _CHANGE.search(sentence, word.end(), word.end() + 160)
        if not verb:
            continue
        delta = metric['current'] - metric['prior']
        up = verb.group(1).lower() in _UP
        if delta == 0 or up != (delta > 0):
            continue
        after = sentence[verb.start():verb.start() + 200]
        if any(_close(value, half, delta) for value, half in _amounts(after)):
            return {'metric': name, 'basis': 'stated change'}
        stated = _amounts(sentence[word.start():verb.start() + 200])
        if (any(_close(value, half, metric['current']) for value, half in stated)
                and any(_close(value, half, metric['prior']) for value, half in stated)
                and metric['current'] != metric['prior']):
            return {'metric': name, 'basis': 'stated current and prior levels'}
        if metric['prior'] > 0:
            growth = abs(Decimal(delta)) / Decimal(metric['prior']) * 100
            stated_levels = _amounts(sentence[word.start():verb.start() + 200])
            percents = [Decimal(p) for p in _PERCENT.findall(after)]
            if (any(_close(value, half, metric['current']) for value, half in stated_levels)
                    and any(abs(p - growth) <= Decimal('0.5') for p in percents)):
                return {'metric': name, 'basis': 'stated level and growth rate'}
    return None


def clause_starts(sentence):
    """Where a quotable statement may begin: the sentence itself, or, after table
    text with no full stop, a capitalised metric phrase close enough to the end."""
    # A heading or page marker run into the sentence ("Third Quarter Results Net
    # sales …", "Google Cloud Google Cloud revenues …", "24 PART 1 During …"):
    # quote from the real sentence start when the remainder repeats the heading
    # or opens like a sentence.
    trimmed = None
    for match in re.finditer(r'(?<=\s)[A-Z][a-z]', sentence[:120]):
        prefix, rest = sentence[:match.start()], sentence[match.start():]
        if (_HEADING_PREFIX.fullmatch(prefix) and not re.search(r'(?:^|\s)[a-z]', prefix)
                and (rest.lower().startswith(prefix.strip().lower() + ' ') or _OPENER.match(rest))):
            trimmed = match.start()  # the latest break wins: the whole heading is removed
    if trimmed is not None:
        yield trimmed
    yield 0
    if len(sentence) <= MAX_SENTENCE:
        return
    starts = sorted({m.start() for words in METRIC_WORDS.values()
                     for m in re.finditer(words, sentence) if sentence[m.start()].isupper()})
    for start in starts:
        if len(sentence) - start <= MAX_SENTENCE:
            yield start


def consistent_component(sentence):
    """A sentence whose own 'by $X from $A to $B' figures agree, with a stated cause."""
    return len(sentence) <= MAX_SENTENCE and cause_match(sentence) is not None and _component_figures(sentence)


def _component_figures(sentence):
    match = _COMPONENT.search(sentence)
    if not match:
        return False
    scale = _SCALE[(match.group(3) or '').lower() or None]
    change, start, end = (Decimal(match.group(i).replace(',', '')) for i in (2, 4, 5))
    up = match.group(1).lower() == 'increased'
    return change * scale > 0 and (end - start == change if up else start - end == change)


def earnings_bridge(observations, current, prior):
    """Exact component arithmetic when net income and operating income diverge."""
    values = {}
    for period_name, (start, end) in (('current', current), ('prior', prior)):
        for concept in BRIDGE_CONCEPTS:
            found = {amount for amount, row in observations
                     if row['concept'] == concept and row['start'] == start and row['end'] == end}
            if len(found) != 1:
                return None
            values[period_name, concept] = found.pop()
    deltas = {c: values['current', c] - values['prior', c] for c in BRIDGE_CONCEPTS}
    if not deltas['NetIncomeLoss'] or not (
            (deltas['OperatingIncomeLoss'] and (deltas['NetIncomeLoss'] > 0) != (deltas['OperatingIncomeLoss'] > 0))
            or abs(deltas['NonoperatingIncomeExpense']) > abs(deltas['OperatingIncomeLoss'])):
        return None
    residuals = {p: values[p, 'NetIncomeLoss'] - (values[p, 'OperatingIncomeLoss']
                 + values[p, 'NonoperatingIncomeExpense'] - values[p, 'IncomeTaxExpenseBenefit'])
                 for p in ('current', 'prior')}
    return {'values': {f'{p}:{c}': values[p, c] for p, c in values}, 'deltas': deltas,
            'other_items': residuals}


def _billions_or_millions(amount):
    amount = Decimal(amount)
    if abs(amount) >= 10 ** 9:
        return f"{'-' if amount < 0 else ''}${abs(amount) / 10 ** 9:,.1f}B"
    return f"{'-' if amount < 0 else ''}${abs(amount) / 10 ** 6:,.1f}M"


def render(value):
    period = value['period']
    lines = [f"Latest reported period {period['current_start']} to {period['current_end']} versus "
             f"{period['prior_start']} to {period['prior_end']} ({value['document_type']} filed {value['filed_at']})."]
    bridge = value.get('bridge')
    if bridge:
        d, v = bridge['deltas'], bridge['values']
        text = (f"Net income moved {_billions_or_millions(d['NetIncomeLoss'])} while operating income moved "
                f"{_billions_or_millions(d['OperatingIncomeLoss'])}: non-operating income (expense) went from "
                f"{_billions_or_millions(v['prior:NonoperatingIncomeExpense'])} to "
                f"{_billions_or_millions(v['current:NonoperatingIncomeExpense'])} "
                f"({_billions_or_millions(d['NonoperatingIncomeExpense'])}), and income tax expense moved "
                f"{_billions_or_millions(d['IncomeTaxExpenseBenefit'])}.")
        if any(bridge['other_items'].values()):
            text += (f" Other reconciling items were {_billions_or_millions(bridge['other_items']['prior'])} and "
                     f"{_billions_or_millions(bridge['other_items']['current'])}.")
        lines.append(text + ' This is the filing\'s own consolidated arithmetic; it shows where the change sits, not why.')
    for statement in value['statements'] + value['components']:
        scope = (', for the segment, region or brand it names'
                 if statement['basis'] == 'period-matched segment attribution' else
                 f", for the segment its table is headed “{statement['scope_heading']}”"
                 if statement['basis'] == 'table-scoped segment attribution' else '')
        context = f"“{statement['context_quote']}” and " if statement.get('context_quote') else ''
        cause = f" and “{statement['cause_quote']}”" if statement.get('cause_quote') else ''
        lines.append(f"Management stated{scope}: {context}“{statement['quote']}”{cause}")
    if not any(stated_cause(row) for row in value['statements'] + value['components']):
        lines.append('The filing states no cause for these changes in this period; their drivers remain unverified.')
    elif value['statements'] or value['components']:
        lines.append('Attributions in quotation marks are management\'s; they are not independently established causes.')
    return ' '.join(lines)


def _cause(sentence):
    match = cause_match(sentence)
    return sentence[match.start():].rstrip(' .') if match else None


def stated_cause(row):
    return _cause(row['quote']) or (_cause(row['cause_quote']) if row.get('cause_quote') else None)


def monitoring_criteria(value):
    """Follow-up tests taken only from the bound explanation: management's own
    stated drivers and figures, and the filing's bridge. No thresholds beyond
    the reported amounts, and no causes beyond what management attributed."""
    criteria = []
    bridge = value.get('bridge')
    if bridge:
        v = bridge['values']
        criteria.append(
            f"Non-operating income (expense): {_billions_or_millions(v['current:NonoperatingIncomeExpense'])} versus "
            f"{_billions_or_millions(v['prior:NonoperatingIncomeExpense'])} for the same period a year earlier. "
            + ("It moved net income opposite to operating income this period"
               if bridge['deltas']['OperatingIncomeLoss'] and (bridge['deltas']['NetIncomeLoss'] > 0)
               != (bridge['deltas']['OperatingIncomeLoss'] > 0)
               else "Its change exceeded the change in operating income this period")
            + "; later filings show whether that recurs.")
    for statement in value['statements']:
        cause = stated_cause(statement)
        if cause:
            criteria.append(f"{statement['metric'][0].upper()}{statement['metric'][1:]}, management's stated reason: "
                            f"“{cause}”. Later filings' year-over-year explanations show whether management "
                            "reports the same driver.")
    for component in value['components']:
        if component['basis'] in ('period-matched segment attribution', 'table-scoped segment attribution'):
            cause = cause_match(component['quote'])
            stated = component['quote'][:cause.start()] if cause else component['quote']
            scope = (f"{component['scope_heading']} (segment table): "
                     if component['basis'] == 'table-scoped segment attribution' else '')
            criteria.append(f"{scope}{stated.rstrip(' ,;.')}; management's stated reason: “{stated_cause(component)}”. "
                            "Later filings' year-over-year explanations show whether this persists.")
            continue
        match = _COMPONENT.search(component['quote'])
        label = component['quote'][:match.start()].strip()
        cause = _cause(component['quote'][match.end():])
        if not cause or not re.fullmatch(r"[A-Za-z][A-Za-z/&' -]{2,80}", label):
            continue
        criteria.append(f"{label}: ${match.group(5).rstrip(',')} versus ${match.group(4).rstrip(',')} for the "
                        f"same period a year earlier; management's stated reason: “{cause}”. Compare the figure "
                        "for the corresponding period one year later, not the next quarter; later filings' "
                        "stated reasons show whether this persists.")
    return criteria[:4]


def _metrics(filing_items):
    """Current/prior values from the same filing's verified comparisons."""
    names = {'us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax': 'revenue', 'us-gaap:Revenues': 'revenue',
             'us-gaap:OperatingIncomeLoss': 'operating income', 'us-gaap:NetIncomeLoss': 'net income'}
    metrics, period = {}, None
    for item in filing_items:
        claims = getattr(item, 'verified_claims', None) or []
        if len(claims) != 2 or claims[0]['metric'] not in names:
            continue
        current, prior = claims
        this = (current['period_start'], current['period_end'], prior['period_start'], prior['period_end'])
        if period is not None and this != period:
            continue
        period = this
        metrics[names[current['metric']]] = {'current': int(current['raw_value']), 'prior': int(prior['raw_value'])}
    return metrics, period


def definition_quote(all_sentences, index, metric, metrics, period):
    for _, sentence in reversed(all_sentences[max(0, index - 5):index]):
        for start in clause_starts(sentence):
            if defines_levels(sentence[start:], metrics, period) == metric:
                return sentence[start:]
    raise ValueError('definition not found')


def explanation_value(text, observations, filing_items, *, ticker, document_type, filed_at):
    metrics, period = _metrics(filing_items)
    if not period or 'revenue' not in metrics:
        return None
    current, prior = (period[0], period[1]), (period[2], period[3])
    period_value = {'current_start': current[0], 'current_end': current[1],
                    'prior_start': prior[0], 'prior_end': prior[1]}
    bridge = earnings_bridge(observations, current, prior)
    if bridge:
        v = bridge['values']
        total = {'current': v['current:NonoperatingIncomeExpense'], 'prior': v['prior:NonoperatingIncomeExpense']}
        other = {}
        for key, (start, end) in (('current', current), ('prior', prior)):
            found = {amount for amount, row in observations
                     if row['concept'] == OTHER_NONOPERATING and row['start'] == start and row['end'] == end}
            if len(found) == 1:
                other[key] = found.pop()
        metrics['non-operating income (expense)'] = total
        if len(other) == 2 and other != total:
            # Reported separately inside the total; a sentence binds to it only
            # when its figures reconcile with this line and not the total.
            metrics['other income (expense), net'] = other
    if 'operating income' in metrics and metrics['revenue']['current'] > 0 and metrics['revenue']['prior'] > 0:
        # Basis points; used only for direction, never reconciled against stated amounts.
        metrics['operating margin'] = {key: int(round(Decimal(metrics['operating income'][key]) * 10000
                                                      / Decimal(metrics['revenue'][key]))) for key in ('current', 'prior')}
    candidates, components, anchor, used = {}, [], None, set()
    all_sentences = list(sentences(text))
    blocks = table_blocks(text, period_value)
    definition = None
    for index, (offset, sentence) in enumerate(all_sentences):
        following = all_sentences[index + 1][1] if index + 1 < len(all_sentences) else None
        if any(block['start'] <= offset < block['end'] for block in blocks):
            continue  # inside a segment table's discussion: never a consolidated statement
        binding = None
        defined = definition[0] if definition and index - definition[1] <= 5 else None
        for start in clause_starts(sentence):
            quote = sentence[start:]
            binding = (bind_statement(quote, metrics)
                       or bind_attribution(quote, metrics, period_value, defined=defined))
            if binding:
                break
        for start in clause_starts(sentence):
            if defines_levels(sentence[start:], metrics, period_value):
                definition = (defines_levels(sentence[start:], metrics, period_value), index)
                break
        if not binding:
            continue
        if (binding['basis'] == 'stated period amount with attribution' and defined
                and bind_attribution(quote, metrics, period_value) is None):
            binding['context_quote'] = definition_quote(all_sentences, index, defined, metrics, period_value)
        if binding['metric'] == 'revenue' and anchor is None:
            anchor = index
        if following_cause(quote, following, period_value):
            binding['cause_quote'] = following
        # Prefer a stated cause, then figures that reconcile, then document order.
        rank = (cause_match(quote) is None and 'cause_quote' not in binding,
                binding['basis'] == 'period-matched attribution', offset)
        candidates.setdefault(binding['metric'], []).append(
            (rank, {'quote': quote, 'start_offset': offset + start, **binding}))
    statements = sorted((min(rows, key=lambda row: row[0])[1] for rows in candidates.values()),
                        key=lambda statement: statement['start_offset'])
    used = {statement['start_offset'] for statement in statements}
    if anchor is not None:
        for offset, sentence in all_sentences[anchor + 1:anchor + 12]:
            if re.search(r'\bconsolidated\b', sentence, re.I):
                break  # the next period's discussion begins
            if consistent_component(sentence) and len(components) < MAX_COMPONENTS:
                components.append({'quote': sentence, 'start_offset': offset, 'basis': 'internally consistent component'})
                used.add(offset)
    scoped = []
    for block in blocks:
        narrative = list(sentences(text[block['rows_end']:block['end']]))
        for index, (offset, sentence) in enumerate(narrative):
            following = narrative[index + 1][1] if index + 1 < len(narrative) else None
            if table_scoped(sentence, block, period_value, following):
                scoped.append({'quote': sentence, 'start_offset': block['rows_end'] + offset,
                               'basis': 'table-scoped segment attribution', 'scope_heading': block['heading'],
                               'table_quote': text[block['start']:block['rows_end']].strip(),
                               **({} if cause_match(sentence) else {'cause_quote': following})})
    for index, (offset, sentence) in enumerate(all_sentences):
        following = all_sentences[index + 1][1] if index + 1 < len(all_sentences) else None
        if any(block['start'] <= offset < block['end'] for block in blocks):
            continue
        for start in clause_starts(sentence):
            quote = sentence[start:]
            if (offset + start not in used and offset not in used
                    and segment_attribution(quote, metrics, period_value, following)):
                scoped.append({'quote': quote, 'start_offset': offset + start,
                               'basis': 'period-matched segment attribution',
                               **({} if cause_match(quote) else {'cause_quote': following})})
                used.add(offset + start)
                break
    # Segment explanations of a consolidated metric that has no explanation of
    # its own come first; then document order.
    explained = {statement['metric'] for statement in statements if stated_cause(statement)}
    unexplained = [name for name in ('operating income', 'revenue') if name in metrics and name not in explained]

    def priority(row):
        head = row['quote'][:cause_match(row['quote']).start()] if cause_match(row['quote']) else row['quote']
        names = [name for name in unexplained if re.search(METRIC_WORDS[name] + (r'|\bsales\b' if name == 'revenue' else ''), head, re.I)]
        return (not names, row['start_offset'])
    components += sorted(scoped, key=priority)[:max(0, MAX_COMPONENTS - len(components))]
    components.sort(key=lambda row: row['start_offset'])
    if not statements and not bridge and not components:
        return None
    value = {'claim_kind': 'issuer_current_period_explanation', 'ticker': ticker,
             'document_type': document_type, 'filed_at': filed_at,
             'period': period_value, 'metrics': metrics, 'bridge': bridge,
             'statements': statements, 'components': components}
    return json.loads(json.dumps(value, default=int))


def extract_current_period_explanation(document, filing_items, *, ticker, cik):
    from .thesis_disclosures import _business_issuer_url
    if (document.document_type not in {'10-K', '10-Q', '10-K/A', '10-Q/A'} or document.publisher != 'SEC EDGAR'
            or document.source_type != 'regulatory_filing' or document.source_tier != 'primary'
            or document.extraction_method != 'html' or not getattr(document, 'text', '')
            or not _business_issuer_url(document.final_url, cik)):
        return []
    try:
        observations = [(amount, row) for row in document.inline_xbrl_facts
                        if (amount := validated_observation(row, cik=cik, concepts=EXPLANATION_CONCEPTS)) is not None]
        value = explanation_value(document.text, observations, filing_items, ticker=ticker,
                                  document_type=document.document_type, filed_at=document.published_at)
        if value is None or not date.fromisoformat(value['period']['current_end']) <= date.fromisoformat(document.published_at) <= date.today():
            return []
        # The reference anchors one bound statement; every other quote is
        # rechecked from the stored value, never shortened to fit.
        anchor = (value['statements'] or value['components'] or [{'quote': 'consolidated inline XBRL facts'}])[0]['quote']
        value['document_ref'] = ClaimDocumentReference(
            reference_id=f'document:{document.content_hash}:current_period_explanation',
            title=document.title or f'{ticker} {document.document_type}', provider='SEC EDGAR',
            url=document.final_url, published_at=document.published_at, section=SECTION,
            content_hash=document.content_hash, quote=anchor).to_dict()
        item = RetrievedEvidence(
            title=f'{ticker} latest-period change explanation', source='SEC EDGAR', summary=render(value),
            timestamp=document.published_at, url=document.final_url, relevance_score=0.97,
            source_type='regulatory_filing', source_tier='primary', claim_type='reported_fact',
            document_type=document.document_type, filed_at=document.published_at, section=SECTION,
            extraction_method='html', reporting_period_start=value['period']['current_start'],
            reporting_period_end=value['period']['current_end'], period_explanations=[value])
        return [item] if bound_current_period_explanation(item, ticker=ticker, cik=cik) else []
    except (KeyError, TypeError, ValueError, AttributeError, ArithmeticError):
        return []


def bound_current_period_explanation(item, *, ticker, cik):
    """Recheck every stored binding, the bridge identity and the rendering."""
    from .thesis_disclosures import _business_issuer_url
    values = getattr(item, 'period_explanations', [])
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        return None
    v = values[0]
    try:
        ref = ClaimDocumentReference(**v['document_ref']).to_dict()
        metrics = v['metrics']
        for statement in v['statements']:
            defined = None
            if 'context_quote' in statement:
                defined = defines_levels(statement['context_quote'], metrics, v['period'])
                if defined != statement['metric'] or bind_attribution(statement['quote'], metrics, v['period']):
                    return None
            binding = (bind_statement(statement['quote'], metrics)
                       or bind_attribution(statement['quote'], metrics, v['period'], defined=defined))
            if binding != {'metric': statement['metric'], 'basis': statement['basis']}:
                return None
            if 'cause_quote' in statement and not following_cause(statement['quote'], statement['cause_quote'], v['period']):
                return None
        for c in v['components']:
            following = c.get('cause_quote')
            if following is not None and cause_match(c['quote']):
                return None
            if c['basis'] == 'internally consistent component':
                valid = consistent_component(c['quote'])
            elif c['basis'] == 'period-matched segment attribution':
                valid = segment_attribution(c['quote'], metrics, v['period'], following)
            elif c['basis'] == 'table-scoped segment attribution':
                tables = table_blocks(c['table_quote'], v['period'])
                valid = (len(tables) == 1 and tables[0]['heading'] == c['scope_heading']
                         and c['table_quote'].startswith(c['scope_heading'])
                         and table_scoped(c['quote'], tables[0], v['period'], following))
            else:
                valid = False
            if not valid:
                return None
        bridge = v.get('bridge')
        if bridge:
            values_ = bridge['values']
            for concept in BRIDGE_CONCEPTS:
                if bridge['deltas'][concept] != values_[f'current:{concept}'] - values_[f'prior:{concept}']:
                    return None
            for period_name in ('current', 'prior'):
                if bridge['other_items'][period_name] != values_[f'{period_name}:NetIncomeLoss'] - (
                        values_[f'{period_name}:OperatingIncomeLoss'] + values_[f'{period_name}:NonoperatingIncomeExpense']
                        - values_[f'{period_name}:IncomeTaxExpenseBenefit']):
                    return None
        if (v['ticker'] != ticker or v['claim_kind'] != 'issuer_current_period_explanation'
                or not (v['statements'] or bridge or v['components']) or 'revenue' not in metrics
                or ref['provider'] != 'SEC EDGAR' or ref['url'] != item.url or not _business_issuer_url(item.url, cik)
                or not re.fullmatch(r'[0-9a-f]{64}', ref.get('content_hash', ''))
                or ref['reference_id'] != f'document:{ref["content_hash"]}:current_period_explanation'
                or ref.get('section') != SECTION or item.section != SECTION
                or ref['published_at'] != item.timestamp or item.filed_at != item.timestamp
                or v['filed_at'] != item.timestamp or v['document_type'] != item.document_type
                or item.reporting_period_start != v['period']['current_start']
                or item.reporting_period_end != v['period']['current_end']
                or not date.fromisoformat(item.reporting_period_end) <= date.fromisoformat(item.timestamp) <= date.today()
                or item.source != 'SEC EDGAR' or item.source_type != 'regulatory_filing' or item.source_tier != 'primary'
                or item.claim_type != 'reported_fact' or item.extraction_method != 'html'
                or item.availability_status != 'available'
                or item.freshness_status in {'stale', 'unavailable', 'conflicting', 'superseded'}
                or item.summary != render(v)):
            return None
        # The composer deduplicates bound disclosures by their anchored quote.
        return {**v, 'quote': ref['quote']}
    except (KeyError, TypeError, ValueError, AttributeError, ArithmeticError):
        return None
