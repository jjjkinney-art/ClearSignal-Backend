"""Historical segment order context with exact printed amounts and definition.

No currency-code inference, numeric normalization, comparisons or forecasts.
"""
from datetime import date
from itertools import islice
import json
import re

from ..integrity.provenance import ClaimDocumentReference
from ..schemas import RetrievedEvidence
from .reviewed_annual_layouts import reviewed_annual_layout, layout_binding
from .sec_risk_sections import complete_business_window, business_section_label, risk_sentence_spans

_AMOUNT = r'\$(?:0|[1-9]\d{0,2}(?:,\d{3})+|[1-9]\d{0,11})(?:\.\d{1,2})?'
_MONTHS = ('January', 'February', 'March', 'April', 'May', 'June', 'July',
           'August', 'September', 'October', 'November', 'December')
_CONTEXT = re.compile(
    r'^(?:\ufeff\s*)*The contract backlog of the '
    r'(?P<label>[A-Z][A-Za-z]*(?:(?: |/|-| & )[A-Za-z]+){0,5}) segment was '
    r'(?P<approximation>approximately )?'
    rf'(?P<v0>{_AMOUNT}), (?P<v1>{_AMOUNT}), and (?P<v2>{_AMOUNT}) at '
    r'(?P<month>' + '|'.join(_MONTHS) + r') (?P<day>\d{1,2}), '
    r'(?P<y0>\d{4}), (?P<y1>\d{4}), and (?P<y2>\d{4}), respectively\. '
    r'Backlog is defined as the value of orders from the customer less the amount '
    r'of sales recognized against the orders\.$')


def parse_order_context(quote):
    """Reconstruct source-spelled rows only; unknown currency stays unknown."""
    if not isinstance(quote, str) or not 100 <= len(quote) <= 300:
        return None
    match = _CONTEXT.fullmatch(quote)
    if not match:
        return None
    try:
        years = [int(match[f'y{i}']) for i in range(3)]
        if not (years[0] > years[1] > years[2] >= 1900):
            return None
        dates = [date(year, _MONTHS.index(match['month']) + 1, int(match['day'])) for year in years]
    except ValueError:
        return None
    return {
        'scope': {'kind': 'named_segment', 'label': match['label']},
        'metric': 'contract backlog',
        'observations': [{'as_of': day.isoformat(), 'reported_amount': match[f'v{i}']}
                         for i, day in enumerate(dates)],
        'approximate': bool(match['approximation']),
        'currency_code': None, 'reported_currency_symbol': '$',
        'definition': 'Backlog is defined as the value of orders from the customer less the amount of sales recognized against the orders.',
        'numeric_normalization_performed': False,
    }


def _summary(value):
    return (f'{value["ticker"]} reported historical segment contract backlog in its '
            f'{value["document_type"]} filed {value["document_ref"]["published_at"]}: '
            f'“{value["quote"]}” This is dated order context for the named segment, '
            'not recognized revenue or a forecast. Amounts retain the printed dollar '
            'symbol; the currency code is not established by this excerpt. Revenue '
            'conversion, delivery timing, cancellations and profitability remain unverified. '
            'No growth rate, valuation signal or company-wide importance is inferred.')


