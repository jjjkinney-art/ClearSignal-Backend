"""Exact current-issuer competition descriptions, without moat conclusions."""
from datetime import date
from itertools import islice
import re

from ..integrity.provenance import ClaimDocumentReference
from ..schemas import RetrievedEvidence
from .reviewed_annual_layouts import reviewed_annual_layout, layout_binding
from .sec_risk_sections import (
    complete_business_window, business_section_label, risk_section_spans,
    risk_section_label, risk_sentence_spans, MAX_ISSUER_RISK_SECTION_CHARS,
)


def _qualifies(quote):
    if not isinstance(quote, str) or not 40 <= len(quote) <= 450 or not quote.endswith('.'):
        return False
    # No numerical market-share claims, forecasts, or self-rated advantages.
    if re.search(r'\d|[%$€£]|\b(?:may|could|might|will|expect\w*|believe\w*|'
                 r'leading|best|superior|advantage\w*|dominant|unmatched)\b', quote, re.I):
        return False
    return bool(re.match(
        r'^We (?:(?:also|primarily|principally) )?compete (?:(?:primarily|principally) )?'
        r'(?:with|against|on the basis of|based on) \S|'
        r'^Our (?:principal|primary|main) competitors (?:are|include) \S|'
        r'^Competition (?:in|within|for) [^.]{3,100} (?:is based|depends) on \S', quote, re.I))


def _summary(value):
    return (f'{value["ticker"]} described competition in its {value["document_type"]} filed '
            f'{value["document_ref"]["published_at"]}: “{value["quote"]}” '
            'This is issuer-reported competitive context; relative strength, market share and durable advantage remain unverified.')


def extract_competition_descriptions(document, *, ticker, cik):
    from .thesis_disclosures import _business_issuer_url
    if (document.document_type not in {'10-K', '20-F'} or document.publisher != 'SEC EDGAR'
            or document.source_type != 'regulatory_filing' or document.source_tier != 'primary'
            or document.extraction_method != 'html' or not document.text_ready
            or not _business_issuer_url(document.final_url, cik)
            or not re.fullmatch(r'[0-9a-f]{64}', document.content_hash or '')):
        return []
    try:
        if date.fromisoformat(document.published_at or '') > date.today():
            return []
    except (TypeError, ValueError):
        return []
    layout = reviewed_annual_layout(document.final_url, document.document_type, document.published_at,
        content_hash=document.content_hash, canonical_content_hash=document.canonical_content_hash, cik=cik)
    windows = []
    business = complete_business_window(document.text, form=document.document_type, layout=layout)
    if business:
        windows.append((*business, business_section_label(document.document_type, layout)))
    risk_section = layout['section'] if layout else risk_section_label(document.document_type)
    windows.extend((left, right, risk_section) for left, right in
        risk_section_spans(document.text, form=document.document_type, layout=layout,
                           max_section_chars=MAX_ISSUER_RISK_SECTION_CHARS))
    result, seen = [], set()
    for start, end, section in windows:
        for left, right in islice(risk_sentence_spans(document.text[start:end]), 2000):
            quote = document.text[start + left:start + right]
            if not _qualifies(quote) or quote in seen:
                continue
            offset = start + left
            ref = ClaimDocumentReference(
                reference_id=f'document:{document.content_hash}:competition:{offset}',
                title=document.title or f'{ticker} {document.document_type}', provider='SEC EDGAR',
                url=document.final_url, published_at=document.published_at, section=section,
                content_hash=document.content_hash, quote=quote).to_dict()
            value = dict(claim_kind='issuer_competition_description', ticker=ticker, quote=quote,
                         start_offset=offset, end_offset=offset + len(quote), document_ref=ref,
                         document_type=document.document_type)
            if layout:
                value['reviewed_layout'] = layout_binding(layout, document.content_hash)
            result.append(RetrievedEvidence(
                title=f'{ticker} competition description · {document.published_at} · {len(result)+1}',
                source='SEC EDGAR', summary=_summary(value), timestamp=document.published_at,
                url=document.final_url, relevance_score=0.96, source_type='regulatory_filing',
                source_tier='primary', claim_type='reported_fact', document_type=document.document_type,
                filed_at=document.published_at, section=section, extraction_method='html',
                competition_disclosures=[value]))
            seen.add(quote)
            if len(result) == 2:
                return result
    return result


def bound_competition_description(item, *, ticker, cik):
    from .thesis_disclosures import _business_issuer_url
    values = getattr(item, 'competition_disclosures', [])
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        return None
    value = values[0]
    try:
        ref = ClaimDocumentReference(**value['document_ref']).to_dict()
        start, end = value['start_offset'], value['end_offset']
        binding = value.get('reviewed_layout')
        if binding is not None and (not isinstance(binding, dict)
                or binding.get('raw_content_hash') != ref.get('content_hash')):
            return None
        layout = reviewed_annual_layout(item.url, item.document_type, item.timestamp,
            content_hash=ref.get('content_hash'), cik=cik,
            canonical_content_hash=binding.get('canonical_content_hash') if binding else None)
        if (layout is not None and binding is None) or (binding is not None and
                (not layout or binding != layout_binding(layout, ref.get('content_hash')))):
            return None
        sections = {business_section_label(item.document_type, layout),
                    layout['section'] if layout else risk_section_label(item.document_type)}
        if (value.get('claim_kind') != 'issuer_competition_description' or value.get('ticker') != ticker
                or not _qualifies(value.get('quote')) or value['quote'] != ref.get('quote')
                or ref.get('provider') != 'SEC EDGAR' or ref.get('section') not in sections
                or not re.fullmatch(r'[0-9a-f]{64}', ref.get('content_hash') or '')
                or not _business_issuer_url(ref['url'], cik) or ref['url'] != item.url
                or ref.get('published_at') != item.timestamp or item.filed_at != item.timestamp
                or date.fromisoformat(item.timestamp) > date.today()
                or type(start) is not int or type(end) is not int or start < 0
                or end - start != len(value['quote'])
                or ref['reference_id'] != f'document:{ref["content_hash"]}:competition:{start}'
                or item.source != 'SEC EDGAR' or item.source_type != 'regulatory_filing'
                or item.source_tier != 'primary' or item.claim_type != 'reported_fact'
                or item.document_type not in {'10-K', '20-F'}
                or value.get('document_type') != item.document_type or item.section != ref['section']
                or item.extraction_method != 'html'
                or item.freshness_status in {'unavailable', 'conflicting', 'superseded', 'stale'}
                or item.availability_status != 'available' or item.summary != _summary(value)):
            return None
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    return value
