"""In-memory original-source binding for a complete annual statement bridge.

Raw bytes stay in a private evidence handle, never in serialized model input.
Serialized/replayed caller descriptors alone cannot authorize this claim.
"""
from dataclasses import dataclass
from datetime import date
import json

from app.schemas import RetrievedEvidence
from app.providers.sec_cash_reconciliation import parse_cash_reconciliations
from .cash_reconciliation_source_binding import bind_cash_reconciliation

KIND = 'issuer_cash_reconciliation'
SECTION = 'Consolidated annual statement of cash flows'


@dataclass(frozen=True, repr=False)
class CashSource:
    body: bytes
    content_hash: str
    cik: str
    url: str
    filed_at: str
    title: str


def _build(source):
    if type(source) is not CashSource:
        return None
    try:
        proofs = parse_cash_reconciliations(source.body.decode('utf-8'), cik=source.cik)
        if len(proofs) != 1:
            return None
        bound = bind_cash_reconciliation(proofs[0], source_body=source.body,
            content_hash=source.content_hash, cik=source.cik, currency='USD', url=source.url,
            filed_at=source.filed_at, evaluated_at=date.today().isoformat(), title=source.title,
            document_type='10-K', availability_status='available', freshness_status='fresh')
        if bound:
            # Metadata describes checked supplied bytes, not independent origin
            # authentication or a finding that the cash drivers will persist.
            return {'claim_kind': KIND, 'bridge': bound['bridge'],
                    'row_references': bound['row_references'],
                    'document_ref': bound['row_references'][-1]['document_ref']}
    except (ValueError, TypeError, UnicodeError):
        return None
    return None


def _summary(value, ticker):
    bridge = value['bridge']
    current, prior = bridge['totals'][:2]
    def money(n):
        return ('-' if n < 0 else '') + f'${abs(n):,}'
    text = (f"{ticker} annual consolidated operating-cash reconciliation (USD), "
        f"{current['start']} to {current['end']} versus {prior['start']} to {prior['end']}, "
        f"10-K filed {value['document_ref']['published_at']}. Printed contributions "
        '(current; prior; derived change): ')
    parts = []
    for row in bridge['rows'][:-1]:
        a, b = [v['display_contribution'] for v in row['values'][:2]]
        parts.append(f"{row['label']}: {money(a)}; {money(b)}; {money(a-b)}")
    text += '. '.join(parts) + '. '
    text += (f"These rows sum exactly to reported operating cash flow of {money(current['operating_cash_flow'])} "
        f"versus {money(prior['operating_cash_flow'])}; derived change {money(bridge['operating_cash_flow_change'])}. "
        'This is statement-contribution arithmetic, not independently established causality, semantic '
        'nonoverlap, recurrence or normalized cash generation. Taxonomy signs are retained separately '
        'from printed cash contributions. Noncash reconciliation adjustments are not new cash payments '
        'or additional losses. Annual evidence does not explain later interim movements; investing '
        'and financing flows remain separate.')
    return text


def extract_cash_reconciliation(document, *, ticker, cik):
    source = getattr(document, 'cash_reconciliation_source', None)
    if (type(source) is not CashSource or source.cik != cik
            or document.document_type != '10-K' or document.publisher != 'SEC EDGAR'
            or document.source_type != 'regulatory_filing' or document.source_tier != 'primary'
            or document.extraction_method != 'html' or not document.text_ready
            or (source.content_hash, source.url, source.filed_at) !=
               (document.content_hash, document.final_url, document.published_at)):
        return []
    value = _build(source)
    if not value:
        return []
    current = value['bridge']['totals'][0]
    item = RetrievedEvidence(title=f'{ticker} annual operating cash reconciliation', source='SEC EDGAR',
        summary=_summary(value, ticker), timestamp=source.filed_at, url=source.url,
        relevance_score=0.96, source_type='regulatory_filing', source_tier='primary',
        claim_type='reported_fact', document_type='10-K', filed_at=source.filed_at,
        section=SECTION, extraction_method='html', reporting_period_start=current['start'],
        reporting_period_end=current['end'], cash_reconciliation_disclosures=[value])
    item._cash_reconciliation_source = source
    return [item]


def bound_cash_reconciliation(item, *, ticker, cik):
    source = getattr(item, '_cash_reconciliation_source', None)
    values = getattr(item, 'cash_reconciliation_disclosures', [])
    if (type(source) is not CashSource or source.cik != cik
            or not isinstance(values, list) or len(values) != 1):
        return None
    rebuilt = _build(source)
    if not rebuilt:
        return None
    try:
        current = rebuilt['bridge']['totals'][0]
        if (json.dumps(values[0], sort_keys=True, allow_nan=False) != json.dumps(rebuilt, sort_keys=True, allow_nan=False)
                or item.summary != _summary(rebuilt, ticker) or item.source != 'SEC EDGAR'
                or item.timestamp != source.filed_at or item.filed_at != source.filed_at or item.url != source.url
                or item.document_type != '10-K' or item.source_type != 'regulatory_filing'
                or item.source_tier != 'primary' or item.section != SECTION or item.extraction_method != 'html'
                or item.reporting_period_start != current['start'] or item.reporting_period_end != current['end']
                or item.availability_status != 'available'
                or item.freshness_status in {'stale', 'conflicting', 'superseded', 'unavailable'}):
            return None
        return {**rebuilt, 'quote': rebuilt['document_ref']['quote']}
    except (TypeError, ValueError, AttributeError):
        return None
