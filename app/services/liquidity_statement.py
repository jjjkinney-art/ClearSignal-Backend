"""Management's own liquidity sufficiency statement, quoted as the filing states it (default off).

Read from the latest periodic filing the metrics stage already holds; no additional request. One sentence
qualifies only when the issuer itself states, in the present tense, that named resources are or will be
sufficient (or adequate) for its needs over a stated horizon ("the next twelve months", "the foreseeable
future"). Precision is preferred to recall: a missed statement leaves the existing, honest gap; an overstated
one would be an error. Excluded:

* any going-concern or substantial-doubt passage (the going-concern rule governs those);
* conditional or hedged statements ("if", "may not", "cannot assure", "no assurance", "subject to");
* past-tense or historical statements ("believed ... was sufficient");
* statements about another entity (a customer, a subsidiary, a tenant).

The statement is quoted with its adjacent sentences, verbatim, so any caveat the filing places next to it
travels with it and the quote cannot be read as stronger than the filing writes it. No figure is extracted
and nothing is inferred about solvency, likelihood or adequacy beyond the issuer's own words.

Two narrow guards keep the quote from misleading about dates (open release issue, IRMD, 2026-11-14):
* a neighbouring sentence that states a money amount is quoted only when it dates every amount to the filing's own
  period end; a prior-period or undated balance next to the statement is left out (the statement and the neighbour
  that carries the caveat are kept), so the quote cannot lead with a stale balance under a "period ended" label;
* a bare page number the page break left at the start of the sentence ("23 We believe ...") is not part of the
  statement; it stays in the quote only if a kept neighbour precedes it, since the quote is verbatim.
"""
from datetime import date
import re

from ..integrity.provenance import ClaimDocumentReference
from ..schemas import RetrievedEvidence

SECTION = 'Liquidity statement'
CLAIM_KIND = 'issuer_liquidity_statement'
DOCUMENT_TYPES = frozenset({'10-K', '10-Q', '10-K/A', '10-Q/A'})
MAX_SENTENCE_CHARS = 700
MAX_NEIGHBOR_CHARS = 450
MAX_QUOTE_CHARS = 900

_SUBJECT = re.compile(r"\b(?:we|our|management|the company|the registrant|the group)\b", re.I)
_BELIEF = re.compile(r"\b(?:believes?|expects?|anticipates?|estimates?|concluded?|is confident|are confident)\b", re.I)
_SUFFICIENT = re.compile(
    r"\b(?:will|would)\s+(?:be|remain|continue to be)\s+(?:sufficient|adequate)\b"
    r"|\b(?:are|is|remain|remains)\s+(?:sufficient|adequate)\b"
    r"|\bwill\s+(?:provide|generate)\s+(?:sufficient|adequate)\b"
    r"|\bwill\s+have\s+(?:sufficient|adequate)\b", re.I)
_RESOURCES = re.compile(
    r"\b(?:cash|liquidity|working capital|capital resources|borrowing capacity|credit facilit\w+|"
    r"revolving credit|cash flows?|investments|financial resources)\b", re.I)
_HORIZON = re.compile(
    r"\b(?:next|following|coming)\s+(?:twelve|12)\s+months\b|\bat least (?:the next )?(?:twelve|12) months\b|"
    r"\bforeseeable future\b|\bnext (?:fiscal )?year\b|\bnear term\b|\bshort[- ]term\b", re.I)
_GOING_CONCERN = re.compile(r"\bgoing concern\b|\bsubstantial doubt\b|\balleviat\w*", re.I)
_HEDGED = re.compile(
    r"\b(?:if|unless|whether|provided that|subject to|in the event|were to|no assurance|cannot assure|"
    r"can be no assurance|may not|might not|could not|uncertain)\b", re.I)
_PAST = re.compile(r"\b(?:we|management|the company|the registrant|the group)\s+(?:had\s+)?(?:believed|expected|anticipated)\b"
                   r"|\b(?:was|were|had been)\s+(?:sufficient|adequate)\b", re.I)
