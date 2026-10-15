"""Offline analysis of supplied public-source files; no retrieval or execution authority."""
import argparse
import hashlib
import json
from itertools import islice
from pathlib import Path
import re

FACTS_LIMIT = 16_777_216
DOCUMENT_LIMIT = 15_000_000
ACHC_FACTS_URL = 'https://data.sec.gov/api/xbrl/companyfacts/CIK0001520697.json'
NPK_DOCUMENT_URL = 'https://www.sec.gov/Archives/edgar/data/80172/000143774926008214/npk20251231_10k.htm'
CONCEPTS = ('RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues',
            'OperatingIncomeLoss', 'NetIncomeLoss', 'ProfitLoss',
            'NetCashProvidedByUsedInOperatingActivities')


def analyze_achc_facts(body):
    from app.providers.sec_client import parse_company_fact_records
    from app.integrity.sec_metric_evidence import comparable_metric_evidence, _duration_matches_form
    if len(body) > FACTS_LIMIT:
        raise ValueError('facts file exceeds fixed bound')
    def invalid_constant(_):
        raise ValueError('non-finite JSON constant')
    data = json.loads(body, parse_constant=invalid_constant)
    if type(data) is not dict or str(data.get('cik')) != '1520697':
        raise ValueError('unexpected facts identity')
    rows = []
    for concept in CONCEPTS:
        for unit in ('USD', 'EUR'):
            records = parse_company_fact_records(data, concept=concept, unit=unit)
            eligible = [r for r in records if _duration_matches_form(r)]
            item = comparable_metric_evidence(records, ticker='ACHC', expected_cik='1520697',
                                              concepts=(concept,), metric_name=concept, unit=unit)
            rows.append({'concept': concept, 'unit': unit, 'parsed_records': len(records),
                'duration_eligible_records': len(eligible),
                'latest_parsed_end': max((r.end for r in records), default=None),
                'latest_duration_eligible_end': max((r.end for r in eligible), default=None),
                'comparison_selected': item is not None,
                'selected_end': item.reporting_period_end if item else None})
    return {'admitted_evidence': False, 'source_origin_verified': False,
            'claimed_source_url': ACHC_FACTS_URL, 'body_sha256': hashlib.sha256(body).hexdigest(),
            'body_bytes': len(body), 'concept_diagnostics': rows}


def analyze_npk_html(body):
    from app.services.public_document_ingestion import _HTMLTextExtractor, MAX_SEC_PERIODIC_CHARS
    from app.services.sec_risk_sections import complete_business_window, risk_sentence_spans
    if len(body) > DOCUMENT_LIMIT:
        raise ValueError('document file exceeds fixed bound')
    parser = _HTMLTextExtractor()
    parser.feed(body.decode('utf-8', errors='replace'))
    _, text, _, _ = parser.result(max_chars=MAX_SEC_PERIODIC_CHARS,
        preserve_sec_risk=True, preserve_sec_business=True, risk_form='10-K')
    window = complete_business_window(text, form='10-K')
    result = {'admitted_evidence': False, 'source_origin_verified': False,
        'claimed_source_url': NPK_DOCUMENT_URL,
        'body_sha256': hashlib.sha256(body).hexdigest(), 'body_bytes': len(body),
        'decoding': 'UTF-8 with replacement; capture encoding is not independently validated',
        'normalized_text_sha256': hashlib.sha256(text.encode()).hexdigest(),
        'text_selection': parser.text_selection, 'normalized_text_characters': len(text),
        'complete_business_window': list(window) if window else None,
        'samples': [], 'sample_limitation':
        'These are candidate sentences for manual review, not final rejection or admission results.'}
    if not window:
        return result
    start, end = window
    counts = {'length_review': 0, 'numeric_or_forward_review': 0, 'other_review': 0}
    text_budget = 1800
    for left, right in islice(risk_sentence_spans(text[start:end]), 2000):
        quote = text[start + left:start + right]
        bucket = ('length_review' if not 60 <= len(quote) <= 300 else
            'numeric_or_forward_review' if re.search(
                r'\d|[%$€£]|\b(?:will|may|could|expect|leading|best|superior)\b', quote, re.I)
            else 'other_review')
        if counts[bucket] == 2:
            continue
        counts[bucket] += 1
        row = {'review_bucket': bucket, 'start_offset': start + left,
            'end_offset': start + right, 'characters': len(quote),
            'sentence_sha256': hashlib.sha256(quote.encode()).hexdigest()}
        # Never clip a sentence into apparent admissibility.
        if len(quote) <= 600 and len(quote) <= text_budget:
            row['complete_sentence'] = quote
            text_budget -= len(quote)
        result['samples'].append(row)
        if len(result['samples']) == 6:
            break
    return result


def _read_local(path, limit):
    if path.is_symlink() or not path.is_file():
        raise ValueError('regular local input required')
    with path.open('rb') as stream:
        body = stream.read(limit + 1)
    if len(body) > limit:
        raise ValueError('input exceeds fixed byte bound')
    return body


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--achc-facts', type=Path, required=True)
    parser.add_argument('--npk-html', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    report = {'purpose': 'offline_source_gap_analysis', 'admitted_evidence': False,
        'capture_authenticity_independently_verified': False,
        'limitation': 'Local file analysis does not verify HTTP origin, media, capture time or live behavior.',
        'achc': analyze_achc_facts(_read_local(args.achc_facts, FACTS_LIMIT)),
        'npk': analyze_npk_html(_read_local(args.npk_html, DOCUMENT_LIMIT))}
    with args.output.open('x') as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
