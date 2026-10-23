"""Source-attributed organisation activities; discussion placement is not ownership."""
from datetime import date, datetime
import hashlib
import json
import re

from ..integrity.provenance import ClaimDocumentReference
from ..schemas import RetrievedEvidence
from .sec_risk_sections import business_section_bounds, risk_sentence_spans

SECTION = 'Item 1. Business - Reported organisation activities'
LABEL = r'[A-Z][A-Za-z]*(?:(?: |/|-| & )[A-Za-z]+){0,5}'
HEADING = re.compile(r'^(?:\ufeff\s*)*([1-9][0-9]?)\.$')
SEGMENT = re.compile(r'^(?P<label>' + LABEL + r') Segment(?: |$)')
ACTIVITY = re.compile(
    r'^(?:\ufeff\s*)*(?P<name>[A-Z][A-Za-z &-]{1,90} (?:Corporation|Inc\.|LLC|Ltd\.|Limited)) '
    r'\("(?P<alias>[A-Z][A-Za-z -]{1,40})"\) '
    r'(?:(?:was acquired on (?P<acquired>[A-Z][a-z]+ [0-9]{1,2}, [0-9]{4}), and )?)'
    r'manufactures (?P<products>[^.;]{8,450}) for (?P<customers>[^.;]{8,300})\.$')
DISPOSITION = re.compile(r'\b(?:divest\w*|sold|sell\w*|sale|dispos\w*|discontinu\w*|ceas\w*|'
                         r'merg\w*|rename\w*|transfer\w*|liquidat\w*)\b', re.I)
UNSUPPORTED = re.compile(r'[%$€£]|\b(?:will|may|could|expect\w*|forecast\w*|revenue|profit\w*|margin\w*|'
    r'competitor\w*|leading|best|superior|innovative|reliable|unmatched|because|although|while|'
    r'which|whose|employee\w*|workforce|facility|facilities|square|feet|acres|capacity|'
    r'future|not|no|never|previous\w*|historical\w*|formerly|used to|we|our|its|their)\b', re.I)


def parse_activity(quote):
    """A deliberately bounded grammar; names/products/segments are never allowlisted."""
    if not isinstance(quote, str) or not 60 <= len(quote) <= 900:
        return None
    m = ACTIVITY.fullmatch(quote)
    if not m or m['alias'].lower() in {'it', 'this', 'that', 'company', 'segment', 'our', 'the'}:
        return None
    if m['acquired']:
        try:
            acquired = datetime.strptime(m['acquired'], '%B %d, %Y').date().isoformat()
        except ValueError:
            return None
    else:
        acquired = None
    activity = m['products'] + ' for ' + m['customers']
    from .thesis_disclosures import _BUSINESS_ASPIRATION_OR_PROMOTION
    if UNSUPPORTED.search(activity) or _BUSINESS_ASPIRATION_OR_PROMOTION.search(activity):
        return None
    # Only explicit millimetre product specifications are supported initially.
    # Acquisition dates are a separate grammatical role; amounts, facility area,
    # awards and delivery years never pass via a generic numeric exemption.
    if re.search(r'\d', re.sub(r'(?<![\w.])\d+(?:\.\d+)?mm\b', '', activity)):
        return None
    expansions = {}
    for expansion in re.finditer(r'(?P<name>[A-Z][A-Za-z ]{3,100}) \((?P<acronym>[A-Z]{2,8})\)', m['customers']):
        name = expansion['name'].strip()
        acronym = expansion['acronym']
        if acronym in expansions:
            return None
        expansions[acronym] = name
    acronyms = set(re.findall(r'\b[A-Z]{2,}\b', activity))
    if acronyms - expansions.keys():
        return None
    return {'organisation_name': m['name'], 'source_alias': m['alias'],
            'statement': quote, 'products': m['products'], 'customers': m['customers'],
            'customer_acronym_expansions': expansions, 'reported_acquisition_date': acquired,
            'acquirer': 'not_established', 'current_status': 'not_established',
            'issuer_ownership': 'not_established', 'revenue_inference_performed': False}


