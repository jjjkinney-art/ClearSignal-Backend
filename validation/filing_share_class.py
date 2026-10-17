"""Offline, source-bound security rows from saved primary Inline XBRL filings.

No retrieval or product evidence admission. A filing's declared class is not
proof of today's listing, quote unit, EPS class allocation or split history.
"""
from datetime import date
import hashlib
import io
import re
from xml.etree import ElementTree as ET

from validation.source_anchored_valuation import _calendar
from validation.valuation_scenario import ValuationContractError

IX = 'http://www.xbrl.org/2013/inlineXBRL'
XBRLI = 'http://www.xbrl.org/2003/instance'
XHTML = 'http://www.w3.org/1999/xhtml'
MAX_FILING_BYTES = 15_000_000  # existing SEC-periodic envelope; no transport exception
DEI = re.compile(r'https?://xbrl\.sec\.gov/dei/20[0-9]{2}(?:q[1-4])?\Z')
ID = re.compile(r'[A-Za-z_][A-Za-z0-9_.-]{0,199}\Z')
SECURITY = {'Security12bTitle', 'TradingSymbol', 'SecurityExchangeName'}
REQUIRED = SECURITY | {'EntityCentralIndexKey', 'DocumentType'}
COMMON = re.compile(
    r'(?:(?:class [a-z0-9.-]{1,12} )?common (?:stock|shares)'
    r'(?:,? (?:(?:\$[0-9]+(?:\.[0-9]+)?|no) par value)(?: per share)?)?'
    r'|(?:\$[0-9]+(?:\.[0-9]+)?|no) par value (?:class [a-z0-9.-]{1,12} )?common (?:stock|shares))\Z', re.I)


