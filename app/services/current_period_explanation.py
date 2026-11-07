"""Latest-period change explanations, bound to the same filing's own figures.

Two kinds of evidence, both from the latest periodic report already retrieved
for filing metrics (no additional request):

* A reported earnings bridge. When net income and operating income move in
  opposite directions, the filing's consolidated inline XBRL facts show where
  the difference sits (other income (expense), net and income tax). This is
  component arithmetic that must reconcile exactly; it identifies where the
  change sits, not why.
* Management's own statements. A sentence is admitted only if the change or
  level it states reconciles, at the sentence's stated precision, with a
  verified comparison from the same filing; nearby component sentences are
  admitted only if their own stated figures are internally consistent. The
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
METRIC_WORDS = {
    'revenue': r'\b(?:net sales|total revenues|revenues?)\b',
    'operating income': r'\boperating (?:income|profit)\b',
    'net income': r'\bnet (?:income|earnings)\b',
    'other income (expense), net': r'(?:\bOI&E\b|\bother income \(expense\), net\b)',
}
_UP = {'increased', 'rose', 'grew', 'an increase'}
_CHANGE = re.compile(r'\b(increased|decreased|rose|fell|declined|grew|an increase|a decrease)\b', re.I)
_CAUSE = re.compile(r'\b(?:primarily|reflecting|due to|driven by|attributable to|as a result of|resulting from)\b', re.I)
_MONEY = re.compile(r'\$\s?((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(?:\s*(thousand|million|billion)\b)?', re.I)
_PERCENT = re.compile(r'(\d+(?:\.\d+)?)\s?%')
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


def bind_statement(sentence, metrics):
    """The metric and basis a management sentence reconciles with, or None."""
    if len(sentence) > MAX_SENTENCE:
        return None
    for name, metric in metrics.items():
        word = re.search(METRIC_WORDS[name], sentence, re.I)
        if not word:
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
    if len(sentence) > MAX_SENTENCE or not _CAUSE.search(sentence):
        return False
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
    if not deltas['NetIncomeLoss'] or not deltas['OperatingIncomeLoss'] or \
            (deltas['NetIncomeLoss'] > 0) == (deltas['OperatingIncomeLoss'] > 0):
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
                f"{_billions_or_millions(d['OperatingIncomeLoss'])}: other income (expense), net went from "
                f"{_billions_or_millions(v['prior:NonoperatingIncomeExpense'])} to "
                f"{_billions_or_millions(v['current:NonoperatingIncomeExpense'])} "
                f"({_billions_or_millions(d['NonoperatingIncomeExpense'])}), and income tax expense moved "
                f"{_billions_or_millions(d['IncomeTaxExpenseBenefit'])}.")
        if any(bridge['other_items'].values()):
            text += (f" Other reconciling items were {_billions_or_millions(bridge['other_items']['prior'])} and "
                     f"{_billions_or_millions(bridge['other_items']['current'])}.")
        lines.append(text + ' This is the filing\'s own consolidated arithmetic; it shows where the change sits, not why.')
    for statement in value['statements'] + value['components']:
        lines.append(f"Management stated: “{statement['quote']}”")
    if value['statements'] or value['components']:
        lines.append('Attributions in quotation marks are management\'s; they are not independently established causes.')
    return ' '.join(lines)


def _cause(sentence):
    match = _CAUSE.search(sentence)
    return sentence[match.start():].rstrip(' .') if match else None


def monitoring_criteria(value):
    """Follow-up tests taken only from the bound explanation: management's own
    stated drivers and figures, and the filing's bridge. No thresholds beyond
    the reported amounts, and no causes beyond what management attributed."""
    criteria = []
    bridge = value.get('bridge')
    if bridge:
        v = bridge['values']
        criteria.append(
            f"Other income (expense), net: {_billions_or_millions(v['current:NonoperatingIncomeExpense'])} versus "
            f"{_billions_or_millions(v['prior:NonoperatingIncomeExpense'])} a year earlier. It moved net income "
            "opposite to operating income this period; the next comparable filing shows whether that recurs.")
    for statement in value['statements']:
        cause = _cause(statement['quote'])
        if cause:
            criteria.append(f"{statement['metric'][0].upper()}{statement['metric'][1:]}, management's stated reason: "
                            f"“{cause}”. The next comparable filing's explanation shows whether management "
                            "reports the same driver.")
    for component in value['components']:
        match = _COMPONENT.search(component['quote'])
        label = component['quote'][:match.start()].strip()
        cause = _cause(component['quote'][match.end():])
        if not cause or not re.fullmatch(r"[A-Za-z][A-Za-z/&' -]{2,80}", label):
            continue
        criteria.append(f"{label}: ${match.group(5).rstrip(',')} versus ${match.group(4).rstrip(',')} a year "
                        f"earlier; management's stated reason: “{cause}”. The next comparable filing's figure "
                        "and stated reason show whether this persists.")
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


def explanation_value(text, observations, filing_items, *, ticker, document_type, filed_at):
    metrics, period = _metrics(filing_items)
    if not period or 'revenue' not in metrics:
        return None
    current, prior = (period[0], period[1]), (period[2], period[3])
    bridge = earnings_bridge(observations, current, prior)
    nonop = {}
    if bridge:
        v = bridge['values']
        nonop = {'other income (expense), net': {'current': v['current:NonoperatingIncomeExpense'],
                                                  'prior': v['prior:NonoperatingIncomeExpense']}}
    statements, components, seen_metrics, anchor = [], [], set(), None
    all_sentences = list(sentences(text))
    for index, (offset, sentence) in enumerate(all_sentences):
        binding = None
        for start in clause_starts(sentence):
            binding = bind_statement(sentence[start:], {**metrics, **nonop})
            if binding:
                break
        if binding and binding['metric'] not in seen_metrics:
            seen_metrics.add(binding['metric'])
            statements.append({'quote': sentence[start:], 'start_offset': offset + start, **binding})
            if binding['metric'] == 'revenue' and anchor is None:
                anchor = index
    if anchor is not None:
        for offset, sentence in all_sentences[anchor + 1:anchor + 12]:
            if re.search(r'\bconsolidated\b', sentence, re.I):
                break  # the next period's discussion begins
            if consistent_component(sentence) and len(components) < MAX_COMPONENTS:
                components.append({'quote': sentence, 'start_offset': offset, 'basis': 'internally consistent component'})
    if not statements and not bridge:
        return None
    value = {'claim_kind': 'issuer_current_period_explanation', 'ticker': ticker,
             'document_type': document_type, 'filed_at': filed_at,
             'period': {'current_start': current[0], 'current_end': current[1],
                        'prior_start': prior[0], 'prior_end': prior[1]},
             'metrics': {**metrics, **nonop}, 'bridge': bridge,
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
                        if (amount := validated_observation(row, cik=cik, concepts=BRIDGE_CONCEPTS)) is not None]
        value = explanation_value(document.text, observations, filing_items, ticker=ticker,
                                  document_type=document.document_type, filed_at=document.published_at)
        if value is None or not date.fromisoformat(value['period']['current_end']) <= date.fromisoformat(document.published_at) <= date.today():
            return []
        # The reference anchors one bound statement; every other quote is
        # rechecked from the stored value, never shortened to fit.
        anchor = value['statements'][0]['quote'] if value['statements'] else 'consolidated inline XBRL facts'
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
            if bind_statement(statement['quote'], metrics) != {'metric': statement['metric'], 'basis': statement['basis']}:
                return None
        if any(not consistent_component(c['quote']) for c in v['components']):
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
                or not (v['statements'] or bridge) or 'revenue' not in metrics
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
