"""Dated, source-bound annual segment results, separate from consolidated facts."""
from datetime import date
import json
import re

from ..integrity.provenance import ClaimDocumentReference
from ..providers.sec_segment_facts import reconstruct
from ..schemas import RetrievedEvidence
from .segment_analysis import segment_analysis

SECTION = 'Annual segment financial table'


def _rows(proof, cik):
    rows = reconstruct(proof, cik=cik)
    if rows is None or len({(r['start'], r['end']) for r in rows}) != 1:
        return None
    return rows


def _summary(value):
    rows = value['segment_context']['segments']
    text = (f"{value['ticker']} reported annual segment results for {rows[0]['start']} to {rows[0]['end']} "
            f"in its {value['document_type']} filed {value['document_ref']['published_at']} (USD; amounts below are expanded from the filing's thousands scale). ")
    text += ' '.join(f"{r['label']}: external revenue ${r['revenue_usd']:,}; operating "
                     + (f"loss ${abs(r['operating_income_usd']):,}." if r['operating_income_usd'] < 0
                        else f"profit ${r['operating_income_usd']:,}.") for r in rows)
    summary = (text + ' ' + value['proof']['definition'] + ' ' + value['proof']['allocation']
            + ' These are reported segment results with the stated allocation; they do not establish standalone economics. '
            + ('No revenue share, margin, growth rate, operating driver, valuation or future performance is inferred. '
               'Reported totals and completeness of segment coverage have not been independently reconciled.'
               if value['segment_context']['analysis']['status'] == 'unavailable' else
               'Any percentage relationships are separate calculations from the cited amounts; the allocation caveat remains material.'))
    for explanation in value.get('sales_explanations', []):
        summary += (f" For {explanation['current_start']} to {explanation['current_end']} compared with "
                    f"{explanation['prior_start']} to {explanation['prior_end']}, management stated: "
                    + explanation['quote'] + ' ' + explanation['limitation'])
    return summary


def _explanation_fields(proof, source, ref, cik):
    try:
        return _build_explanation_fields(proof, source, ref, cik)
    except (KeyError, ValueError, TypeError, AttributeError):
        return None


def _build_explanation_fields(proof, source, ref, cik):
    from .segment_sales_explanations import explanations
    values = explanations(proof, source, cik=cik)
    if not values:
        return None
    refs = []
    for value in values:
        refs.append(ClaimDocumentReference(**{**ref, 'reference_id': ref['reference_id'] + f":sales_explanation:{value['start_offset']}",
                     'section': 'Item 7. Management discussion and analysis',
                     'quote': value['quote']}).to_dict())
    return {'operating_explanation_source': source, 'sales_explanations': values,
            'sales_explanation_refs': refs,
            'comparison_revenue_ref': ClaimDocumentReference(**{**ref,
                'reference_id': ref['reference_id'] + ':prior_revenue',
                'quote': proof['comparison_period']['metrics']['revenue']['row_text']}).to_dict(),
            'sales_comparison_heading_refs': [ClaimDocumentReference(**{**ref,
                'reference_id': ref['reference_id'] + f":comparison_heading:{v['heading_start_offset']}",
                'section': 'Item 7. Management discussion and analysis',
                'quote': v['comparison_heading']}).to_dict() for v in values]}


def _context(proof, cik):
    rows = _rows(proof, cik)
    if not rows:
        return None
    analysis = segment_analysis(proof, rows, cik=cik)
    return {'scope': 'reported_segments', 'currency': 'USD', 'segments': rows,
            'derived_ratios': analysis['derived_ratios'],
            'totals_reconciled': analysis['status'] in {'matched', 'zero_revenue'}, 'analysis': analysis}