def _parse(body, cik, period_end):
    """Retain selected text/context subtrees; no namespace guessing or HTML repair."""
    text = body.decode('utf-8')
    if '\x00' in text or re.search(r'<!\s*(?:DOCTYPE|ENTITY)\b', text, re.I):
        raise ValuationContractError('DTD/entity declarations unsupported')
    encoding = re.match(r'''\s*<\?xml\b[^?]*\bencoding\s*=\s*['"]([^'"]+)['"]''', text, re.I)
    if encoding and encoding[1].lower() not in {'utf-8', 'utf8', 'ascii', 'us-ascii'}:
        raise ValuationContractError('unsupported XML byte encoding')
    stack, pending, scope, ids, contexts, facts = [], [], {}, set(), {}, []
    count = 0
    for event, value in ET.iterparse(io.BytesIO(body), events=('start-ns', 'start', 'end')):
        if event == 'start-ns':
            prefix, uri = value
            if len(prefix or '') > 200 or len(uri) > 2048 or len(pending) >= 256:
                raise ValuationContractError('namespace bound')
            pending.append((prefix or '', uri))
            continue
        node = value
        if event == 'start':
            count += 1
            if count > 100000 or len(stack) >= 128:
                raise ValuationContractError('XML node/depth bound')
            previous = scope
            if pending:
                scope = {**scope, **dict(pending)}
                pending = []
                if len(scope) > 256:
                    raise ValuationContractError('namespace scope bound')
            identifier = node.get('id')
            if identifier is not None:
                # Unrelated dimensional contexts can have long generated IDs.
                # Keep global uniqueness and a computational cap; only selected
                # fact/context references must fit the narrower identifier grammar.
                if not identifier or len(identifier) > 4096 or identifier in ids:
                    raise ValuationContractError('invalid or duplicate XML ID')
                ids.add(identifier)
            qname = (node.get('name') or '').split(':')
            wanted = (node.tag == f'{{{IX}}}nonNumeric' and len(qname) == 2
                      and DEI.fullmatch(scope.get(qname[0], '')) and qname[1] in REQUIRED)
            protected = bool((stack and stack[-1][4]) or node.tag == f'{{{XBRLI}}}context' or wanted)
            stack.append((node, previous, scope, count, protected))
            continue
        if node.tag == f'{{{XBRLI}}}context':
            identifiers = node.findall(f'./{{{XBRLI}}}entity/{{{XBRLI}}}identifier')
            ends = node.findall(f'./{{{XBRLI}}}period/{{{XBRLI}}}endDate')
            instants = node.findall(f'./{{{XBRLI}}}period/{{{XBRLI}}}instant')
            end = (ends + instants)
            if len(list(node.iter())) > 64 or len(contexts) >= 20000:
                raise ValuationContractError('context resource bound')
            valid = (len(identifiers) == 1 and identifiers[0].get('scheme') == 'http://www.sec.gov/CIK'
                and (identifiers[0].text or '').strip() == cik and len(end) == 1
                and (end[0].text or '').strip() == period_end)
            periods = node.findall(f'./{{{XBRLI}}}period')
            starts = node.findall(f'./{{{XBRLI}}}period/{{{XBRLI}}}startDate')
            valid = valid and len(periods) == 1 and (
                (len(instants) == 1 and len(periods[0]) == 1 and not starts)
                or (len(ends) == 1 and len(starts) == 1 and len(periods[0]) == 2
                    and _calendar((starts[0].text or '').strip()) <= _calendar(period_end)))
            contexts[node.get('id')] = valid
        if node.tag == f'{{{IX}}}nonNumeric':
            name = (node.get('name') or '').split(':')
            namespace = scope.get(name[0], '') if len(name) == 2 else ''
            if len(name) == 2 and DEI.fullmatch(namespace) and name[1] in REQUIRED:
                content = ' '.join(''.join(node.itertext()).split())
                if (not content or len(content) > 500 or not ID.fullmatch(node.get('id', ''))
                        or not ID.fullmatch(node.get('contextRef', '')) or 'continuedAt' in node.attrib
                        or 'escape' in node.attrib
                        or '{http://www.w3.org/2001/XMLSchema-instance}nil' in node.attrib
                        or any(n.tag == f'{{{IX}}}exclude' for n in node.iter())):
                    raise ValuationContractError('unsupported security/identity text binding')
                if name[1] != 'SecurityExchangeName' and node.get('format'):
                    raise ValuationContractError('transformed identity/title/symbol unsupported')
                rows = [frame[3] for frame in stack if frame[0].tag == f'{{{XHTML}}}tr']
                hidden = any(frame[0].tag == f'{{{IX}}}hidden' for frame in stack)
                if name[1] in SECURITY and (not rows or hidden):
                    raise ValuationContractError('security fact outside a non-hidden table row')
                facts.append({'concept': name[1], 'namespace': namespace, 'text': content,
                    'fact_id': node.get('id'), 'context_id': node.get('contextRef'),
                    'row': rows[-1] if rows else None, 'format': node.get('format', '')})
                if len(facts) > 1000:
                    raise ValuationContractError('security fact bound')
        if len(stack) == 1 or not stack[-2][4]:
            node.clear()
            if len(stack) > 1:
                stack[-2][0].remove(node)
        _, previous, _, _, _ = stack.pop()
        scope = previous
    if stack:
        raise ValuationContractError('incomplete XML')
    if any(not contexts.get(fact['context_id'], False) for fact in facts):
        raise ValuationContractError('context entity/reporting-period mismatch')
    return facts


