"""Offline per-share facts and EPS policy from one saved, identity-bound filing.

No production parser widening, basic-to-diluted substitution or split clearance.
"""
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
import re
from xml.etree import ElementTree as ET

from app.providers.sec_inline_facts import (
    _InlineTarget, _ParseLimit, _qname, _GAAP, _ID, _TRANSFORMS, IX, XBRLI, USD,
)
from validation.filing_share_class import extract_filed_share_class

CONCEPTS = ('EarningsPerShareBasic', 'EarningsPerShareDiluted')
POLICY = 'EarningsPerShareTextBlock'
MAX_POLICY_CHARS = 8192
MAX_POLICIES = 32
BLOCKS = {f'{{http://www.w3.org/1999/xhtml}}{name}' for name in ('p', 'div', 'td', 'tr', 'br')}


class _EPSInlineTarget(_InlineTarget):
    """Reuse bounded contexts/facts; opt in to exact USD/xbrli:shares units only."""
    def __init__(self):
        super().__init__(CONCEPTS)
        self.policy = None
        self.policies = []

    def _resource(self, element):
        if element.tag == f'{{{XBRLI}}}context':
            return super()._resource(element)
        key = element.get('id', '')
        divide = element.find(f'{{{XBRLI}}}divide')
        if not _ID.fullmatch(key) or len(element) != 1 or divide is None or len(divide) != 2:
            return
        numerator = divide.find(f'{{{XBRLI}}}unitNumerator')
        denominator = divide.find(f'{{{XBRLI}}}unitDenominator')
        if (numerator is None or denominator is None or len(numerator) != 1 or len(denominator) != 1
                or [child.tag for child in divide] != [f'{{{XBRLI}}}unitNumerator', f'{{{XBRLI}}}unitDenominator']):
            return
        top = numerator.find(f'{{{XBRLI}}}measure')
        bottom = denominator.find(f'{{{XBRLI}}}measure')
        if top is None or bottom is None or len(top) or len(bottom):
            return
        top_qname = _qname(self.resource_namespaces.get(id(top), {}), (top.text or '').strip())
        bottom_qname = _qname(self.resource_namespaces.get(id(bottom), {}), (bottom.text or '').strip())
        if top_qname == (USD, 'USD') and bottom_qname == (XBRLI, 'shares'):
            self.units[key] = {'unit': 'USD/shares', 'currency': 'USD',
                'numerator_namespace': USD, 'denominator_namespace': XBRLI}

    def _fact(self, frame):
        attrs = frame['element'].attrib
        if (any(item['tag'] in {f'{{{IX}}}exclude', f'{{{IX}}}continuation'} for item in self.stack)
                or 'escape' in attrs or ('format' in attrs
                and not all(_qname(frame['scope'], attrs['format'])))):
            return
        count = len(self.facts)
        super()._fact(frame)
        if len(self.facts) > count:
            self.facts[-1]['decimals'] = frame['element'].get('decimals')

    def _policy_data(self, text):
        if self.policy is None or self.policy['overflow']:
            return
        if self.policy['chars'] + len(text) > MAX_POLICY_CHARS:
            self.policy['overflow'] = True
            self.policy['chunks'] = []
        else:
            self.policy['chars'] += len(text)
            self.policy['chunks'].append(text)

    def start(self, tag, attrs):
        super().start(tag, attrs)
        namespace, concept = _qname(self.stack[-1]['scope'], attrs.get('name'))
        if tag == f'{{{IX}}}nonNumeric' and concept == POLICY and _GAAP.fullmatch(namespace):
            if any(item['tag'] in {f'{{{IX}}}exclude', f'{{{IX}}}continuation'} for item in self.stack[:-1]):
                return
            if self.policy is not None or len(self.policies) >= MAX_POLICIES:
                raise _ParseLimit('EPS policy bound or nesting')
            if (not _ID.fullmatch(attrs.get('id', '')) or not _ID.fullmatch(attrs.get('contextRef', ''))
                    or any(key in attrs for key in ('continuedAt', 'target', 'format', 'tupleRef'))
                    or '{http://www.w3.org/2001/XMLSchema-instance}nil' in attrs
                    or attrs.get('escape', '') not in ('', 'true', 'false')):
                return
            self.policy = {'fact_id': attrs['id'], 'context_id': attrs['contextRef'],
                'concept': POLICY, 'concept_namespace': namespace, 'depth': len(self.stack),
                'chunks': [], 'chars': 0, 'overflow': False}
        elif self.policy is not None and tag in BLOCKS:
            self._policy_data(' ')

    def data(self, text):
        super().data(text)
        if self.policy is not None and not any(frame['tag'] == f'{{{IX}}}exclude' for frame in self.stack):
            self._policy_data(text)

    def end(self, tag):
        if self.policy is not None:
            if tag in BLOCKS:
                self._policy_data(' ')
            if tag == f'{{{IX}}}nonNumeric' and len(self.stack) == self.policy['depth']:
                self.policies.append(self.policy)
                self.policy = None
        super().end(tag)


