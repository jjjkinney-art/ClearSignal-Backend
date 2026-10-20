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

# Explicit segment subject only: do not resolve "it", "this segment" or a
# preceding heading into an issuer-wide statement. Leading SEC BOM characters
# remain in the exact quote and offsets; this grammar does not remove them.
_NAMED_SEGMENT_COMPETITION = re.compile(
    r'^(?:\ufeff\s*)*The (?P<label>[A-Z][A-Za-z]*(?:(?: |/|-| & )[A-Za-z]+){0,5}) segment '
    r'competes (?:for its business )?(?:(?:primarily|principally) )?'
    r'(?:on the basis of|based on|with|against) \S')


def _segment_scope(quote):
    match = _NAMED_SEGMENT_COMPETITION.match(quote)
    return {'kind': 'named_segment', 'label': match['label']} if match else None


def _qualifies(quote):
    if not isinstance(quote, str) or not 40 <= len(quote) <= 450 or not quote.endswith('.'):
        return False
    # No numerical market-share claims, forecasts, or self-rated advantages.
    if re.search(r'\d|[%$€£]|\b(?:may|could|might|will|expect\w*|believe\w*|'
                 r'leading|best|superior|advantage\w*|dominant|unmatched)\b', quote, re.I):
        return False
    if re.search(r'\b(?:employees|personnel|workforce|recruit\w*|talent|'
                 r'software developers|sales professionals)\b', quote, re.I):
        return False
    return bool(_segment_scope(quote) or re.match(
        r'^We (?:(?:also|primarily|principally) )?compete (?:(?:primarily|principally) )?'
        r'(?:with|against|on the basis of|based on) \S|'
        r'^We (?:also )?face competition from \S|'
        r'^Our (?:principal|primary|main) competitors (?:are|include) \S|'
        r'^Our (?:principal|primary|main) (?:global |regional |national )?competitor'
        r'(?: for [^.;]{1,80}?)? is (?:currently )?\S|'
        r'^Competition (?:in|within|for) [^.]{3,100} (?:is based|depends) on \S', quote, re.I))


def _summary(value):
    return (f'{value["ticker"]} described competition in its {value["document_type"]} filed '
            f'{value["document_ref"]["published_at"]}: “{value["quote"]}” '
            + ('This is issuer-reported context for the named segment, not a company-wide competitive assessment; '
               if value.get('competition_scope') else 'This is issuer-reported competitive context; ')
            + 'relative strength, market share and durable advantage remain unverified.')


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
            # HTML joins a block heading to the next sentence. Strip only a
            # shared literal heading when the entire following sentence qualifies.
            heading = re.match(r'^(?:Our Competition|Competition)\s+', quote)
            if heading and _qualifies(quote[heading.end():]):
                left += heading.end()
                quote = document.text[start + left:start + right]
            if not _qualifies(quote) or quote in seen:
                continue
            scope = _segment_scope(quote)
            if scope and section != business_section_label(document.document_type, layout):
                # A third-party segment mentioned in risk prose does not gain
                # the current issuer's business-section context.
                continue
            offset = start + left
            try:
                ref = ClaimDocumentReference(
                    reference_id=f'document:{document.content_hash}:competition:{offset}',
                    title=document.title or f'{ticker} {document.document_type}', provider='SEC EDGAR',
                    url=document.final_url, published_at=document.published_at, section=section,
                    content_hash=document.content_hash, quote=quote).to_dict()
            except (TypeError, ValueError):
                # A business-section reference has a stricter quote bound than
                # risk context. Withhold this complete candidate; do not clip it
                # or discard independently validated business and risk evidence.
                continue
            value = dict(claim_kind='issuer_competition_description', ticker=ticker, quote=quote,
                         start_offset=offset, end_offset=offset + len(quote), document_ref=ref,
                         document_type=document.document_type)
            if scope:
                value['competition_scope'] = scope
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
        scope = _segment_scope(value['quote'])
        if value.get('competition_scope') != scope or (scope and
                ref['section'] != business_section_label(item.document_type, layout)):
            return None
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    return value