def extract_filed_share_class(body, receipt, *, expected_cik, expected_symbol,
                              form, filed_at, reporting_period_end):
    """Select exactly one same-row/context requested security, retaining its title.

    Supplied receipt and filing metadata are consistency inputs, not submission
    authorization or independently authenticated origin. Extra receipt keys are
    never copied to output. Raw content is not normalized before hashing.
    """
    try:
        if (type(body) is not bytes or not 0 < len(body) <= MAX_FILING_BYTES
                or not isinstance(expected_cik, str) or not re.fullmatch(r'[0-9]{10}', expected_cik)
                or int(expected_cik) == 0 or not isinstance(expected_symbol, str)
                or not re.fullmatch(r'[A-Z0-9][A-Z0-9.-]{0,31}', expected_symbol)
                or not isinstance(form, str) or form not in {'10-K', '10-K/A', '10-Q', '10-Q/A'}):
            raise ValuationContractError('explicit supported filing and issuer required')
        if not _calendar(reporting_period_end) <= _calendar(filed_at) <= date.today():
            raise ValuationContractError('filing chronology mismatch')
        if not isinstance(receipt, dict):
            raise ValuationContractError('saved body receipt required')
        url = receipt.get('url')
        if (not isinstance(url, str) or not re.fullmatch(
                rf'https://www\.sec\.gov/Archives/edgar/data/{int(expected_cik)}/[0-9]{{18}}/'
                r'[A-Za-z0-9][A-Za-z0-9_.-]{0,199}\.html?', url)
                or receipt.get('body_sha256') != hashlib.sha256(body).hexdigest()
                or type(receipt.get('body_bytes')) is not int or receipt['body_bytes'] != len(body)
                or type(receipt.get('http_status')) is not int or receipt['http_status'] != 200
                or receipt.get('media_type') != 'text/html' or receipt.get('content_encoding') != 'identity'):
            raise ValuationContractError('exact primary filing URL/body/media receipt required')
        facts = _parse(body, expected_cik, reporting_period_end)
        if ({f['text'] for f in facts if f['concept'] == 'EntityCentralIndexKey'} != {expected_cik}
                or {f['text'] for f in facts if f['concept'] == 'DocumentType'} != {form}):
            raise ValuationContractError('document DEI issuer/form mismatch')
        matches = [f for f in facts if f['concept'] == 'TradingSymbol' and f['text'] == expected_symbol]
        if len(matches) != 1:
            raise ValuationContractError('one exact requested trading symbol required')
        selected = [f for f in facts if f['row'] == matches[0]['row'] and f['concept'] in SECURITY]
        if (len(selected) != 3 or {f['concept'] for f in selected} != SECURITY
                or len({f['context_id'] for f in selected}) != 1):
            raise ValuationContractError('unambiguous same-row/context security fields required')
        fields = {f['concept']: f for f in selected}
        title = fields['Security12bTitle']['text']
        if not COMMON.fullmatch(title):
            raise ValuationContractError('unsupported class-title grammar; no preferred/unit/ADR inference')
        return {'extracted': True, 'admitted': False, 'launch_ready': False,
            'classification': 'offline_filed_common_share_class',
            'declared_security': {'title': title, 'trading_symbol': expected_symbol,
                'exchange_label': fields['SecurityExchangeName']['text'], 'issuer_cik': expected_cik,
                'context_id': matches[0]['context_id'], 'form': form, 'filed_at': filed_at,
                'reporting_period_end': reporting_period_end},
            'raw_binding': {'url': url, 'body_sha256': receipt['body_sha256'], 'body_bytes': len(body),
                'fields': fields},
            'current_listing_verified': False, 'quote_unit_verified': False,
            'split_compatibility_verified': False, 'eps_class_compatibility_verified': False,
            'independently_adjudicated': False,
            'limitations': ['Title/symbol/exchange are declared in this filing, not proof of the current listing.',
                'Hash and supplied metadata establish byte consistency, not source origin authenticity.',
                'Context dimensions and exchange transformations are not interpreted as class-member or exchange equivalence.',
                'No absence-of-split search, corporate-action completeness, quote-unit or EPS-class proof is supplied.',
                'No price/EPS ratio, evidence admission or investment threshold is authorized.']}
    except (ValuationContractError, UnicodeDecodeError, ET.ParseError, RecursionError) as exc:
        return {'extracted': False, 'admitted': False, 'launch_ready': False,
            'classification': 'offline_filed_common_share_class',
            'reason': 'filed_share_class_rejected', 'diagnostic_type': type(exc).__name__}