def _context(target, identifier, cik, period_end):
    if identifier in target.duplicates:
        return None
    value = target.contexts.get(identifier)
    if (not value or value['entity_scheme'] != 'http://www.sec.gov/CIK'
            or not re.fullmatch(r'[0-9]{1,10}', value['entity_identifier'])
            or int(value['entity_identifier']) != int(cik)):
        return None
    try:
        start, end = date.fromisoformat(value['start']), date.fromisoformat(value['end'])
        if (start.isoformat() != value['start'] or end.isoformat() != value['end']
                or not 300 <= (end - start).days + 1 <= 380 or end.isoformat() > period_end):
            return None
    except ValueError:
        return None
    return value


def _amount(fact):
    if fact['sign'] not in ('', '-') or not -9 <= fact['scale'] <= 9:
        return None
    literal, transform = fact['literal'], fact['format']
    if transform:
        if (transform not in _TRANSFORMS.get(fact['format_namespace'], set())
                or not re.fullmatch(r'(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?', literal)):
            return None
    elif fact['format_namespace'] or not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', literal):
        return None
    try:
        with localcontext() as context:
            context.prec = 100
            value = Decimal(literal.replace(',', '')) * Decimal(10) ** fact['scale']
            if fact['sign'] == '-':
                value = -value
        return format(value, 'f') if value.is_finite() and value.copy_abs() <= Decimal('1000000') else None
    except InvalidOperation:
        return None


def inspect_filing_eps_basis(body, receipt, *, expected_cik, expected_symbol,
                             form, filed_at, reporting_period_end):
    """Keep basic/diluted facts, policy display text and missing basis proof apart."""
    cover = extract_filed_share_class(body, receipt, expected_cik=expected_cik,
        expected_symbol=expected_symbol, form=form, filed_at=filed_at, reporting_period_end=reporting_period_end)
    if not cover['extracted'] or form not in ('10-K', '10-K/A'):
        return _gap('filing_binding')
    target = _EPSInlineTarget()
    parser = ET.XMLParser(target=target)
    try:
        text = body.decode('utf-8')
        for start in range(0, len(text), 16384):
            parser.feed(text[start:start+16384])
        parser.close()
    except (_ParseLimit, ET.ParseError, ValueError):
        return _gap('bounded_inline_parse')
    observations = []
    for fact in target.facts:
        context = _context(target, fact['context_id'], expected_cik, reporting_period_end)
        unit = target.units.get(fact['unit_id'])
        value = _amount(fact)
        if (context is None or unit is None or value is None
                or any(fact[key] in target.duplicates for key in ('fact_id', 'unit_id'))):
            continue
        observations.append({**fact, **context, **unit, 'value': value,
            'scope': 'consolidated_unsegmented_context', 'source_form': form, 'filed_at': filed_at})
    observations.sort(key=lambda row: (row['end'], row['start'], row['concept'], row['fact_id']))
    coverage = []
    for concept in CONCEPTS:
        current = [row for row in observations if row['concept'] == concept and row['end'] == reporting_period_end]
        signatures = {(row['start'], row['end'], Decimal(row['value'])) for row in current}
        status = 'observed' if len(signatures) == 1 else 'conflicting' if signatures else 'not_observed'
        coverage.append({'concept': concept, 'status': status,
            'value': current[0]['value'] if status == 'observed' else None,
            'fact_ids': [row['fact_id'] for row in current]})
    policies = []
    for policy in target.policies:
        context = _context(target, policy['context_id'], expected_cik, reporting_period_end)
        if (context is None or context['end'] != reporting_period_end or policy['overflow']
                or policy['fact_id'] in target.duplicates):
            continue
        content = ' '.join(''.join(policy['chunks']).split())
        if content:
            policies.append({**context, 'source_form': form, 'filed_at': filed_at,
                'fact_id': policy['fact_id'], 'context_id': policy['context_id'],
                'concept': POLICY, 'concept_namespace': policy['concept_namespace'], 'display_text': content,
                'representation': 'whitespace_normalized_display_text_not_canonical_xbrl_value',
                'participating_securities_mentioned': True if re.search(r'\bparticipating securities\b', content, re.I) else None})
    return {'inspected': True, 'status': 'partial', 'admitted': False, 'launch_ready': False,
        'classification': 'offline_filing_eps_basis_inspection', 'filed_share_class': cover,
        'raw_binding': {key: cover['raw_binding'][key] for key in ('url', 'body_sha256', 'body_bytes')},
        'observations': observations, 'reporting_period_coverage': coverage, 'eps_policy_display_text': policies,
        'basic_to_diluted_substitution_performed': False, 'already_adjusted_through': None,
        'split_basis_verified': False, 'eps_class_compatibility_verified': False,
        'quote_unit_verified': False, 'independently_adjudicated': False,
        'limitations': ['Only explicit USD divided by xbrli:shares units and unsegmented annual contexts are supported.',
            'Missing/unsupported facts are not proof the issuer omitted the metric.',
            'Basic EPS is not promoted to diluted EPS, even when surrounding prose describes both.',
            'EPS policy display text is source context, not proof of an already-adjusted split cutoff or class rights.',
            'No current quote, corporate-action completeness, P/E or product evidence admission is established.']}


def _gap(stage):
    return {'inspected': False, 'status': 'insufficient_eps_basis_evidence', 'admitted': False,
        'launch_ready': False, 'classification': 'offline_filing_eps_basis_inspection',
        'reason': 'filing_eps_basis_rejected', 'stage': stage}