def reconstruct(proof):
    """Re-run boundaries, entity grammar and disposition checks from complete proof."""
    if not isinstance(proof, dict) or set(proof) != {'text', 'start_offset', 'text_sha256'}:
        return []
    text, origin = proof['text'], proof['start_offset']
    if (not isinstance(text, str) or not 50 <= len(text) <= 160_000
            or type(origin) is not int or not 0 <= origin <= 360_000 - len(text)
            or hashlib.sha256(text.encode()).hexdigest() != proof['text_sha256']):
        return []
    bounds = business_section_bounds(text, form='10-K')
    if not bounds or bounds[0] != 0 or bounds[3] != len(text):
        return []
    _, a, z, _ = bounds
    spans = [(a+i,a+j) for i,j in risk_sentence_spans(text[a:z])]
    if len(spans) > 2000:
        return []
    headings = []
    for (left, right), (next_left, next_right) in zip(spans, spans[1:]):
        ordinal = HEADING.fullmatch(text[left:right])
        label = SEGMENT.match(text[next_left:next_right])
        if ordinal and label:
            headings.append({'ordinal': int(ordinal[1]), 'label': label['label'],
                'start': left, 'body_start': next_left,
                'heading_end': next_left + label.end() - (1 if text[next_left:next_right][label.end()-1:label.end()] == ' ' else 0)})
    if (not 2 <= len(headings) <= 12 or [h['ordinal'] for h in headings] != list(range(1,len(headings)+1))
            or len({h['label'] for h in headings}) != len(headings)):
        return []
    candidates = []
    for heading in headings:
        # Any next numbered heading closes the discussion, including general
        # Business subsections that are not themselves named segments.
        closing = next((left for left, right in spans
            if left > heading['body_start'] and HEADING.fullmatch(text[left:right])), z)
        for left, right in spans:
            if left < heading['body_start'] or right > closing:
                continue
            quote = text[left:right]
            context = parse_activity(quote)
            if not context:
                continue
            alias = re.compile(r'(?<!\w)' + re.escape(context['source_alias']) + r'(?!\w)', re.I)
            legal = context['organisation_name'].lower()
            mentions = [text[i:j] for i,j in spans if alias.search(text[i:j]) or legal in text[i:j].lower()]
            former_owner = re.compile(r'(?:formerly|previously) (?:owned|operated) by (?:'
                + re.escape(context['organisation_name']) + '|' + re.escape(context['source_alias']) + r')(?!\w)', re.I)
            if any(DISPOSITION.search(mention) or former_owner.search(mention) for mention in mentions):
                continue
            # An alias defined more than once, or for another organisation, is
            # ambiguous. No cross-sentence alias/pronoun resolution is attempted.
            alias_definition = '("' + context['source_alias'] + '")'
            if len(re.findall(re.escape(alias_definition), text, re.I)) != 1:
                continue
            context['scope'] = {'kind': 'organisation_in_segment_discussion', 'segment_label': heading['label']}
            context['disposition_check'] = 'no_explicit_named_disposition_found_in_complete_business_section'
            candidates.append({'quote': quote, 'start_offset': origin+left, 'end_offset': origin+right,
                'organisation_context': context,
                'heading_quote': text[heading['start']:heading['heading_end']],
                'heading_start_offset': origin+heading['start'],
                'segment_end_offset': origin+closing})
    return candidates


def _summary(value):
    c = value['organisation_context']
    return (f"{value['ticker']} described {c['organisation_name']} in its {c['scope']['segment_label']} segment discussion "
        f"in the 10-K filed {value['document_ref']['published_at']}: “{value['quote']}” "
        'This is a sampled issuer-attributed organisation activity statement. Current operations and issuer ownership '
        'are not established; acquisition wording does not identify an acquirer. Product specifications are source literals, '
        'not financial measurements. Revenue contribution, competitive advantage and complete company coverage remain unverified.')


