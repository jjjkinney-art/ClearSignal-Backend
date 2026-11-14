"""A current substantial-doubt going-concern disclosure, quoted as the filing states it.

Only the issuer's own present-tense conclusion that substantial doubt exists about its ability
to continue as a going concern qualifies, and only from the latest periodic filing the
metrics stage already holds (no extra request). The rule separates that from the many other
passages that mention substantial doubt and are NOT a current conclusion:

* conditional or hypothetical risk-factor language ("could raise substantial doubt");
* historical statements ("we have from time to time faced substantial doubt", past tense);
* statements that the doubt was alleviated, removed or does not exist;
* an auditor's explanatory paragraph (the auditor's opinion, not the issuer's conclusion);
* doubt about another entity (a customer, a tenant, a subsidiary).

A sentence the rule cannot classify as a current, unalleviated, issuer-owned conclusion does
not qualify: precision is preferred to recall, because a missed disclosure is a gap the
answer can state, while an overstated one is an error. The conclusion is quoted with its
adjacent sentences, verbatim, so management's own stated cash position, plans and the
dependence it describes travel with it and the quote cannot be read as stronger than the
filing writes it. The module draws no inference about likelihood or consequence.
"""
from datetime import date
import re

from ..integrity.provenance import ClaimDocumentReference
from ..schemas import RetrievedEvidence

SECTION = 'Going-concern disclosure'
DOCUMENT_TYPES = frozenset({'10-K', '10-Q', '10-K/A', '10-Q/A'})
MAX_NEIGHBOR_CHARS = 450
MAX_QUOTE_CHARS = 900

_DOUBT = re.compile(r'\bsubstantial doubt\b', re.I)
_ABILITY = re.compile(r'\bability to continue as a going concern\b', re.I)
# The issuer's own subject. "its" is allowed only when no third party appears (below).
_ISSUER_SUBJECT = re.compile(
    r"(?:\b(?:the )?(?:Company|Registrant|Group|Partnership|Trust|Corporation)(?:['’]s)?\b|\bour\b|\bwe\b|\bits\b)",
    re.I)
_THIRD_PARTY = re.compile(
    r'\b(?:customers?|tenants?|borrowers?|counterpart\w+|suppliers?|licensees?|subsidiar\w+|joint ventures?|'
    r'investees?|affiliates?|vendors?|distributors?|lessees?|issuers? of|portfolio compan\w+|acquirees?|'
    r'target compan\w+)\b', re.I)
# Present-tense assertion that the doubt exists now.
_ASSERTS = re.compile(
    r'\b(?:raises?|casts?|creates?|gives? rise to)\s+(?:a\s+)?(?:significant\s+|substantial\s+)?'
    r'(?:substantial\s+)?doubt\b'
    r'|\bthere is substantial doubt\b|\bsubstantial doubt (?:exists|remains)\b'
    r'|\b(?:have|has) concluded that (?:there is )?substantial doubt\b'
    r'|\bconcluded that substantial doubt (?:exists|remains)\b', re.I)
_CONDITIONAL = re.compile(
    r'\b(?:could|may|might|would|can|should|if|unless|whether|in the event|were to|potentially|possibility|'
    r'possible|no assurance|cannot assure|risk that|likelihood|any such)\b', re.I)
_HISTORICAL = re.compile(
    r'\b(?:from time to time|in the past|previously|historically|prior to|formerly|in prior (?:years|periods|quarters)|'
    r'(?:have|has|had) (?:faced|experienced|had|received)|periods (?:where|when|in which)|'
    r'there (?:was|were) substantial doubt|(?:raised|cast|created|expressed) substantial doubt)\b', re.I)
_ALLEVIATED = re.compile(
    r'\balleviat\w*|\bno longer\b|\b(?:do|does|did|have|has) not (?:raise|raised|exist|remain)\b|'
    r'\bno substantial doubt\b|\bnot (?:be )?(?:aware|concluded)\b|'
    r'\bhas been (?:resolved|removed|eliminated|overcome|mitigated)\b|\bovercome\b|\bmitigat\w*', re.I)
_ABOUT_DOUBT = re.compile(r'\b(?:doubt|conditions?|factors?|events?|circumstances?)\b', re.I)
_AUDITOR = re.compile(
    r'\b(?:auditors?|independent registered public accounting firm|accounting firm|audit report|'
    r'report of independent|explanatory paragraph)\b', re.I)


