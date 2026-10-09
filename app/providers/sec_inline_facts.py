"""Conservative consolidated USD facts from a single Inline XBRL document.

Unsupported transformations, dimensions, ambiguous identifiers and malformed
XML remain gaps. This is not a general-purpose XBRL processor.
"""
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
import logging
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


# Bounds apply to retained metadata, independently of the download-size limit.
MAX_DEPTH = 128
MAX_IDS = 200_000
MAX_RESOURCES = 20_000
MAX_FACTS = 20_000
MAX_RESOURCE_NODES = 64
MAX_FIELD_CHARS = 4096
_DECLARATION = re.compile(r'<!\s*(?:DOCTYPE|ENTITY)\b', re.I)
MAX_NAMESPACES = 256
_TEXT_FIELDS = frozenset({f'{{{XBRLI}}}{name}' for name in
    ('identifier', 'startDate', 'endDate', 'measure')} | {f'{{{IX}}}nonFraction'})
logger = logging.getLogger(__name__)


class _ParseLimit(ValueError):
    pass


def _qname(scope, name):
    parts = (name or '').split(':')
    return (scope.get(parts[0], ''), parts[1]) if len(parts) == 2 else ('', '')


class _InlineTarget:
    """XML callbacks retain flat observations and one small resource subtree.

    There is no document tree or namespace index for unrelated display markup.
    All IDs are checked through EOF so a later duplicate still rejects a fact.
    """
    def __init__(self, concepts):
        self.concepts = frozenset(concepts)
        self.stack, self.pending, self.scope = [], [], {}
        self.ids, self.duplicates = set(), set()
        self.contexts, self.units, self.facts = {}, {}, []
        self.resource, self.resource_nodes, self.resource_invalid = None, 0, False
        self.resource_namespaces = {}
        self.resource_count = 0

    def start_ns(self, prefix, uri):
        if len(prefix or '') > 200 or len(uri) > 2048 or len(self.pending) >= MAX_NAMESPACES:
            raise _ParseLimit('XML namespace limit')
        self.pending.append((prefix or '', uri))

    def end_ns(self, prefix):
        # Element frames restore the preceding namespace scope.
        pass

    def start(self, tag, attrs):
        if len(self.stack) >= MAX_DEPTH:
            raise _ParseLimit('XML depth limit')
        identifier = attrs.get('id')
        # Longer IDs cannot be a supported fact/context/unit reference.
        if identifier and len(identifier) <= 200:
            if identifier in self.ids:
                self.duplicates.add(identifier)
            else:
                if len(self.ids) >= MAX_IDS:
                    raise _ParseLimit('XML identifier limit')
                self.ids.add(identifier)
        previous = self.scope
        if self.pending:
            self.scope = {**previous, **dict(self.pending)}
            self.pending = []
            if len(self.scope) > MAX_NAMESPACES:
                raise _ParseLimit('XML namespace limit')
        if self.stack:
            self.stack[-1]['children'] += 1
        element = ET.Element(tag, attrs) if (
            self.resource is not None or tag in {f'{{{XBRLI}}}context', f'{{{XBRLI}}}unit', f'{{{IX}}}nonFraction'}
        ) else None
        frame = dict(tag=tag, element=element, previous=previous,
                     scope=self.scope, children=0, text_overflow=False)
        if self.resource is None and tag in {f'{{{XBRLI}}}context', f'{{{XBRLI}}}unit'}:
            self.resource_count += 1
            if self.resource_count > MAX_RESOURCES:
                raise _ParseLimit('XBRL resource limit')
            self.resource = element
            self.resource_nodes, self.resource_invalid = 0, False
            self.resource_namespaces = {}
        if self.resource is not None:
            self.resource_nodes += 1
            if self.resource_nodes > MAX_RESOURCE_NODES:
                self.resource_invalid = True
                self.resource.clear()
                self.resource_namespaces.clear()
            if not self.resource_invalid:
                if self.stack and element is not self.resource:
                    self.stack[-1]['element'].append(element)
                if tag == f'{{{XBRLI}}}measure':
                    self.resource_namespaces[id(element)] = self.scope
        self.stack.append(frame)

    def data(self, text):
        if not self.stack:
            return
        frame = self.stack[-1]
        element = frame['element']
        if (element is None or frame['text_overflow'] or
                frame['tag'] not in _TEXT_FIELDS):
            return
        if len(element.text or '') + len(text) > MAX_FIELD_CHARS:
            frame['text_overflow'] = True
            # This cannot pass the bounded literal/date/identity validation.
            element.text = '!' * (MAX_FIELD_CHARS + 1)
        else:
            element.text = (element.text or '') + text

    def _resource(self, element):
        key = element.get('id', '')
        if not _ID.fullmatch(key):
            return
        if element.tag == f'{{{XBRLI}}}context':
            entity = element.find(f'{{{XBRLI}}}entity')
            period = element.find(f'{{{XBRLI}}}period')
            if (entity is None or period is None or len(element) != 2
                    or len(entity) != 1 or len(period) != 2):
                return
            identifier = entity.find(f'{{{XBRLI}}}identifier')
            start = period.find(f'{{{XBRLI}}}startDate')
            end = period.find(f'{{{XBRLI}}}endDate')
            if any(x is None or len(x) for x in (identifier, start, end)):
                return
            values = dict(entity_scheme=identifier.get('scheme'),
                          entity_identifier=(identifier.text or '').strip(),
                          start=(start.text or '').strip(), end=(end.text or '').strip())
            if (len(values['entity_identifier']) > 10 or len(values['start']) != 10
                    or len(values['end']) != 10):
                return
            self.contexts[key] = values
        else:
            measure = element.find(f'{{{XBRLI}}}measure')
            if len(element) != 1 or measure is None or len(measure):
                return
            namespace, unit = _qname(self.resource_namespaces.get(id(measure), {}),
                                     (measure.text or '').strip())
            if unit == 'USD' and namespace == USD:
                self.units[key] = dict(unit_namespace=namespace, unit=unit)

    def _fact(self, frame):
        fact = frame['element']
        attrs = fact.attrib
        namespace, concept = _qname(frame['scope'], attrs.get('name'))
        if (concept not in self.concepts or not _GAAP.fullmatch(namespace)
                or frame['children'] or frame['text_overflow']
                or any(key in attrs for key in ('tupleRef', 'target', 'continuedAt', 'precision'))
                or attrs.get('{http://www.w3.org/2001/XMLSchema-instance}nil') is not None
                or not re.fullmatch(r'(?:INF|-?[0-9]{1,2})', attrs.get('decimals', ''))):
            return
        fact_id, context_id, unit_id = (attrs.get(key, '') for key in ('id', 'contextRef', 'unitRef'))
        literal = (fact.text or '').strip()
        if any(not _ID.fullmatch(key) for key in (fact_id, context_id, unit_id)) or len(literal) > 80:
            return
        try:
            scale = int(attrs.get('scale', '0'))
        except ValueError:
            return
        format_ns, format_name = _qname(frame['scope'], attrs.get('format')) if attrs.get('format') else ('', '')
        if len(self.facts) >= MAX_FACTS:
            raise _ParseLimit('Inline fact limit')
        self.facts.append(dict(concept_namespace=namespace, concept=concept,
            fact_id=fact_id, context_id=context_id, unit_id=unit_id, literal=literal,
            format_namespace=format_ns, format=format_name, sign=attrs.get('sign', ''), scale=scale))

    def end(self, tag):
        frame = self.stack.pop()
        if tag == f'{{{IX}}}nonFraction':
            self._fact(frame)
        if frame['element'] is self.resource and self.resource is not None:
            if not self.resource_invalid:
                self._resource(self.resource)
            self.resource = None
            self.resource_namespaces = {}
        self.scope = frame['previous']

    def close(self):
        return self


def parse_inline_observations(text, *, cik, concepts):
    """Parse bounded XML callbacks; unsupported or incomplete input fails closed."""
    if not isinstance(text, str) or len(text) > 15_000_000 or _DECLARATION.search(text):
        return ()
    target = _InlineTarget(concepts)
    parser = ET.XMLParser(target=target)
    try:
        # Feeding slices avoids an additional whole-document StringIO copy.
        for start in range(0, len(text), 16_384):
            parser.feed(text[start:start + 16_384])
        parser.close()
    except _ParseLimit as exc:
        logger.warning('Inline XBRL extraction unavailable: %s', exc)
        return ()
    except (ET.ParseError, ValueError):
        return ()
    observations = []
    for fact in target.facts:
        if any(fact[key] in target.duplicates for key in ('fact_id', 'context_id', 'unit_id')):
            continue
        context = target.contexts.get(fact['context_id'])
        unit = target.units.get(fact['unit_id'])
        if context is None or unit is None:
            continue
        observation = dict(**fact, **context, **unit, scope='consolidated')
        if validated_observation(observation, cik=cik, concepts=concepts) is not None:
            observations.append(observation)
    return tuple(observations)