def extract_order_context(document, *, ticker, cik):
    from .thesis_disclosures import _business_issuer_url
    if (document.document_type not in {'10-K', '20-F'} or document.publisher != 'SEC EDGAR'
            or document.source_type != 'regulatory_filing' or document.source_tier != 'primary'
            or document.extraction_method != 'html' or not document.text_ready
            or not _business_issuer_url(document.final_url, cik)
            or not re.fullmatch(r'[0-9a-f]{64}', document.content_hash or '')):
        return []
    try:
        filed = date.fromisoformat(document.published_at or '')
        if filed > date.today():
            return []
    except (TypeError, ValueError):
        return []
    layout = reviewed_annual_layout(document.final_url, document.document_type, document.published_at,
        content_hash=document.content_hash, canonical_content_hash=document.canonical_content_hash, cik=cik)
    window = complete_business_window(document.text, form=document.document_type, layout=layout)
    if not window:
        return []
    start, end = window
    spans = list(islice(risk_sentence_spans(document.text[start:end]), 2000))
    for (left, _), (_, right) in zip(spans, spans[1:]):
        # Exactly two adjacent complete sentences, including the definition.
        # Never remove a substantive intervening clause or append a forecast.
        quote = document.text[start + left:start + right]
        context = parse_order_context(quote)
        if not context or date.fromisoformat(context['observations'][0]['as_of']) > filed:
            continue
        offset = start + left
        try:
            ref = ClaimDocumentReference(reference_id=f'document:{document.content_hash}:order_context:{offset}',
                title=document.title or f'{ticker} {document.document_type}', provider='SEC EDGAR',
                url=document.final_url, published_at=document.published_at,
                section=business_section_label(document.document_type, layout),
                content_hash=document.content_hash, quote=quote).to_dict()
        except (TypeError, ValueError):
            continue
        value = {'claim_kind': 'issuer_order_backlog_context', 'ticker': ticker,
                 'quote': quote, 'start_offset': offset, 'end_offset': offset + len(quote),
                 'document_ref': ref, 'document_type': document.document_type, 'order_context': context}
        if layout:
            value['reviewed_layout'] = layout_binding(layout, document.content_hash)
        # One bounded order excerpt per already retrieved annual document.
        return [RetrievedEvidence(title=f'{ticker} historical segment order context · {document.published_at}',
            source='SEC EDGAR', summary=_summary(value), timestamp=document.published_at,
            url=document.final_url, relevance_score=0.96, source_type='regulatory_filing',
            source_tier='primary', claim_type='reported_fact', document_type=document.document_type,
            filed_at=document.published_at, section=ref['section'], extraction_method='html',
            operating_disclosures=[value])]
    return []


def bound_order_context(item, *, ticker, cik):
    from .thesis_disclosures import _business_issuer_url
    values = getattr(item, 'operating_disclosures', [])
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        return None
    value = values[0]
    try:
        context = parse_order_context(value['quote'])
        ref = ClaimDocumentReference(**value['document_ref']).to_dict()
        start, end = value['start_offset'], value['end_offset']
        binding = value.get('reviewed_layout')
        if binding is not None and (not isinstance(binding, dict) or binding.get('raw_content_hash') != ref.get('content_hash')):
            return None
        layout = reviewed_annual_layout(item.url, item.document_type, item.timestamp,
            content_hash=ref.get('content_hash'),
            canonical_content_hash=binding.get('canonical_content_hash') if binding else None, cik=cik)
        if (layout is not None and binding is None) or (binding is not None and (
                not layout or binding != layout_binding(layout, ref.get('content_hash')))):
            return None
        section = business_section_label(item.document_type, layout)
        if (not context or json.dumps(value.get('order_context'), sort_keys=True, allow_nan=False)
                != json.dumps(context, sort_keys=True, allow_nan=False)
                or value.get('claim_kind') != 'issuer_order_backlog_context' or value.get('ticker') != ticker
                or value['document_type'] != item.document_type or item.document_type not in {'10-K', '20-F'}
                or ref['quote'] != value['quote'] or ref['provider'] != 'SEC EDGAR'
                or not re.fullmatch(r'[0-9a-f]{64}', ref.get('content_hash', ''))
                or not _business_issuer_url(ref['url'], cik) or ref['url'] != item.url
                or ref['published_at'] != item.timestamp or ref.get('section') != section or item.section != section
                or item.filed_at != item.timestamp
                or item.reporting_period_start is not None or item.reporting_period_end is not None
                or date.fromisoformat(item.timestamp) > date.today()
                or date.fromisoformat(context['observations'][0]['as_of']) > date.fromisoformat(item.timestamp)
                or type(start) is not int or type(end) is not int or start < 0 or end - start != len(value['quote'])
                or ref['reference_id'] != f'document:{ref["content_hash"]}:order_context:{start}'
                or item.source != 'SEC EDGAR' or item.source_type != 'regulatory_filing'
                or item.source_tier != 'primary' or item.claim_type != 'reported_fact'
                or item.extraction_method != 'html' or item.availability_status != 'available'
                or item.freshness_status in {'unavailable', 'conflicting', 'superseded', 'stale'}
                or item.summary != _summary(value)):
            return None
    except (KeyError, ValueError, TypeError, AttributeError):
        return None
    return value