def classify(sentence, previous='', following=''):
    """'current' only for the issuer's present, unalleviated conclusion; else a reason.

    previous and following are the adjacent sentences (empty when absent). A neighbour that
    says the doubt was alleviated, or that no doubt exists, withdraws the conclusion.
    """
    if not isinstance(sentence, str) or not _DOUBT.search(sentence) or not _ABILITY.search(sentence):
        return 'not_a_going_concern_conclusion'
    if _AUDITOR.search(sentence):
        return 'auditor_statement'
    if _THIRD_PARTY.search(sentence) or not _ISSUER_SUBJECT.search(sentence):
        return 'other_entity_or_no_issuer_subject'
    doubt = _DOUBT.search(sentence)
    before = sentence[:doubt.start()]
    if _CONDITIONAL.search(before):
        return 'conditional'
    if _HISTORICAL.search(sentence):
        return 'historical'
    if _ALLEVIATED.search(sentence):
        return 'alleviated_or_negated'
    if not _ASSERTS.search(sentence):
        return 'no_present_assertion'
    for neighbour in (previous, following):
        if (neighbour and _ALLEVIATED.search(neighbour) and _ABOUT_DOUBT.search(neighbour)
                and not _CONDITIONAL.search(neighbour)):
            return 'alleviated_by_adjacent_sentence'
    return 'current'


def _summary(value):
    return (f'{value["ticker"]} stated in its {value["document_type"]} filed {value["document_ref"]["published_at"]}'
            f' (period ended {value["period_end"]}): “{value["quote"]}” This is the filing’s own going-concern '
            'disclosure, quoted as written. It is not an independent assessment, a prediction that operations '
            'will cease, or a statement about any period the filing does not address.')


def extract_going_concern(document, *, ticker, cik, period_end):
    """The latest periodic filing's current going-concern conclusion, or []."""
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
    for index, (offset, sentence) in enumerate(pairs):
        previous = pairs[index - 1] if index else None
        following = pairs[index + 1] if index + 1 < len(pairs) else None
        if classify(sentence, previous[1] if previous else '', following[1] if following else '') != 'current':
            continue
        # The conclusion with its adjacent sentences, as one contiguous verbatim passage.
        start, end = offset, offset + len(sentence)
        if previous and len(previous[1]) <= MAX_NEIGHBOR_CHARS and not text[previous[0] + len(previous[1]):offset].strip():
            start = previous[0]
        if following and len(following[1]) <= MAX_NEIGHBOR_CHARS and not text[end:following[0]].strip():
            end = following[0] + len(following[1])
        if end - start > MAX_QUOTE_CHARS:
            start, end = offset, offset + len(sentence)
        quote = text[start:end]
        try:
            ref = ClaimDocumentReference(
                reference_id=f'document:{document.content_hash}:going_concern:{start}',
                title=document.title or f'{ticker} {document.document_type}', provider='SEC EDGAR',
                url=document.final_url, published_at=document.published_at, section=SECTION,
                content_hash=document.content_hash, quote=quote).to_dict()
        except (TypeError, ValueError):
            continue
        value = dict(claim_kind='issuer_going_concern_disclosure', ticker=ticker, quote=quote,
                     conclusion=sentence, conclusion_offset=offset - start, start_offset=start,
                     end_offset=end, document_ref=ref, document_type=document.document_type,
                     period_end=period_end)
        return [RetrievedEvidence(
            title=f'{ticker} going-concern disclosure · {document.published_at}',
            source='SEC EDGAR', summary=_summary(value), timestamp=document.published_at,
            url=document.final_url, relevance_score=0.98, source_type='regulatory_filing',
            source_tier='primary', claim_type='reported_fact', document_type=document.document_type,
            filed_at=document.published_at, section=SECTION, extraction_method='html',
            reporting_period_end=period_end, going_concern_disclosures=[value])]
    return []


def bound_going_concern(item, *, ticker, cik):
    """Recheck every stored binding, the classification and the rendering."""
    from .thesis_disclosures import _business_issuer_url
    values = getattr(item, 'going_concern_disclosures', [])
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        return None
    value = values[0]
    try:
        ref = ClaimDocumentReference(**value['document_ref']).to_dict()
        quote, conclusion, offset = value['quote'], value['conclusion'], value['conclusion_offset']
        start, end = value['start_offset'], value['end_offset']
        if (value.get('claim_kind') != 'issuer_going_concern_disclosure' or value.get('ticker') != ticker
                or type(offset) is not int or type(start) is not int or type(end) is not int
                or not isinstance(quote, str) or not isinstance(conclusion, str)
                or start < 0 or end - start != len(quote) or len(quote) > MAX_QUOTE_CHARS
                or offset < 0 or quote[offset:offset + len(conclusion)] != conclusion
                # The conclusion is a complete sentence at exact boundaries, never a clipped one.
                or not conclusion.endswith(('.', '!', '?'))
                or (offset and not quote[offset - 1].isspace())
                or (offset + len(conclusion) < len(quote) and not quote[offset + len(conclusion)].isspace())
                or quote != ref.get('quote')
                or ref.get('provider') != 'SEC EDGAR' or ref.get('section') != SECTION
                or not re.fullmatch(r'[0-9a-f]{64}', ref.get('content_hash') or '')
                or ref['reference_id'] != f'document:{ref["content_hash"]}:going_concern:{start}'
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
                or item.summary != _summary(value)):
            return None
        # The same classification the producer applied, on the stored adjacent text.
        previous, following = quote[:offset].strip(), quote[offset + len(conclusion):].strip()
        if classify(conclusion, previous, following) != 'current':
            return None
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    return value
