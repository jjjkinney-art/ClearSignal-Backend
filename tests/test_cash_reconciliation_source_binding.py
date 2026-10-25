"""Source-byte binding, not independent source authentication."""
from copy import deepcopy
import hashlib
import re
import pytest

from app.providers.sec_cash_reconciliation import parse_cash_reconciliations, reconstruct_cash_reconciliation
from app.services.cash_reconciliation_source_binding import bind_cash_reconciliation
from test_sec_cash_reconciliation import xml


def inputs(source=None):
    body = (source or xml()).encode()
    proof, = parse_cash_reconciliations(body.decode(), cik='1234567')
    return proof, dict(source_body=body, content_hash=hashlib.sha256(body).hexdigest(),
        cik='1234567', currency='USD',
        url='https://www.sec.gov/Archives/edgar/data/1234567/000123456726000001/report.htm',
        filed_at='2026-03-13', evaluated_at='2026-10-25', title='Synthetic annual report',
        document_type='10-K', availability_status='available', freshness_status='fresh')


def test_source_binding_preserves_full_rows_and_fact_anchors():
    proof, args = inputs()
    bound = bind_cash_reconciliation(proof, **args)
    assert bound and bound['bridge']['source_binding_established'] is True
    assert bound['admitted'] is bound['bridge']['admitted'] is bound['launch_ready'] is False
    assert bound['independent_origin_verification'] is False
    assert len(bound['row_references']) == len(bound['bridge']['rows']) == 4
    for row, ref in zip(bound['bridge']['rows'], bound['row_references']):
        assert ref['fact_ids'] == [v['fact_id'] for v in row['values']]
        assert ref['document_ref']['url'].endswith('#' + ref['fact_ids'][0])
        assert row['label'] in ref['document_ref']['quote']
        assert ref['document_ref']['content_hash'] == args['content_hash']


@pytest.mark.parametrize('field,value', [
    ('content_hash', '0' * 64), ('cik', '999'), ('currency', 'EUR'),
    ('url', 'https://www.sec.gov/Archives/edgar/data/999/000123456726000001/report.htm'),
    ('url', 'https://example.com/report.htm'), ('url', 'https://www.sec.gov/report.htm?token=secret'),
    ('filed_at', '2026-11-01'), ('filed_at', '2025-06-30'),
    ('evaluated_at', '2026-03-01'), ('document_type', '10-Q'),
    ('availability_status', 'unavailable'), ('freshness_status', 'stale'),
    ('title', ''), ('title', 'x' * 301), ('source_body', b'changed source'),
])
def test_metadata_mismatch_is_a_gap(field, value):
    proof, args = inputs()
    args[field] = value
    assert bind_cash_reconciliation(proof, **args) is None


def test_rehashed_capsule_with_two_offsetting_omissions_is_rejected_against_original():
    source = xml(total=(70, 80))
    depreciation = re.search(r'<tr><td>Depreciation</td>.*?</tr>', source).group()
    offset = depreciation.replace('Depreciation', 'Offset').replace('g:Depreciation', 'custom:Offset')
    offset = offset.replace('<td><ix:', '<td>(<ix:').replace('</ix:nonFraction></td><td></td>', '</ix:nonFraction></td><td>)</td>')
    proof, args = inputs(source.replace(depreciation, depreciation + offset))
    forged = deepcopy(proof)
    forged['xml'] = re.sub(r'<[^>]*tr><[^>]*td>(?:Depreciation|Offset)</[^>]*td>.*?</[^>]*tr>', '', forged['xml'])
    forged['capsule_sha256'] = hashlib.sha256(forged['xml'].encode()).hexdigest()
    assert reconstruct_cash_reconciliation(forged, cik='1234567') is not None
    assert bind_cash_reconciliation(forged, **args) is None


def test_alternative_reconciling_source_cannot_keep_original_receipt():
    proof, args = inputs()
    changed, _ = inputs(xml(amounts=(20, 20), total=(85, 90)))
    changed['source_sha256'] = proof['source_sha256']
    assert bind_cash_reconciliation(changed, **args) is None


def test_long_complete_row_is_withheld_without_clipping_or_widening_quote_cap():
    source = xml(label='A' * 180).replace('>30</ix:', '>' + '0' * 78 + '30</ix:')
    source = source.replace('>20</ix:', '>' + '0' * 78 + '20</ix:')
    proof, args = inputs(source)
    assert reconstruct_cash_reconciliation(proof, cik='1234567') is not None
    assert bind_cash_reconciliation(proof, **args) is None