_THIRD_PARTY = re.compile(
    r'\b(?:customers?|tenants?|borrowers?|counterpart\w+|suppliers?|licensees?|subsidiar\w+|joint ventures?|'
    r'investees?|affiliates?|vendors?|distributors?|lessees?|portfolio compan\w+)\b(?!\s+and\b)', re.I)


_MONEY = re.compile(r"\$\s?\d|\b\d[\d,.]*\s?(?:thousand|million|billion)\b", re.I)
_MONTHS = ('january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december')
_DATE = re.compile(r"\b(" + "|".join(_MONTHS) + r")\s+(\d{1,2}),?\s+(\d{4})\b", re.I)
_PAGE_MARKER = re.compile(r"\d{1,3}\s+(?=[A-Z])")


def _dates(text):
    return {f"{int(y):04d}-{_MONTHS.index(m.lower()) + 1:02d}-{int(d):02d}" for m, d, y in _DATE.findall(text)}


def dated_to_period_end(neighbour, period_end):
    """True when the neighbouring text states no amount, or dates every amount it states to the filing's period end."""
    if not _MONEY.search(neighbour):
        return True
    return _dates(neighbour) == {period_end}


def enabled():
    from ..config import settings
    return getattr(settings, 'liquidity_statements_enabled', False) is True


def classify(sentence):
    """'statement' only for the issuer's own present-tense sufficiency statement; else a reason."""
    if not isinstance(sentence, str) or len(sentence) > MAX_SENTENCE_CHARS or not sentence.endswith('.'):
        return 'not_a_sentence'
    sufficient = _SUFFICIENT.search(sentence)
    if not sufficient:
        return 'no_sufficiency_assertion'
    if _GOING_CONCERN.search(sentence):
        return 'going_concern_passage'
    before = sentence[:sufficient.start()]
    if not _SUBJECT.search(before) or not _BELIEF.search(before):
        return 'no_issuer_belief'
    if not _RESOURCES.search(sentence):
        return 'no_named_resources'
    if not _HORIZON.search(sentence):
        return 'no_horizon'
    if _HEDGED.search(before) or _HEDGED.search(sentence[sufficient.start():sufficient.end() + 40]):
        return 'hedged'
    if _PAST.search(before):
        return 'past_tense'
    if _THIRD_PARTY.search(before):
        return 'other_entity'
    return 'statement'


def _summary(value):
    return (f'{value["ticker"]} stated in its {value["document_type"]} filed {value["document_ref"]["published_at"]}'
            f' (period ended {value["period_end"]}): “{value["quote"]}” This is management’s own liquidity '
            'statement, quoted as written. It is not an independent assessment of liquidity or solvency, and it '
            'says nothing about any period the filing does not address.')