def extract_organisation_activities(document, *, ticker, cik):
    from .thesis_disclosures import _business_issuer_url
    if (document.document_type != '10-K' or document.publisher != 'SEC EDGAR'
            or document.source_type != 'regulatory_filing' or document.source_tier != 'primary'
            or document.extraction_method != 'html' or not document.text_ready
            or not _business_issuer_url(document.final_url, cik)):
        return []
    try:
        if date.fromisoformat(document.published_at or '') > date.today():
            return []
    except (TypeError, ValueError):
        return []
    bounds = business_section_bounds(document.text, form='10-K')
    if not bounds:
        return []
    start, _, _, end = bounds
    text = document.text[start:end]
    proof = {'text': text, 'start_offset': start, 'text_sha256': hashlib.sha256(text.encode()).hexdigest()}
    for candidate in reconstruct(proof):
        if (candidate['organisation_context']['reported_acquisition_date'] or '0001-01-01') > document.published_at:
            continue
        offset = candidate['start_offset']
        try:
            ref = ClaimDocumentReference(reference_id=f'document:{document.content_hash}:organisation_activity:{offset}',
                title=document.title or f'{ticker} 10-K', provider='SEC EDGAR', url=document.final_url,
                published_at=document.published_at, section=SECTION, content_hash=document.content_hash,
                quote=candidate['quote']).to_dict()
        except (TypeError, ValueError):
            continue
        value = {**candidate, 'claim_kind': 'issuer_organisation_activity_context', 'ticker': ticker,
                 'document_ref': ref, 'business_source_proof': proof}
        item = RetrievedEvidence(title=f'{ticker} reported organisation activities', source='SEC EDGAR',
            summary=_summary(value), timestamp=document.published_at, url=document.final_url,
            relevance_score=0.96, source_type='regulatory_filing', source_tier='primary', claim_type='reported_fact',
            document_type='10-K', filed_at=document.published_at, section=SECTION, extraction_method='html',
            organisation_disclosures=[value])
        if bound_organisation_activity(item, ticker=ticker, cik=cik):
            return [item]
    return []


def bound_organisation_activity(item, *, ticker, cik):
    from .thesis_disclosures import _business_issuer_url
    values = getattr(item, 'organisation_disclosures', [])
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        return None
    value = values[0]
    try:
        candidates = reconstruct(value['business_source_proof'])
        fields = {'quote','start_offset','end_offset','organisation_context','heading_quote','heading_start_offset','segment_end_offset'}
        selected = {k: value[k] for k in fields}
        if not any(json.dumps(c, sort_keys=True, allow_nan=False) == json.dumps(selected, sort_keys=True, allow_nan=False) for c in candidates):
            return None
        ref = ClaimDocumentReference(**value['document_ref']).to_dict()
        if (value['claim_kind'] != 'issuer_organisation_activity_context' or value['ticker'] != ticker
                or ref['quote'] != value['quote'] or ref['provider'] != 'SEC EDGAR'
                or not re.fullmatch(r'[0-9a-f]{64}', ref.get('content_hash', ''))
                or ref['url'] != item.url or not _business_issuer_url(item.url, cik)
                or ref['published_at'] != item.timestamp or item.filed_at != item.timestamp
                or ref.get('section') != SECTION or item.section != SECTION
                or ref['reference_id'] != f'document:{ref["content_hash"]}:organisation_activity:{value["start_offset"]}'
                or date.fromisoformat(item.timestamp) > date.today()
                or (value['organisation_context']['reported_acquisition_date'] or '0001-01-01') > item.timestamp
                or item.source != 'SEC EDGAR' or item.source_type != 'regulatory_filing'
                or item.source_tier != 'primary' or item.claim_type != 'reported_fact'
                or item.document_type != '10-K' or item.extraction_method != 'html'
                or item.reporting_period_start is not None or item.reporting_period_end is not None
                or item.availability_status != 'available'
                or item.freshness_status in {'unavailable','conflicting','superseded','stale'}
                or item.summary != _summary(value)):
            return None
        return value
    except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
        return None
