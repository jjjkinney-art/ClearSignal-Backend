"""Complete product lists under explicit segment headings; no revenue inference."""
from datetime import date
from itertools import islice
import json
import re

from ..integrity.provenance import ClaimDocumentReference
from ..schemas import RetrievedEvidence
from .sec_risk_sections import complete_business_window, risk_sentence_spans

SECTION = 'Item 1. Business - Reported segment products'
PRODUCTS = re.compile(
    r'^(?:\ufeff\s*)*(?P<ordinal>[1-9][0-9]?)\. '
    r'(?P<label>[A-Z][A-Za-z]*(?:(?: |/|-| & )[A-Za-z]+){0,5}) Segment '
    r'(?P<statement>[A-Z][A-Za-z /&-]{2,99} (?:sold|manufactured|offered) by the segment '
    r'(?:include|comprise) (?P<products>[^.]{30,750})\.)$')


def parse_product_context(quote):
    if not isinstance(quote, str) or not 80 <= len(quote) <= 900:
        return None
    match = PRODUCTS.fullmatch(quote)
    if not match or match['label'].lower() in {'the', 'this', 'our', 'its', 'that'}:
        return None
    from .thesis_disclosures import _BUSINESS_ASPIRATION_OR_PROMOTION
    statement = match['statement']
    if (re.search(r'\d|[%$€£]|\b(?:will|may|could|expect\w*|leading|best|superior|'
                  r'future|forecast\w*|revenue|profit\w*|margin\w*|employees|workforce|'
                  r'we|our|it|which|because|although|while|enrich\w*|empower\w*|'
                  r'innovative|reliable|unmatched|easier|enjoyable|improv\w*|enhanc\w*)\b', statement, re.I)
            or _BUSINESS_ASPIRATION_OR_PROMOTION.search(statement)
            or not (';' in match['products'] or match['products'].count(',') >= 2)):
        return None
    return {'scope': {'kind': 'named_segment', 'label': match['label']},
            'heading': match['ordinal'] + '. ' + match['label'] + ' Segment',
            'statement': statement, 'reported_product_list': match['products'],
            'revenue_inference_performed': False}


def _summary(value):
    return (f"{value['ticker']} reported products for the named {value['product_context']['scope']['label']} "
            f"segment in its 10-K filed {value['document_ref']['published_at']}: “{value['quote']}” "
            'This is a sampled, source-reported segment product list, not a complete issuer business model. '
            'Revenue contribution, ownership, competitive advantage and future performance are not established by this list.')


def extract_segment_products(document, *, ticker, cik):
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
    window = complete_business_window(document.text, form='10-K')
    if not window:
        return []
    start, end = window
    spans = list(islice(risk_sentence_spans(document.text[start:end]), 2000))
    candidates = []
    for (left, _), (_, right) in zip(spans, spans[1:]):
        quote = document.text[start + left:start + right]
        context = parse_product_context(quote)
        if context:
            candidates.append((start + left, quote, context))
    # One sampled list; source order is not a materiality ranking. Duplicate
    # eligible headings for a segment are ambiguous rather than first-wins.
    for offset, quote, context in candidates:
        if sum(c['scope']['label'] == context['scope']['label'] for _, _, c in candidates) != 1:
            continue
        try:
            ref = ClaimDocumentReference(reference_id=f'document:{document.content_hash}:segment_products:{offset}',
                title=document.title or f'{ticker} 10-K', provider='SEC EDGAR',
                url=document.final_url, published_at=document.published_at, section=SECTION,
                content_hash=document.content_hash, quote=quote).to_dict()
        except (TypeError, ValueError):
            continue
        value = {'claim_kind': 'issuer_segment_product_context', 'ticker': ticker,
                 'quote': quote, 'start_offset': offset, 'end_offset': offset + len(quote),
                 'document_ref': ref, 'product_context': context}
        item = RetrievedEvidence(title=f'{ticker} reported segment products', source='SEC EDGAR',
            summary=_summary(value), timestamp=document.published_at, url=document.final_url,
            relevance_score=0.96, source_type='regulatory_filing', source_tier='primary',
            claim_type='reported_fact', document_type='10-K', filed_at=document.published_at,
            section=SECTION, extraction_method='html', product_disclosures=[value])
        if bound_segment_products(item, ticker=ticker, cik=cik):
            return [item]
    return []


def bound_segment_products(item, *, ticker, cik):
    from .thesis_disclosures import _business_issuer_url
    values = getattr(item, 'product_disclosures', [])
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        return None
    value = values[0]
    try:
        context = parse_product_context(value['quote'])
        ref = ClaimDocumentReference(**value['document_ref']).to_dict()
        start, end = value['start_offset'], value['end_offset']
        if (not context or json.dumps(value.get('product_context'), sort_keys=True, allow_nan=False)
                != json.dumps(context, sort_keys=True, allow_nan=False)
                or value.get('claim_kind') != 'issuer_segment_product_context' or value.get('ticker') != ticker
                or ref['quote'] != value['quote'] or ref['provider'] != 'SEC EDGAR'
                or not re.fullmatch(r'[0-9a-f]{64}', ref.get('content_hash', ''))
                or ref['url'] != item.url or not _business_issuer_url(item.url, cik)
                or ref['published_at'] != item.timestamp or item.filed_at != item.timestamp
                or ref.get('section') != SECTION or item.section != SECTION
                or type(start) is not int or type(end) is not int or not 0 <= start < end <= 360_000
                or end-start != len(value['quote'])
                or ref['reference_id'] != f'document:{ref["content_hash"]}:segment_products:{start}'
                or date.fromisoformat(item.timestamp) > date.today()
                or item.source != 'SEC EDGAR' or item.source_type != 'regulatory_filing'
                or item.source_tier != 'primary' or item.claim_type != 'reported_fact'
                or item.document_type != '10-K' or item.extraction_method != 'html'
                or item.reporting_period_start is not None or item.reporting_period_end is not None
                or item.availability_status != 'available'
                or item.freshness_status in {'unavailable', 'conflicting', 'superseded', 'stale'}
                or item.summary != _summary(value)):
            return None
        return value
    except (KeyError, ValueError, TypeError, AttributeError):
        return None
