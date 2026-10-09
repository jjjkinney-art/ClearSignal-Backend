"""Conservative consolidated USD facts from a single Inline XBRL document.

Unsupported transformations, dimensions, ambiguous identifiers and malformed
XML remain gaps. This is not a general-purpose XBRL processor.
"""
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
from io import StringIO
import re
from xml.etree import ElementTree as ET

XBRLI = 'http://www.xbrl.org/2003/instance'
IX = 'http://www.xbrl.org/2013/inlineXBRL'
USD = 'http://www.xbrl.org/2003/iso4217'
_ID = re.compile(r'[A-Za-z_][A-Za-z0-9_.-]{0,199}\Z')
_GAAP = re.compile(r'https?://(?:fasb\.org|xbrl\.us)/us-gaap/20\d{2}(?:-\d{2}-\d{2})?\Z')
_TRANSFORMS = {
    'http://www.xbrl.org/inlineXBRL/transformation/2011-07-31': {'numcommadot'},
    'http://www.xbrl.org/inlineXBRL/transformation/2015-02-26': {'numdotdecimal'},
    'http://www.xbrl.org/inlineXBRL/transformation/2020-02-12': {'num-dot-decimal'},
    'http://www.xbrl.org/inlineXBRL/transformation/2022-02-16': {'num-dot-decimal'},
}


def validated_observation(value, *, cik, concepts):
    """Recheck the producer's source observation before binding or rendering."""
    try:
        if (not isinstance(value, dict) or not _GAAP.fullmatch(value['concept_namespace'])
                or value['concept'] not in concepts or value['unit'] != 'USD'
                or value['unit_namespace'] != USD
                or value['entity_scheme'] != 'http://www.sec.gov/CIK'
                or not re.fullmatch(r'[0-9]{1,10}', value['entity_identifier'])
                or int(value['entity_identifier']) != int(cik)
                or value['scope'] != 'consolidated'
                or any(not _ID.fullmatch(value[key]) for key in ('fact_id', 'context_id', 'unit_id'))
                or value['sign'] not in ('', '-')
                or type(value['scale']) is not int or not -9 <= value['scale'] <= 9):
            return None
        start, end = date.fromisoformat(value['start']), date.fromisoformat(value['end'])
        if start > end:
            return None
        literal = value['literal']
        if not isinstance(literal, str) or len(literal) > 80:
            return None
        namespace, transformation = value['format_namespace'], value['format']
        if transformation:
            if transformation not in _TRANSFORMS.get(namespace, set()):
                return None
            # Only dot-decimal values and properly grouped comma thousands.
            if not re.fullmatch(r'(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?', literal):
                return None
        elif namespace or not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', literal):
            return None
        with localcontext() as arithmetic:
            arithmetic.prec = 100
            amount = Decimal(literal.replace(',', '')) * (Decimal(10) ** value['scale'])
            if value['sign'] == '-':
                amount = -amount
        if not amount.is_finite() or abs(amount) > Decimal('1e18'):
            return None
        # USD statement amounts are retained exactly; no floating point rounding.
        if amount != amount.to_integral_value():
            return None
        return int(amount)
    except (KeyError, TypeError, ValueError, InvalidOperation, OverflowError):
        return None


def parse_inline_observations(text, *, cik, concepts):
    """Read namespace-aware XHTML without entity expansion or external fetches."""
    if (not isinstance(text, str) or '<!DOCTYPE' in text.upper()
            or '<!ENTITY' in text.upper() or len(text) > 15_000_000):
        return ()
    try:
        namespaces, stack, pending, scope = {}, [], [], {}
        parser = ET.iterparse(StringIO(text), events=('start', 'end', 'start-ns'))
        for event, item in parser:
            if event == 'start-ns':
                pending.append(item)
            elif event == 'start':
                stack.append(scope)
                scope = {**scope, **dict(pending)} if pending else scope
                pending = []
                namespaces[id(item)] = scope
            else:
                scope = stack.pop()
        root = parser.root
    except (ET.ParseError, ValueError):
        return ()

    def qname(element, name):
        parts = (name or '').split(':')
        if len(parts) != 2:
            return '', ''
        return namespaces[id(element)].get(parts[0], ''), parts[1]

    # Duplicate XML IDs cannot safely identify a fact or its context/unit.
    ids, duplicate = {}, set()
    for element in root.iter():
        identifier = element.get('id')
        if identifier:
            if identifier in ids:
                duplicate.add(identifier)
            ids[identifier] = element
    observations = []
    for fact in root.iter(f'{{{IX}}}nonFraction'):
        attrs = fact.attrib
        concept_ns, concept = qname(fact, attrs.get('name'))
        if (concept not in concepts or not _GAAP.fullmatch(concept_ns)
                or list(fact) or any(key in attrs for key in ('tupleRef', 'target', 'continuedAt', 'precision'))
                or attrs.get('{http://www.w3.org/2001/XMLSchema-instance}nil') is not None
                or not re.fullmatch(r'(?:INF|-?[0-9]{1,2})', attrs.get('decimals', ''))):
            continue
        fact_id, context_id, unit_id = (attrs.get(key, '') for key in ('id', 'contextRef', 'unitRef'))
        if any(identifier in duplicate for identifier in (fact_id, context_id, unit_id)):
            continue
        context, unit = ids.get(context_id), ids.get(unit_id)
        if (context is None or unit is None or context.tag != f'{{{XBRLI}}}context'
                or unit.tag != f'{{{XBRLI}}}unit'):
            continue
        entity, period = context.find(f'{{{XBRLI}}}entity'), context.find(f'{{{XBRLI}}}period')
        if (entity is None or period is None or len(context) != 2 or len(entity) != 1
                or len(period) != 2 or len(unit) != 1):
            continue
        identifier = entity.find(f'{{{XBRLI}}}identifier')
        start, end = period.find(f'{{{XBRLI}}}startDate'), period.find(f'{{{XBRLI}}}endDate')
        measure = unit.find(f'{{{XBRLI}}}measure')
        if any(element is None for element in (identifier, start, end, measure)):
            continue
        unit_ns, unit_name = qname(measure, (measure.text or '').strip())
        format_ns, format_name = qname(fact, attrs.get('format')) if attrs.get('format') else ('', '')
        try:
            scale = int(attrs.get('scale', '0'))
        except ValueError:
            continue
        observation = dict(concept_namespace=concept_ns, concept=concept, unit=unit_name,
            unit_namespace=unit_ns, entity_scheme=identifier.get('scheme'),
            entity_identifier=(identifier.text or '').strip(), scope='consolidated',
            start=(start.text or '').strip(), end=(end.text or '').strip(),
            fact_id=fact_id, context_id=context_id, unit_id=unit_id,
            literal=(fact.text or '').strip(), format_namespace=format_ns, format=format_name,
            sign=attrs.get('sign', ''), scale=scale)
        if validated_observation(observation, cik=cik, concepts=concepts) is not None:
            observations.append(observation)
    return tuple(observations)