def extract_segment_financial_context(document, *, ticker, cik):
    from .thesis_disclosures import _business_issuer_url
    if (document.document_type not in {'10-K', '20-F'} or document.publisher != 'SEC EDGAR'
            or document.source_type != 'regulatory_filing' or document.source_tier != 'primary'
            or document.extraction_method != 'html' or not document.text_ready
            or not _business_issuer_url(document.final_url, cik)):
        return []
    for proof in getattr(document, 'segment_financial_tables', ())[:1]:
        context = _context(proof, cik)
        try:
            if not context or not date.fromisoformat(proof['period_end']) <= date.fromisoformat(document.published_at) <= date.today():
                continue
            ref = ClaimDocumentReference(reference_id=f'document:{document.content_hash}:segment_table:{proof["table_number"]}',
                title=document.title or f'{ticker} {document.document_type}', provider='SEC EDGAR',
                url=document.final_url, published_at=document.published_at, section=SECTION,
                content_hash=document.content_hash, quote=proof['metrics']['revenue']['row_text']).to_dict()
            caveat_refs = [ClaimDocumentReference(reference_id=ref['reference_id'] + f':caveat:{i}',
                title=ref['title'], provider='SEC EDGAR', url=ref['url'], published_at=ref['published_at'],
                section=SECTION, content_hash=ref['content_hash'], quote=proof[key]).to_dict()
                for i, key in enumerate(('definition', 'allocation'))]
            income_ref = ClaimDocumentReference(reference_id=ref['reference_id'] + ':operating_income',
                title=ref['title'], provider='SEC EDGAR', url=ref['url'], published_at=ref['published_at'],
                section=SECTION, content_hash=ref['content_hash'],
                quote=proof['metrics']['operating_income']['row_text']).to_dict()
        except (ValueError, TypeError, KeyError):
            continue
        value = {'ticker': ticker, 'claim_kind': 'issuer_segment_financial_context',
                 'document_type': document.document_type, 'quote': ref['quote'],
                 'document_ref': ref, 'operating_income_ref': income_ref, 'caveat_refs': caveat_refs, 'proof': proof, 'segment_context': context}
        if document.document_type == '10-K':
            from .segment_sales_explanations import source_window
            fields = _explanation_fields(proof, source_window(document.text), ref, cik)
            if fields:
                value.update(fields)
        item = RetrievedEvidence(title=f'{ticker} annual segment results', source='SEC EDGAR',
            timestamp=document.published_at, summary=_summary(value), url=document.final_url,
            relevance_score=0.96, source_type='regulatory_filing', source_tier='primary',
            claim_type='reported_fact', document_type=document.document_type, filed_at=document.published_at,
            section=SECTION, extraction_method='html', reporting_period_start=context['segments'][0]['start'],
            reporting_period_end=proof['period_end'], segment_disclosures=[value])
        if bound_segment_financial_context(item, ticker=ticker, cik=cik):
            return [item]
    return []


def bound_segment_financial_context(item, *, ticker, cik):
    from .thesis_disclosures import _business_issuer_url
    values = getattr(item, 'segment_disclosures', [])
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        return None
    value = values[0]
    try:
        proof = value['proof']
        context = _context(proof, cik)
        ref = ClaimDocumentReference(**value['document_ref']).to_dict()
        explanation_keys = {'operating_explanation_source', 'sales_explanations', 'sales_explanation_refs',
                            'comparison_revenue_ref', 'sales_comparison_heading_refs'}
        if explanation_keys.intersection(value):
            fields = _explanation_fields(proof, value.get('operating_explanation_source'), ref, cik)
            if (item.document_type != '10-K' or not fields
                    or json.dumps({k: value.get(k) for k in explanation_keys}, sort_keys=True, allow_nan=False)
                    != json.dumps(fields, sort_keys=True, allow_nan=False)):
                return None
        income_ref = ClaimDocumentReference(**value['operating_income_ref']).to_dict()
        if income_ref != {**ref, 'reference_id': ref['reference_id'] + ':operating_income',
                          'quote': proof['metrics']['operating_income']['row_text']}:
            return None
        caveats = [ClaimDocumentReference(**r).to_dict() for r in value['caveat_refs']]
        if (not context or json.dumps(value['segment_context'], sort_keys=True, allow_nan=False) != json.dumps(context, sort_keys=True, allow_nan=False)
                or value['ticker'] != ticker or value['claim_kind'] != 'issuer_segment_financial_context'
                or value['document_type'] != item.document_type or item.document_type not in {'10-K', '20-F'}
                or item.source != 'SEC EDGAR' or item.source_type != 'regulatory_filing'
                or item.source_tier != 'primary' or item.claim_type != 'reported_fact'
                or item.extraction_method != 'html' or item.section != SECTION
                or item.availability_status != 'available' or item.freshness_status in {'stale', 'superseded', 'conflicting', 'unavailable'}
                or ref['provider'] != item.source or ref['url'] != item.url or not _business_issuer_url(item.url, cik)
                or not re.fullmatch(r'[0-9a-f]{64}', ref.get('content_hash', ''))
                or ref.get('section') != SECTION or ref['published_at'] != item.timestamp or item.filed_at != item.timestamp
                or ref['reference_id'] != f'document:{ref["content_hash"]}:segment_table:{proof["table_number"]}'
                or value['quote'] != ref['quote'] or ref['quote'] != proof['metrics']['revenue']['row_text']
                or item.reporting_period_start != context['segments'][0]['start']
                or item.reporting_period_end != proof['period_end']
                or not date.fromisoformat(proof['period_end']) <= date.fromisoformat(item.timestamp) <= date.today()
                or item.summary != _summary(value) or len(caveats) != 2):
            return None
        for i, (r, key) in enumerate(zip(caveats, ('definition', 'allocation'))):
            if r != {**ref, 'reference_id': ref['reference_id'] + f':caveat:{i}', 'quote': proof[key]}:
                return None
        return value
    except (KeyError, ValueError, TypeError, AttributeError):
        return None