def extract_liquidity_statement(document, *, ticker, cik, period_end):
    """The latest periodic filing's first qualifying liquidity statement, or []."""
    from .current_period_explanation import sentences
    from .thesis_disclosures import _business_issuer_url
    if (document.document_type not in DOCUMENT_TYPES or document.publisher != 'SEC EDGAR'
            or document.source_type != 'regulatory_filing' or document.source_tier != 'primary'
            or document.extraction_method != 'html' or not getattr(document, 'text', '')
            or not _business_issuer_url(document.final_url, cik)
            or not re.fullmatch(r'[0-9a-f]{64}', document.content_hash or '')):
        return []
    try:
        if not date.fromisoformat(period_end) <= date.fromisoformat(document.published_at) <= date.today():
            return []
    except (TypeError, ValueError):
        return []
    text = document.text
    pairs = list(sentences(text))
    for index, (offset, raw_sentence) in enumerate(pairs):
        marker = _PAGE_MARKER.match(raw_sentence)  # "23 We believe ...": the page number is not the issuer's statement
        sentence = raw_sentence[marker.end():] if marker else raw_sentence
        statement_at = offset + (marker.end() if marker else 0)
        if classify(sentence) != 'statement':
            continue
        previous = pairs[index - 1] if index else None
        following = pairs[index + 1] if index + 1 < len(pairs) else None
        start, end = statement_at, statement_at + len(sentence)
        if (previous and len(previous[1]) <= MAX_NEIGHBOR_CHARS and not text[previous[0] + len(previous[1]):offset].strip()
                and dated_to_period_end(previous[1], period_end)):
            start = previous[0]
        if (following and len(following[1]) <= MAX_NEIGHBOR_CHARS and not text[end:following[0]].strip()
                and dated_to_period_end(following[1], period_end)):
            end = following[0] + len(following[1])
        if end - start > MAX_QUOTE_CHARS:
            start, end = statement_at, statement_at + len(sentence)
        quote = text[start:end]
        if _GOING_CONCERN.search(quote):
            continue  # a neighbouring going-concern passage: that rule governs, not this one
        try:
            ref = ClaimDocumentReference(
                reference_id=f'document:{document.content_hash}:liquidity:{start}',
                title=document.title or f'{ticker} {document.document_type}', provider='SEC EDGAR',
                url=document.final_url, published_at=document.published_at, section=SECTION,
                content_hash=document.content_hash, quote=quote).to_dict()
        except (TypeError, ValueError):
            continue
        value = dict(claim_kind=CLAIM_KIND, ticker=ticker, quote=quote, statement=sentence,
                     statement_offset=statement_at - start, start_offset=start, end_offset=end, document_ref=ref,
                     document_type=document.document_type, period_end=period_end)
        return [RetrievedEvidence(
            title=f'{ticker} liquidity statement · {document.published_at}',
            source='SEC EDGAR', summary=_summary(value), timestamp=document.published_at,
            url=document.final_url, relevance_score=0.97, source_type='regulatory_filing',
            source_tier='primary', claim_type='reported_fact', document_type=document.document_type,
            filed_at=document.published_at, section=SECTION, extraction_method='html',
            reporting_period_end=period_end, liquidity_statements=[value])]
    return []


def bound_liquidity_statement(item, *, ticker, cik):
    """Recheck every stored binding, the classification and the rendering."""
    from .thesis_disclosures import _business_issuer_url
    values = getattr(item, 'liquidity_statements', [])
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        return None
    value = values[0]
    try:
        ref = ClaimDocumentReference(**value['document_ref']).to_dict()
        quote, statement, offset = value['quote'], value['statement'], value['statement_offset']
        start, end = value['start_offset'], value['end_offset']
        if (value.get('claim_kind') != CLAIM_KIND or value.get('ticker') != ticker
                or type(offset) is not int or type(start) is not int or type(end) is not int
                or not isinstance(quote, str) or not isinstance(statement, str)
                or start < 0 or end - start != len(quote) or len(quote) > MAX_QUOTE_CHARS
                or offset < 0 or quote[offset:offset + len(statement)] != statement
                or (offset and not quote[offset - 1].isspace())
                or (offset + len(statement) < len(quote) and not quote[offset + len(statement)].isspace())
                or _GOING_CONCERN.search(quote)
                or quote != ref.get('quote')
                or ref.get('provider') != 'SEC EDGAR' or ref.get('section') != SECTION
                or not re.fullmatch(r'[0-9a-f]{64}', ref.get('content_hash') or '')
                or ref['reference_id'] != f'document:{ref["content_hash"]}:liquidity:{start}'
                or not _business_issuer_url(ref['url'], cik) or ref['url'] != item.url
                or ref.get('published_at') != item.timestamp or item.filed_at != item.timestamp
                or value.get('document_type') != item.document_type
                or item.document_type not in DOCUMENT_TYPES or item.section != SECTION
                or item.source != 'SEC EDGAR' or item.source_type != 'regulatory_filing'
                or item.source_tier != 'primary' or item.claim_type != 'reported_fact'
                or item.extraction_method != 'html' or item.availability_status != 'available'
                or item.freshness_status in {'unavailable', 'conflicting', 'superseded', 'stale'}
                or value.get('period_end') != item.reporting_period_end
                or not date.fromisoformat(item.reporting_period_end) <= date.fromisoformat(item.timestamp)
                    <= date.today()
                or item.summary != _summary(value)
                or classify(statement) != 'statement'
                or not dated_to_period_end(quote[:offset], item.reporting_period_end)
                or not dated_to_period_end(quote[offset + len(statement):], item.reporting_period_end)):
            return None
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    return value
