"""Bounded management-attributed sales explanations, never verified causes."""
from decimal import Decimal, ROUND_HALF_UP, localcontext
import hashlib
import re

from ..providers.sec_segment_facts import reconstruct
from .sec_risk_sections import rejected_risk_heading, risk_sentence_spans

OPEN = re.compile(r'\bITEM\s+7\.\s+MANAGEMENT[’\']S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND RESULTS OF OPERATIONS\b', re.I)
CLOSE = re.compile(r'\bITEM\s+7A\.\s+QUANTITATIVE AND QUALITATIVE DISCLOSURES ABOUT MARKET RISK\b', re.I)
YEARS = re.compile(r'\b(20\d{2}) COMPARED TO (20\d{2})\b')
MONEY = r'(?:0|[1-9]\d{0,2}(?:,\d{3})*)'
SALES = re.compile(
    rf"Net sales of the (?P<label>[A-Za-z][A-Za-z /&-]{{1,79}}) segment "
    rf"(?P<direction>increased|decreased) by \$(?P<change>{MONEY})"
    rf"(?: \((?P<percent>\d{{1,3}})%\))?, from \$(?P<prior>{MONEY}) to \$(?P<current>{MONEY}), "
    r"reflecting (?P<article>an|a) (?P<movement>increase|decrease) in "
    r"(?P<explanation>shipments from the segment's backlog|units shipped)\.")


def source_window(text):
    if not isinstance(text, str) or len(text) > 360_000:
        return None
    openings = [m for m in OPEN.finditer(text)
                if not rejected_risk_heading(text, m.end(), start=m.start())]
    closings = [m for m in CLOSE.finditer(text)
                if not rejected_risk_heading(text, m.end(), start=m.start())]
    if len(openings) != 1 or len(closings) != 1:
        return None
    a, b = openings[0].start(), closings[0].start()
    if not 0 < b - a <= 80_000:
        return None
    value = text[a:b] + closings[0].group()
    return {'text': value, 'start_offset': a,
            'sha256': hashlib.sha256(value.encode()).hexdigest()}


def explanations(proof, source, *, cik):
    """Rebuild all output from complete section text and both period proofs."""
    try:
        if (not isinstance(source, dict) or set(source) != {'text', 'start_offset', 'sha256'}
                or type(source['start_offset']) is not int or not 0 <= source['start_offset'] <= 360_000
                or source['start_offset'] + len(source['text']) > 360_000
                or hashlib.sha256(source['text'].encode()).hexdigest() != source['sha256']):
            return []
        window = source_window(source['text'])
        if not window or window['start_offset'] != 0 or window['text'] != source['text']:
            return []
        current = reconstruct(proof, cik=cik)
        prior_proof = proof['comparison_period']
        if 'comparison_period' in prior_proof:
            return []
        prior = reconstruct(prior_proof, cik=cik)
        year = int(proof['period_end'][:4])
        if (not current or not prior or prior_proof['period_end'] != f'{year-1}-12-31'
                or any(proof[k] != prior_proof[k] for k in
                       ('table_number', 'headers', 'definition', 'allocation', 'unit_heading'))
                or [r['label'] for r in current] != [r['label'] for r in prior]
                or [e['column'] for e in proof['metrics']['revenue']['entries']]
                   != [e['column'] for e in prior_proof['metrics']['revenue']['entries']]
                or any(a['dimensions'] != b['dimensions'] or a['start'][5:] != b['start'][5:]
                       or a['start'][:4] != str(year) or b['start'][:4] != str(year-1)
                       for a, b in zip(current, prior))):
            return []
        text = source['text']
        headings = list(YEARS.finditer(text))
        # The first comparison must be current/prior; a repeated heading in
        # liquidity cannot replace a missing or different results comparison.
        if len(headings) < 2 or headings[0].groups() != (str(year), str(year-1)):
            return []
        if headings[1].groups() != (str(year-1), str(year-2)):
            return []
        start, end = headings[0].end(), headings[1].start()
        found = []
        for left, right in risk_sentence_spans(text[start:end]):
            a, b = start + left, start + right
            while a < b and text[a] in '\ufeff \t\n':
                a += 1
            quote = text[a:b]
            match = SALES.fullmatch(quote)
            if not match or len(quote) > 300:
                continue
            rows = [(c, p) for c, p in zip(current, prior) if c['label'] == match['label']]
            if len(rows) != 1:
                continue
            c, p = rows[0]
            number = lambda key: int(match[key].replace(',', ''))
            delta = c['revenue_usd'] - p['revenue_usd']
            if (delta == 0 or number('current') != c['revenue_usd'] or number('prior') != p['revenue_usd']
                    or number('change') != abs(delta)
                    or match['direction'] != ('increased' if delta > 0 else 'decreased')
                    or match['movement'] != ('increase' if delta > 0 else 'decrease')):
                continue
            if match['article'] != ('an' if delta > 0 else 'a'):
                continue
            if match['percent']:
                if p['revenue_usd'] <= 0:
                    continue
                with localcontext() as ctx:
                    ctx.prec = 80
                    percent = (Decimal(abs(delta)) * 100 / Decimal(p['revenue_usd'])).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
                if percent != int(match['percent']):
                    continue
            found.append({'label': c['label'], 'currency': 'USD', 'current_start': c['start'],
                'current_end': c['end'], 'prior_start': p['start'], 'prior_end': p['end'],
                'current_revenue_usd': c['revenue_usd'], 'prior_revenue_usd': p['revenue_usd'],
                'change_usd': delta, 'quote': quote, 'start_offset': source['start_offset'] + a,
                'end_offset': source['start_offset'] + b, 'comparison_heading': headings[0].group(),
                'heading_start_offset': source['start_offset'] + headings[0].start(),
                'attribution': 'management', 'scope': 'reported_segment_sales',
                'limitation': 'This is management’s explanation, not independently established causation, new orders or a future revenue forecast.'})
        # Multiple eligible explanations for one segment are ambiguous.
        return [x for x in found if sum(y['label'] == x['label'] for y in found) == 1][:8]
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return []
